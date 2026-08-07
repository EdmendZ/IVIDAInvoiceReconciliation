"""Governed conversion of reviewer edits into evaluation feedback."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.document_versions import ReviewAction
from app.experiments.domain import FeedbackCandidate, FeedbackClassification
from app.experiments.ports import ExperimentRepository
from app.infra.postgres_experiment_repository import ExperimentNotFound
from app.infra.postgres_review_repository import (
    PostgresReviewRepository,
    ReviewVersionNotFound,
)
from app.services.ports import DocumentDraftRepository, ExtractionRunRepository


class FeedbackPermissionDenied(PermissionError):
    pass


class FeedbackSourceIncomplete(RuntimeError):
    pass


def _normalized_description(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _line_key(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    sku = str(item.get("sku") or "").strip().casefold()
    if sku:
        return f"sku={sku}"
    description = _normalized_description(item.get("description"))
    return f"description={description}" if description else None


def _unique_index(items: list[object], field: str) -> dict[str, int] | None:
    result: dict[str, int] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return None
        value = (
            str(item.get("sku") or "").strip().casefold()
            if field == "sku"
            else _normalized_description(item.get("description"))
        )
        if not value:
            continue
        if value in result:
            return None
        result[value] = index
    return result


def _matched_lines(
    old: list[object], new: list[object]
) -> list[tuple[str, object | None, object | None]] | None:
    """Match unique SKUs first, then unique normalized descriptions."""

    old_skus = _unique_index(old, "sku")
    new_skus = _unique_index(new, "sku")
    old_descriptions = _unique_index(old, "description")
    new_descriptions = _unique_index(new, "description")
    if None in (old_skus, new_skus, old_descriptions, new_descriptions):
        return None

    matched_old: set[int] = set()
    matched_new: set[int] = set()
    pairs: list[tuple[str, object | None, object | None]] = []
    for sku in sorted(old_skus.keys() & new_skus.keys()):
        old_index = old_skus[sku]
        new_index = new_skus[sku]
        matched_old.add(old_index)
        matched_new.add(new_index)
        pairs.append((f"sku={sku}", old[old_index], new[new_index]))

    for description in sorted(old_descriptions.keys() & new_descriptions.keys()):
        old_index = old_descriptions[description]
        new_index = new_descriptions[description]
        if old_index in matched_old or new_index in matched_new:
            continue
        matched_old.add(old_index)
        matched_new.add(new_index)
        preferred = _line_key(new[new_index]) or f"description={description}"
        pairs.append((preferred, old[old_index], new[new_index]))

    for index, item in enumerate(old):
        if index not in matched_old:
            key = _line_key(item)
            if key is None:
                return None
            pairs.append((key, item, None))
    for index, item in enumerate(new):
        if index not in matched_new:
            key = _line_key(item)
            if key is None:
                return None
            pairs.append((key, None, item))
    keys = [key for key, _, _ in pairs]
    if len(keys) != len(set(keys)):
        return None
    return sorted(pairs, key=lambda item: item[0])


def iter_field_changes(
    old: object,
    new: object,
    path: str = "",
) -> Iterator[tuple[str, object, object]]:
    """Yield deterministic field diffs without positional line-item matching."""

    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            child = f"{path}.{key}" if path else key
            yield from iter_field_changes(old.get(key), new.get(key), child)
        return
    if isinstance(old, list) and isinstance(new, list):
        line_pairs = _matched_lines(old, new) if path == "items" else None
        if line_pairs is not None:
            for key, old_line, new_line in line_pairs:
                yield from iter_field_changes(
                    old_line,
                    new_line,
                    f"{path}[{key}]",
                )
            return
    if old != new:
        yield path, old, new


class FeedbackService:
    def __init__(
        self,
        *,
        review_repository: PostgresReviewRepository,
        draft_repository: DocumentDraftRepository,
        run_repository: ExtractionRunRepository,
        experiment_repository: ExperimentRepository,
    ) -> None:
        self._reviews = review_repository
        self._drafts = draft_repository
        self._runs = run_repository
        self._experiments = experiment_repository

    def collect_for_version(self, version_id: str) -> list[FeedbackCandidate]:
        version = self._reviews.get_version(version_id)
        if version is None:
            raise ReviewVersionNotFound(version_id)
        bundle = self._drafts.get_for_task(version.task_id)
        if bundle is None or bundle.draft.draft_id != version.source_draft_id:
            raise FeedbackSourceIncomplete("exact source draft is unavailable")
        run = self._runs.get(bundle.draft.run_id)
        if run is None or not run.normalizer_model or not run.prompt_version:
            raise FeedbackSourceIncomplete("model provenance is unavailable")

        existing = {
            (item.action_id, item.field_path): item
            for item in self._experiments.list_feedback_candidates()
        }
        created: list[FeedbackCandidate] = []
        for action in self._reviews.list_actions(version_id):
            if action.action not in {"document_edited", "document_reclassified"}:
                continue
            for field_path, old_value, new_value in self._changes(action):
                key = (action.action_id, field_path)
                if key in existing:
                    created.append(existing[key])
                    continue
                candidate = FeedbackCandidate(
                    candidate_id=str(
                        uuid5(NAMESPACE_URL, f"{action.action_id}:{field_path}")
                    ),
                    task_id=version.task_id,
                    draft_id=bundle.draft.draft_id,
                    version_id=version.version_id,
                    action_id=action.action_id,
                    run_id=run.run_id,
                    field_path=field_path,
                    old_value=old_value,
                    new_value=new_value,
                    document_type=version.document_type.value,
                    supplier_name=self._supplier_name(version.document_json),
                    normalizer_model=run.normalizer_model,
                    prompt_version=run.prompt_version,
                    created_at=action.created_at,
                )
                existing[key] = candidate
                created.append(candidate)
        stored_ids = {
            item.candidate_id for item in self._experiments.list_feedback_candidates()
        }
        new_items = [item for item in created if item.candidate_id not in stored_ids]
        if new_items:
            self._experiments.create_feedback_candidates(new_items)
        return created

    def confirm(
        self,
        candidate_id: str,
        classification: FeedbackClassification,
        include_in_gold: bool,
        user: AuthenticatedUser,
        confirmed_at: datetime,
    ) -> FeedbackCandidate:
        if user.role != AdminRole.ADMIN:
            raise FeedbackPermissionDenied("admin role is required")
        candidate = next(
            (
                item
                for item in self._experiments.list_feedback_candidates()
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ExperimentNotFound(candidate_id)
        target_id = candidate_id
        if candidate.confirmed_at is not None:
            replacement = candidate.model_copy(
                update={
                    "candidate_id": str(uuid4()),
                    "classification": None,
                    "include_in_gold": False,
                    "confirmed_by": None,
                    "confirmed_at": None,
                    "created_at": confirmed_at,
                    "supersedes_candidate_id": candidate.candidate_id,
                }
            )
            self._experiments.create_feedback_candidates([replacement])
            target_id = replacement.candidate_id
        return self._experiments.confirm_feedback(
            target_id,
            classification=classification,
            include_in_gold=include_in_gold,
            confirmed_by=user.user_id,
            confirmed_at=confirmed_at,
        )

    @staticmethod
    def _changes(action: ReviewAction) -> Iterator[tuple[str, Any, Any]]:
        if action.field_path:
            yield action.field_path, action.old_value, action.new_value
            return
        yield from iter_field_changes(action.old_value, action.new_value)

    @staticmethod
    def _supplier_name(document: dict) -> str | None:
        supplier = document.get("supplier")
        return supplier.get("name") if isinstance(supplier, dict) else None

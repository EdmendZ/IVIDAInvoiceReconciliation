"""Create an immutable extraction experiment definition."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.experiments.domain import (
    ExperimentDefinition,
    ExperimentRole,
    ExperimentThresholds,
)
from app.experiments.runner import load_dataset_identity
from app.evaluation.providers import (
    build_real_normalizer,
    build_real_parser,
    document_schema_version,
    evaluation_parameters,
    parser_runtime_version,
)
from app.infra.database import get_session_factory
from app.infra.database_models import AdminUserRow
from app.infra.postgres_experiment_repository import PostgresExperimentRepository


def _active_admin_id(explicit_id: str | None) -> str:
    if explicit_id:
        return explicit_id
    with get_session_factory()() as session:
        user_id = session.execute(
            select(AdminUserRow.user_id)
            .where(AdminUserRow.is_active.is_(True))
            .order_by(AdminUserRow.created_at, AdminUserRow.user_id)
            .limit(1)
        ).scalar_one_or_none()
    if user_id is None:
        raise RuntimeError("create an active admin or pass --created-by")
    return user_id


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an extraction experiment")
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--role",
        required=True,
        choices=[role.value for role in ExperimentRole],
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--created-by")
    parser.add_argument("--required-schema-valid-rate", type=Decimal, default="1")
    parser.add_argument("--minimum-field-accuracy", type=Decimal, default="0.95")
    parser.add_argument("--minimum-line-item-f1", type=Decimal, default="0.95")
    parser.add_argument("--minimum-evidence-coverage", type=Decimal, default="0.90")
    parser.add_argument("--max-cost-aud-per-document", type=Decimal)
    parser.add_argument("--require-known-cost", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    settings = get_settings()
    manifest = args.manifest.resolve()
    document_parser = build_real_parser(settings)
    normalizer = build_real_normalizer(settings)
    definition = ExperimentDefinition(
        experiment_id=str(uuid4()),
        name=args.name,
        role=ExperimentRole(args.role),
        manifest_path=str(manifest),
        dataset_identity=load_dataset_identity(manifest),
        parser_provider=document_parser.provider_name,
        parser_model=document_parser.model_name,
        parser_version=parser_runtime_version(),
        normalizer_provider=normalizer.provider_name,
        normalizer_model=normalizer.model_name,
        prompt_version=normalizer.prompt_version,
        schema_version=document_schema_version(),
        parameters=evaluation_parameters(settings),
        thresholds=ExperimentThresholds(
            required_schema_valid_rate=args.required_schema_valid_rate,
            minimum_field_accuracy=args.minimum_field_accuracy,
            minimum_line_item_f1=args.minimum_line_item_f1,
            minimum_evidence_coverage=args.minimum_evidence_coverage,
            max_cost_aud_per_document=args.max_cost_aud_per_document,
            require_known_cost=args.require_known_cost,
        ),
        created_by=_active_admin_id(args.created_by),
        created_at=datetime.now(UTC),
    )
    repository = PostgresExperimentRepository(get_session_factory())
    repository.create_definition(definition)
    print(definition.experiment_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

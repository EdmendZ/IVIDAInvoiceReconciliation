from app.core.config import Settings
from app.domain.parsing import ParseState, ParserSubmission


def test_api_tokens_are_not_in_settings_repr() -> None:
    settings = Settings(
        mineru_api_token="mineru-secret",
        normalization_api_key="normalization-secret",
    )
    rendered = repr(settings)
    assert "mineru-secret" not in rendered
    assert "normalization-secret" not in rendered


def test_parser_submission_has_stable_remote_id() -> None:
    submission = ParserSubmission(remote_job_id="batch-1")
    assert submission.remote_job_id == "batch-1"
    assert ParseState.QUEUED.value == "queued"

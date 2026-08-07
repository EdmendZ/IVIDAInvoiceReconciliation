from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_quality_lab_docs_state_safety_boundaries() -> None:
    evaluation = _read("docs/ai/09-testing-and-evaluation.md")
    interview = _read("docs/interview/model-selection.md")
    assert "失败必须进入分母" in evaluation
    assert "不会自动修改生产模型配置" in evaluation
    assert "Feedback Candidate" in interview
    assert "inconclusive" in interview


def test_quality_lab_docs_cover_operation_and_gold_governance() -> None:
    operations = _read("docs/operations/08-api-ui-and-local-run.md")
    readme = _read("README.md")
    assert "/lab" in operations
    assert "app.cli.create_experiment" in readme
    assert "app.cli.run_experiment" in operations
    assert "dataset identity" in operations
    assert "真实 API 前提" in operations
    assert "只有 `model_error`" in operations
    assert "不会自动" in readme

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_quality_lab_docs_state_safety_boundaries() -> None:
    evaluation = _read("docs/ai.md")
    assert "失败必须进入分母" in evaluation
    assert "不会自动修改生产模型配置" in evaluation
    assert "Feedback Candidate" in evaluation
    assert "inconclusive" in evaluation


def test_quality_lab_docs_cover_operation_and_gold_governance() -> None:
    evaluation = _read("docs/ai.md")
    readme = _read("README.md")
    assert "/lab" in evaluation
    assert "app.cli.create_experiment" in readme
    assert "app.cli.run_experiment" in evaluation
    assert "dataset identity" in evaluation
    assert "真实模型结论" in evaluation
    assert "`model_error`" in evaluation
    assert "不会自动" in readme

from pathlib import Path


def test_interview_docs_keep_pilot_boundary() -> None:
    text = Path("docs/demo.md").read_text(encoding="utf-8")

    assert "本机演示 Pilot" in text
    assert "自动付款" in text
    assert "MinerU" in text
    assert "确定性" in text


def test_interview_docs_reference_real_demo_entrypoints() -> None:
    script = Path("docs/demo.md").read_text(encoding="utf-8")

    assert "run_local_demo.py" in script
    assert "http://127.0.0.1:5274" in script
    assert "app/domain/workspace.py" in script

from pathlib import Path


def test_interview_docs_keep_pilot_boundary() -> None:
    root = Path("docs/interview")
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "project-story.md",
            root / "demo-script.md",
            root / "architecture.md",
        )
    )

    assert "本机演示 Pilot" in text
    assert "自动付款" in text
    assert "MinerU" in text
    assert "确定性" in text


def test_interview_docs_reference_real_demo_entrypoints() -> None:
    script = Path("docs/interview/demo-script.md").read_text(encoding="utf-8")

    assert "start_local_demo.ps1" in script
    assert "http://127.0.0.1:5274" in script
    assert "docs/interview/model-selection.md" in script

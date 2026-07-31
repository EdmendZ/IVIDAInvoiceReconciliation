from app.services.prompt_version import prompt_version


def test_prompt_version_is_stable_and_content_addressed() -> None:
    first = prompt_version("system", "user")
    second = prompt_version("system", "user")
    changed = prompt_version("system changed", "user")

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 16
    assert changed != first

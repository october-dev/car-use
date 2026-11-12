"""The CI workflow is the contract in issue #1. Guard it from drifting."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_runs_pytest_on_push_and_pull_request():
    text = WORKFLOW.read_text()
    assert "push:" in text
    assert "pull_request:" in text
    assert "uv run pytest" in text
    assert "enable-cache: true" in text
    for os_name in ("ubuntu-latest", "macos-latest"):
        assert os_name in text
    for version in ("3.11", "3.12", "3.13"):
        assert version in text

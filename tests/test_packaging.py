"""PyPI packaging: one version, and the built wheel ships the skill and scenarios."""
import subprocess
import tarfile
import zipfile
from pathlib import Path

from car_use import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_has_a_single_source():
    init = (ROOT / "src" / "car_use" / "__init__.py").read_text()
    project = (ROOT / "pyproject.toml").read_text()
    assert f'__version__ = "{__version__}"' in init
    assert 'dynamic = ["version"]' in project
    assert 'path = "src/car_use/__init__.py"' in project
    assert f'version = "{__version__}"' not in project


def test_docs_install_from_pypi():
    readme = (ROOT / "README.md").read_text()
    onboarding = (ROOT / "onboarding.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "uv tool install car-use" in readme
    assert "uv tool install car-use" in onboarding
    assert "git+https://github.com/october-dev/car-use" not in readme
    assert __version__ in changelog


def test_publish_workflow_uses_trusted_publishing_without_tokens():
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text()
    assert '"v*"' in text
    assert "uv build" in text
    assert "uv publish --trusted-publishing always" in text
    assert "id-token: write" in text
    assert "__version__" in text
    assert "GITHUB_REF_NAME" in text
    lowered = text.lower()
    assert "pypi_token" not in lowered
    assert "password" not in lowered
    assert "secrets." not in text


def test_built_wheel_includes_skill_scenarios_and_version(tmp_path):
    out = tmp_path / "dist"
    built = subprocess.run(
        ["uv", "build", "--out-dir", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(out.glob("*.whl"))
    sdists = list(out.glob("*.tar.gz"))
    assert len(wheels) == 1 and len(sdists) == 1

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        meta_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = zf.read(meta_name).decode()
    assert "car_use/SKILL.md" in names
    scenarios = [n for n in names if n.startswith("car_use/scenarios/") and n.endswith(".toml")]
    assert "car_use/scenarios/p0420.toml" in scenarios
    assert len(scenarios) >= 7
    assert f"Version: {__version__}" in metadata
    assert "License: MIT" in metadata or "License-Expression: MIT" in metadata

    with tarfile.open(sdists[0]) as tar:
        sdist_names = tar.getnames()
    assert any(n.endswith("/SKILL.md") for n in sdist_names)
    assert any(n.endswith("/scenarios/p0420.toml") for n in sdist_names)

    installed = subprocess.run(
        ["uv", "run", "--isolated", "--no-project", "--with", str(wheels[0]),
         "car-use", "--version"],
        cwd=tmp_path, capture_output=True, text=True, timeout=180,
    )
    assert installed.returncode == 0, installed.stderr
    assert installed.stdout.strip() == f"car-use {__version__}"

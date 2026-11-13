from __future__ import annotations

import tomllib
from pathlib import Path

from mendpact import __version__
from mendpact.project_init import DEFAULT_ACTION_REF

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]

    assert __version__ == version
    assert f"adhodari03/mendpact@v{version}" == DEFAULT_ACTION_REF


def test_release_smoke_targets_current_version() -> None:
    version = __version__
    workflow = (ROOT / ".github/workflows/release-smoke.yml").read_text(encoding="utf-8")

    assert f"name: MendPact v{version} release smoke" in workflow
    assert f"test/release-v{version}" in workflow
    assert f"uses: adhodari03/mendpact@v{version}" in workflow
    assert f"name: mendpact-v{version}-release-smoke" in workflow


def test_primary_readme_action_example_targets_current_version() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"uses: adhodari03/mendpact@v{__version__}" in readme

"""Keep published UI, package, API and current documentation versions consistent."""

import json
import runpy
import tomllib
from pathlib import Path

from banking_api import __version__
from banking_api.main import create_app


def test_release_version_matches_packages_lock_api_and_current_docs():
    root = Path(__file__).resolve().parents[3]
    assert __version__ == "1.0.0"
    for name in ("package.json", "apps/web/package.json", "packages/api-client/package.json"):
        assert json.loads((root / name).read_text())["version"] == __version__
    project = tomllib.loads((root / "apps/api/pyproject.toml").read_text())
    lock = tomllib.loads((root / "apps/api/uv.lock").read_text())
    assert project["project"]["version"] == __version__
    assert next(p["version"] for p in lock["package"] if p["name"] == "banking-api") == __version__
    assert create_app().openapi()["info"]["version"] == __version__
    assert f"当前版本：v{__version__}" in (root / "README.md").read_text()
    assert f"当前版本为 **v{__version__}" in (root / "docs/README.md").read_text()
    # Current docs describe the implementation; obsolete release logs are not required.
    checker = runpy.run_path(str(root / "scripts/check_docs.py"))
    errors, count = checker["validate"](root)
    assert count > 0
    assert errors == []
    # Browser labels derive from the web package; no second hardcoded version.
    version_source = (root / "apps/web/lib/version.ts").read_text()
    assert "package.json" in version_source


def test_documentation_checker_rejects_broken_links_and_missing_anchors(tmp_path):
    root = Path(__file__).resolve().parents[3]
    checker = runpy.run_path(str(root / "scripts/check_docs.py"))
    target = tmp_path / "current.md"
    target.write_text("# Current\n\n## Existing section\n")
    index = tmp_path / "README.md"
    index.write_text(
        "# Index\n\n[valid](current.md#existing-section)\n"
        "[broken](removed.md)\n[anchor](current.md#removed)\n"
        "```md\n[example](not-a-real-file.md)\n```\n"
    )
    errors = checker["link_errors"](index, tmp_path)
    assert len(errors) == 2
    assert "missing link: removed.md" in errors[0]
    assert "missing anchor: current.md#removed" in errors[1]

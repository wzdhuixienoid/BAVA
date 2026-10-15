"""Keep published UI, package, API and current documentation versions consistent."""

import json
import tomllib
from pathlib import Path

from banking_api import __version__
from banking_api.main import create_app


def test_release_version_matches_packages_lock_api_and_current_docs():
    root = Path(__file__).resolve().parents[3]
    assert __version__ == "0.11.2"
    for name in ("package.json", "apps/web/package.json", "packages/api-client/package.json"):
        assert json.loads((root / name).read_text())["version"] == __version__
    project = tomllib.loads((root / "apps/api/pyproject.toml").read_text())
    lock = tomllib.loads((root / "apps/api/uv.lock").read_text())
    assert project["project"]["version"] == __version__
    assert next(p["version"] for p in lock["package"] if p["name"] == "banking-api") == __version__
    assert create_app().openapi()["info"]["version"] == __version__
    assert f"当前版本：v{__version__}" in (root / "README.md").read_text()
    assert f"当前版本为 **v{__version__}" in (root / "docs/README.md").read_text()
    assert (root / f"docs/releases/release-notes-v{__version__}.md").is_file()
    # Browser labels derive from the web package; no second hardcoded version.
    version_source = (root / "apps/web/lib/version.ts").read_text()
    assert "package.json" in version_source

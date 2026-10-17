"""Validate current documentation structure, local links, navigation and version markers.

Uses only the standard library; does not fetch external links or load application secrets.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".venv",
    ".next",
    ".cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}
LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+[\"'][^\n]*?[\"'])?\)")


def prose(content: str) -> str:
    """Ignore examples in fenced blocks when validating Markdown links and titles."""
    lines, fence = [], None
    for line in content.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def anchors(content: str) -> set[str]:
    found, counts = set(), {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", prose(content), re.MULTILINE):
        title = re.sub(r"[^\w\-\s]", "", title.lower()).replace(" ", "-")
        number = counts.get(title, 0)
        counts[title] = number + 1
        found.add(f"{title}-{number}" if number else title)
    return found


def local_links(path: Path, root: Path = ROOT) -> list[tuple[Path, str]]:
    result = []
    for match in LINK.finditer(prose(path.read_text())):
        url = urlsplit(match[1].strip("<>"))
        if url.scheme or url.netloc:
            continue
        if url.path.startswith("/"):
            # Skill replies may link to an actual app page, e.g. [收款人管理](/payees).
            target = (
                root / "apps/web/app" / unquote(url.path).lstrip("/") / "page.tsx"
            ).resolve()
        else:
            target = (
                (path.parent / unquote(url.path)).resolve()
                if url.path
                else path.resolve()
            )
        result.append((target, unquote(url.fragment)))
    return result


def link_errors(path: Path, root: Path) -> list[str]:
    errors = []
    for target, fragment in local_links(path, root):
        if not target.is_relative_to(root):
            errors.append(
                f"{path.relative_to(root)}: link escapes repository: {target}"
            )
        elif not target.exists():
            errors.append(
                f"{path.relative_to(root)}: missing link: {target.relative_to(root)}"
            )
        elif (
            fragment
            and target.suffix == ".md"
            and fragment not in anchors(target.read_text())
        ):
            errors.append(
                f"{path.relative_to(root)}: missing anchor: {target.name}#{fragment}"
            )
    return errors


def markdown_files(root: Path) -> list[Path]:
    result = []
    for directory, children, names in os.walk(root):
        children[:] = [
            name
            for name in children
            if name not in EXCLUDED and not name.startswith(".")
        ]
        result.extend(Path(directory) / name for name in names if name.endswith(".md"))
    return sorted(result)


def migration_head(root: Path) -> str:
    revisions, parents = set(), set()
    for path in (root / "apps/api/migrations/versions").glob("*.py"):
        for statement in ast.parse(path.read_text()).body:
            if isinstance(statement, ast.Assign):
                names = [
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                ]
                value = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name
            ):
                names, value = [statement.target.id], statement.value
            else:
                continue
            if not {"revision", "down_revision"}.intersection(names):
                continue
            entry = ast.literal_eval(value)
            if "revision" in names:
                revisions.add(entry)
            elif entry is not None:
                parents.update(entry if isinstance(entry, tuple) else (entry,))
    heads = revisions - parents
    if len(heads) != 1:
        raise ValueError(f"Expected one migration head, found {sorted(heads)}")
    return heads.pop()


def validate(root: Path = ROOT) -> tuple[list[str], int]:
    root = root.resolve()
    paths, errors = markdown_files(root), []
    for path in paths:
        errors.extend(link_errors(path, root))
        # Runtime skill instructions have their own Catalog format and binding checks.
        runtime_skill = "agent_skills" in path.parts and path.name != "README.md"
        if not runtime_skill:
            headings = re.findall(r"^# .+", prose(path.read_text()), re.MULTILINE)
            if len(headings) != 1:
                errors.append(f"{path.relative_to(root)}: expected one document title")

    index = root / "docs/README.md"
    indexed = {target for target, _ in local_links(index, root)}
    current_docs = [
        path for path in paths if path.is_relative_to(root / "docs") and path != index
    ]
    for path in current_docs:
        if path not in indexed:
            errors.append(f"{path.relative_to(root)}: not listed in docs/README.md")
    for name in ("archive", "releases"):
        if (root / "docs" / name).exists():
            errors.append(
                f"docs/{name}: current documentation must not retain release archives"
            )

    version = json.loads((root / "package.json").read_text())["version"]
    head = migration_head(root)
    markers = {
        root / "README.md": (f"当前版本：v{version}", f"数据库迁移：{head}"),
        index: (f"当前版本为 **v{version}**", f"head 为 **{head}**"),
        root / "docs/development/setup.md": (f"迁移 head 为 **{head}**",),
    }
    for path, expected in markers.items():
        for marker in expected:
            if marker not in path.read_text():
                errors.append(
                    f"{path.relative_to(root)}: missing current marker: {marker}"
                )
    return errors, len(paths)


if __name__ == "__main__":
    errors, count = validate()
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        sys.exit(1)
    print(
        f"PASS {count} Markdown files: local links, anchors, titles, navigation, version and migration"
    )

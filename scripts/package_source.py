"""Build a BAVA source ZIP without local credentials, dependencies or video artifacts."""

import hashlib
import json
import os
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = ("apps", "packages", "infra", "scripts", "docs")
ROOT_FILES = (
    "README.md", "Makefile", ".env.example", ".gitignore", ".dockerignore",
    "docker-compose.yml", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml",
)
EXCLUDED_DIRECTORIES = {
    ".git", ".venv", "node_modules", ".pnpm-store", ".next", "__pycache__",
    ".pytest_cache", ".ruff_cache", "htmlcov", "dist", "build", "artifacts",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".tsbuildinfo", ".db", ".sqlite", ".sqlite3", ".dump",
    ".log", ".pem", ".key", ".p12", ".pfx", ".zip", ".mp4", ".mov",
    ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".db-wal", ".db-shm",
    ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm", ".backup", ".bak",
}


def source_files(root: Path) -> list[Path]:
    root = root.resolve()
    paths = [root / name for name in ROOT_FILES]
    for name in SOURCE_DIRECTORIES:
        for directory, children, names in os.walk(root / name):
            children[:] = sorted(
                child for child in children
                if child not in EXCLUDED_DIRECTORIES and not child.startswith(".")
            )
            paths.extend(Path(directory) / name for name in names)
    result = []
    for path in sorted(set(paths)):
        if path.name.startswith(".") and path.name not in {
            ".env.example", ".gitignore", ".dockerignore", ".gitkeep",
        }:
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Refusing source symlink: {path.relative_to(root)}")
        if not path.is_file():
            raise ValueError(f"Missing source file: {path.relative_to(root)}")
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError(f"Unexpected large source file: {path.relative_to(root)}")
        result.append(path)
    return result


def package(root: Path = ROOT) -> tuple[Path, int]:
    root = root.resolve()
    version = json.loads((root / "package.json").read_text())["version"]
    prefix = f"BAVA-v{version}-source"
    files = source_files(root)
    output = root / "dist" / f"{prefix}.zip"
    output.parent.mkdir(exist_ok=True)
    # Fixed timestamps and ordered members make identical source yield identical ZIPs.
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            member = ZipInfo(f"{prefix}/{path.relative_to(root).as_posix()}", (2020, 1, 1, 0, 0, 0))
            member.create_system = 3
            permissions = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
            member.external_attr = (stat.S_IFREG | permissions) << 16
            archive.writestr(member, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    with ZipFile(output) as archive:
        if bad_member := archive.testzip():
            raise ValueError(f"Corrupt archive member: {bad_member}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    return output, len(files)


if __name__ == "__main__":
    output, count = package()
    print(f"PASS {count} source files -> {output.relative_to(ROOT)}")
    print(f"SHA-256 -> {output.with_suffix('.zip.sha256').relative_to(ROOT)}")

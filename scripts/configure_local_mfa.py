"""Choose local verification without displaying or rotating an existing encryption key."""

import argparse
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


def configure(path: Path, method: str = "totp"):
    if method not in {"mock", "totp"}:
        raise ValueError("Unsupported verification method")
    content = (
        path.read_text()
        if path.exists()
        else (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    )
    lines = content.splitlines()
    current = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip().strip("\"'")
    if method == "mock" and current.get("APP_ENVIRONMENT") == "production":
        raise ValueError("Demo verification is forbidden in production")
    changes = {"REAUTH_PROVIDER": method}
    if method == "totp":
        encryption_key = current.get("MFA_ENCRYPTION_KEY") or Fernet.generate_key().decode()
        Fernet(encryption_key.encode())  # Never silently replace an invalid existing key.
        changes["MFA_ENCRYPTION_KEY"] = encryption_key
    updated, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in changes:
            if key not in seen:
                updated.append(f"{key}={changes[key]}")
                seen.add(key)
        else:
            updated.append(line)
    updated.extend(
        f"{key}={value}" for key, value in changes.items() if key not in seen
    )
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as target:
            temp_name = Path(target.name)
            target.write("\n".join(updated) + "\n")
        os.chmod(temp_name, 0o600)
        temp_name.replace(path)
    finally:
        if temp_name and temp_name.exists():
            temp_name.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--method", choices=("mock", "totp"), default="totp")
    args = parser.parse_args()
    configure(args.env_file, args.method)
    print(
        "已配置后端身份验证码验证，已有验证码保持不变；重启API后生效。"
        if args.method == "mock"
        else "已配置 TOTP；已有密钥保持不变。重启API后通过认证器绑定接口完成设置。"
    )

"""Prepare private local Keycloak credentials or provision its explicit BAVA identity."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ENV = ROOT / ".env.oidc.local"
REALM_FILE = ROOT / ".local/oidc/bava-realm.json"


def prepare(*, web_port: int, api_port: int, idp_port: int, database_port: int) -> None:
    if PRIVATE_ENV.exists() or REALM_FILE.exists():
        raise SystemExit("Private OIDC configuration already exists; retained without rotation.")
    web_url, api_url = f"http://localhost:{web_port}", f"http://localhost:{api_port}"
    idp_url = f"http://localhost:{idp_port}"
    subject = str(uuid4())
    password = secrets.token_urlsafe(24)
    values = {
        "APP_ENVIRONMENT": "development", "DEVELOPMENT_USER_ID": "dev-user-001",
        "AUTH_MODE": "oidc", "REAUTH_PROVIDER": "totp",
        "MFA_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "MFA_ISSUER": "BAVA",
        "OIDC_ISSUER": f"{idp_url}/realms/bava", "OIDC_AUDIENCE": "banking-api",
        "OIDC_JWKS_URL": "http://keycloak:8080/realms/bava/protocol/openid-connect/certs",
        "NEXT_PUBLIC_AUTH_MODE": "oidc", "NEXT_PUBLIC_API_BASE_URL": api_url,
        "NEXT_PUBLIC_OIDC_AUTHORITY": f"{idp_url}/realms/bava",
        "NEXT_PUBLIC_OIDC_CLIENT_ID": "bava-web", "NEXT_PUBLIC_OIDC_SCOPE": '"openid profile"',
        "CORS_ORIGINS": json.dumps([web_url]),
        "WEB_PORT": str(web_port), "API_PORT": str(api_port),
        "POSTGRES_PORT": str(database_port), "KEYCLOAK_PORT": str(idp_port),
        "OIDC_LOCAL_UID": str(os.getuid()),
        "KEYCLOAK_PUBLIC_URL": idp_url, "KEYCLOAK_ADMIN_USERNAME": "bava-admin",
        "KEYCLOAK_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "OIDC_DEMO_USERNAME": "bava-review", "OIDC_DEMO_PASSWORD": password,
        "OIDC_DEMO_SUBJECT": subject,
    }
    realm = {
        "realm": "bava", "enabled": True, "sslRequired": "none",
        "registrationAllowed": False, "resetPasswordAllowed": False,
        "accessTokenLifespan": 900,
        "users": [{
            "id": subject, "username": values["OIDC_DEMO_USERNAME"], "enabled": True,
            "emailVerified": True, "firstName": "BAVA", "lastName": "Review",
            "email": "review@example.test", "requiredActions": [],
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }],
        "clients": [{
            "clientId": "bava-web", "enabled": True, "protocol": "openid-connect",
            "publicClient": True, "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "redirectUris": [f"{web_url}/auth/popup-callback"], "webOrigins": [web_url],
            "attributes": {
                "pkce.code.challenge.method": "S256", "post.logout.redirect.uris": web_url,
            },
            "defaultClientScopes": ["basic", "profile", "email", "web-origins"],
            "protocolMappers": [{
                "name": "BAVA API audience", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {"included.custom.audience": "banking-api",
                           "access.token.claim": "true", "id.token.claim": "false"},
            }],
        }],
    }
    REALM_FILE.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Exclusive creation prevents overwriting identities or rotating existing secrets.
    for path, content in (
        (REALM_FILE, json.dumps(realm, ensure_ascii=False, indent=2) + "\n"),
        (PRIVATE_ENV, "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"),
    ):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
    print("Created .env.oidc.local and .local/oidc/bava-realm.json (private, mode 0600).")
    print("Start the OIDC Compose environment, then rerun this script with --provision.")


def provision(project: str | None) -> None:
    if not PRIVATE_ENV.is_file() or not REALM_FILE.is_file():
        raise SystemExit("Prepare the private OIDC configuration first.")
    values = dict(line.split("=", 1) for line in PRIVATE_ENV.read_text().splitlines() if "=" in line)
    command = ["docker", "compose", "--env-file", ".env", "--env-file", ".env.oidc.local",
               "-f", "docker-compose.yml", "-f", "infra/oidc/compose.yml"]
    if project:
        command.extend(["-p", project])
    command.extend([
        "exec", "-T", "api", ".venv/bin/python", "-m",
        "banking_api.security.authentication.provision", "--user-id", "dev-user-001",
        "--issuer", values["OIDC_ISSUER"], "--subject", values["OIDC_DEMO_SUBJECT"],
    ])
    subprocess.run(command, cwd=ROOT, check=True)
    print("Mapped the local Keycloak review identity to the synthetic BAVA account.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--project", help="Optional Compose project name for isolated verification")
    for name, default in (("web", 3000), ("api", 8000), ("idp", 8080), ("database", 5432)):
        parser.add_argument(f"--{name}-port", type=int, default=default, choices=range(1, 65536),
                            metavar="PORT")
    arguments = parser.parse_args()
    if arguments.provision:
        provision(arguments.project)
    else:
        ports = [arguments.web_port, arguments.api_port, arguments.idp_port, arguments.database_port]
        if len(set(ports)) != len(ports):
            parser.error("Each service needs a different port")
        prepare(web_port=arguments.web_port, api_port=arguments.api_port,
                idp_port=arguments.idp_port, database_port=arguments.database_port)

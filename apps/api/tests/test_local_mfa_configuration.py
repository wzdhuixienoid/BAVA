import runpy
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

CONFIGURE = runpy.run_path(str(Path(__file__).parents[3] / "scripts/configure_local_mfa.py"))[
    "configure"
]


def test_enable_mfa_retains_other_configuration_and_existing_key(tmp_path):
    path = tmp_path / ".env"
    key = Fernet.generate_key().decode()
    path.write_text(
        f"LLM_API_KEY=private-test-value\nMFA_ENCRYPTION_KEY={key}\nREAUTH_PROVIDER=mock\n"
    )
    CONFIGURE(path)
    assert path.read_text() == (
        f"LLM_API_KEY=private-test-value\nMFA_ENCRYPTION_KEY={key}\nREAUTH_PROVIDER=totp\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600
    CONFIGURE(path)
    assert f"MFA_ENCRYPTION_KEY={key}\n" in path.read_text()


def test_invalid_existing_encryption_key_is_not_replaced(tmp_path):
    path = tmp_path / ".env"
    original = "MFA_ENCRYPTION_KEY=invalid-key\nREAUTH_PROVIDER=mock\n"
    path.write_text(original)
    with pytest.raises(ValueError):
        CONFIGURE(path)
    assert path.read_text() == original


def test_first_configuration_uses_project_template_and_random_valid_key(tmp_path):
    path = tmp_path / ".env"
    CONFIGURE(path)
    entries = dict(
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert entries["REAUTH_PROVIDER"] == "totp"
    cipher = Fernet(entries["MFA_ENCRYPTION_KEY"].encode())
    assert cipher.decrypt(cipher.encrypt(b"test")) == b"test"


def test_switch_to_demo_preserves_existing_credentials_and_needs_no_enrollment(tmp_path):
    path = tmp_path / ".env"
    original = (
        "APP_ENVIRONMENT=development\nREAUTH_PROVIDER=totp\n"
        "MFA_ENCRYPTION_KEY=retained-key\nLLM_API_KEY=private-test-value\n"
        "MOCK_REAUTH_CODE=135790\n"
    )
    path.write_text(original)
    CONFIGURE(path, "mock")
    assert path.read_text() == original.replace("REAUTH_PROVIDER=totp", "REAUTH_PROVIDER=mock")
    assert path.stat().st_mode & 0o777 == 0o600


def test_configuration_script_rejects_demo_in_production(tmp_path):
    path = tmp_path / ".env"
    original = "APP_ENVIRONMENT=production\nREAUTH_PROVIDER=totp\n"
    path.write_text(original)
    with pytest.raises(ValueError, match="forbidden in production"):
        CONFIGURE(path, "mock")
    assert path.read_text() == original


@pytest.mark.parametrize("previous", ["135790", "private-user-selected-code"])
def test_configuration_preserves_user_selected_identity_code(tmp_path, previous):
    path = tmp_path / ".env"
    path.write_text(f"APP_ENVIRONMENT=development\nMOCK_REAUTH_CODE={previous}\n")
    CONFIGURE(path, "mock")
    assert f"MOCK_REAUTH_CODE={previous}\n" in path.read_text()

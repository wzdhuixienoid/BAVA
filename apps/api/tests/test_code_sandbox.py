import os

import pytest

from banking_api.security.code_sandbox import container_arguments, run_isolated_analysis


def test_container_has_no_bank_mount_network_or_privilege():
    command = container_arguments("banking-analysis-test")
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "65532:65532"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in command and "no-new-privileges=true" in command
    assert "--memory" in command and "--pids-limit" in command and "--cpus" in command
    assert "--volume" not in command and "--mount" not in command and "--env" not in command
    assert "--privileged" not in command and "--pid=host" not in command


async def test_sandbox_fails_closed_without_docker(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("asyncio.create_subprocess_exec", unavailable)
    result = await run_isolated_analysis("raise RuntimeError('must not execute locally')", {})
    assert result.status == "UNAVAILABLE"
    assert result.result is None
    assert "result" not in result.audit()


@pytest.mark.parametrize("code,data", [("x" * 16385, {}), ("result=1", {"x": "a" * 32769})])
async def test_sandbox_rejects_oversized_inputs(code, data):
    with pytest.raises(ValueError):
        await run_isolated_analysis(code, data)


@pytest.mark.sandbox
@pytest.mark.skipif(
    os.getenv("RUN_DOCKER_SANDBOX_TESTS") != "1", reason="explicit Docker test opt-in"
)
@pytest.mark.parametrize(
    "code,expected",
    [
        ("result = sum(input_data['values'])", "SUCCEEDED"),
        ("open('/etc/passwd', 'w').write('changed')", "REJECTED"),
        ("open('/private/tmp/banking_host_secret').read()", "REJECTED"),
        ("import socket\nsocket.create_connection(('1.1.1.1', 443), timeout=1)", "REJECTED"),
        ("print('x' * 10000000)", "REJECTED"),
        ("result = 'x' * (256 * 1024 * 1024)", "REJECTED"),
        ("while True: pass", "LIMIT"),
    ],
)
async def test_real_sandbox_isolation(code, expected):
    result = await run_isolated_analysis(code, {"values": [1, 2, 3]}, timeout=3)
    if expected == "LIMIT":
        assert result.status in {"TIMEOUT", "REJECTED"}
    else:
        assert result.status == expected
    if expected == "SUCCEEDED":
        assert result.result == 6
    else:
        assert result.result is None

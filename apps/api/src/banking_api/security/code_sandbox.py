"""Disposable Docker analysis jobs. No host mounts, credentials, network or bank authority."""

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

IMAGE = "banking-analysis-sandbox:1.0.1"
OUTPUT_LIMIT = 65536


@dataclass(frozen=True)
class SandboxResult:
    job_id: str
    code_sha256: str
    input_sha256: str
    status: str
    elapsed_ms: int
    result: Any = None

    def audit(self):
        return {key: value for key, value in asdict(self).items() if key != "result"}


def container_arguments(job_id: str) -> list[str]:
    return [
        "docker",
        "create",
        "--name",
        job_id,
        "--interactive",
        "--network",
        "none",
        "--read-only",
        "--user",
        "65532:65532",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.5",
        "--ulimit",
        "cpu=2:2",
        "--ulimit",
        "fsize=65536:65536",
        "--ulimit",
        "nofile=64:64",
        "--log-driver",
        "none",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=8m",
        "--label",
        "banking.disposable-analysis=true",
        IMAGE,
    ]


async def _bounded_read(stream):
    output = bytearray()
    while chunk := await stream.read(4096):
        output.extend(chunk)
        if len(output) > OUTPUT_LIMIT:
            raise ValueError("OUTPUT_LIMIT")
    return bytes(output)


async def run_isolated_analysis(
    code: str,
    input_data: dict,
    *,
    timeout: float = 5,
) -> SandboxResult:
    if not isinstance(code, str) or len(code.encode()) > 16384:
        raise ValueError("CODE_LIMIT")
    if not isinstance(input_data, dict):
        raise ValueError("INPUT_MUST_BE_OBJECT")
    data = json.dumps(input_data, sort_keys=True, allow_nan=False).encode()
    payload = json.dumps({"code": code, "input_data": input_data}, allow_nan=False).encode()
    if len(payload) > 32768:
        raise ValueError("INPUT_LIMIT")
    if not 0 < timeout <= 10:
        raise ValueError("TIMEOUT_LIMIT")
    job = "banking-analysis-" + uuid4().hex
    started = time.monotonic()
    status, result, process = "UNAVAILABLE", None, None
    readers = []
    try:
        create = await asyncio.create_subprocess_exec(
            *container_arguments(job),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(create.communicate(), timeout=10)
        except TimeoutError:
            create.kill()
            await create.wait()
            raise
        if create.returncode == 0:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "start",
                "--attach",
                "--interactive",
                job,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            readers = [
                asyncio.create_task(_bounded_read(process.stdout)),
                asyncio.create_task(_bounded_read(process.stderr)),
            ]
            _, stdout, _ = await asyncio.wait_for(
                asyncio.gather(process.wait(), *readers),
                timeout=timeout,
            )
            if process.returncode == 0:
                decoded = json.loads(stdout)
                if not isinstance(decoded, dict) or set(decoded) != {"result"}:
                    raise ValueError("INVALID_OUTPUT")
                result, status = decoded["result"], "SUCCEEDED"
            else:
                status = "REJECTED"
    except TimeoutError:
        status = "TIMEOUT"
    except (ValueError, OSError, BrokenPipeError):
        status = "REJECTED" if process else "UNAVAILABLE"
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        for reader in readers:
            if not reader.done():
                reader.cancel()
        if readers:
            await asyncio.gather(*readers, return_exceptions=True)
        # Even timeouts and cancelled callers remove the exact job; never touch other containers.
        try:
            cleanup = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "--force",
                job,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(cleanup.wait(), timeout=5)
        except (OSError, TimeoutError):
            pass
    return SandboxResult(
        job,
        hashlib.sha256(code.encode()).hexdigest(),
        hashlib.sha256(data).hexdigest(),
        status,
        int((time.monotonic() - started) * 1000),
        result,
    )

"""Runs ONLY in a disposable restricted container, never in the banking API process."""

import json
import sys

payload = json.loads(sys.stdin.buffer.read(32769))
code = payload["code"]
if not isinstance(code, str) or len(code.encode()) > 16384:
    raise ValueError("CODE_LIMIT")
namespace = {"input_data": payload["input_data"], "__name__": "__sandbox__"}
exec(compile(code, "<isolated-analysis>", "exec"), namespace)
output = json.dumps({"result": namespace.get("result")}, allow_nan=False)
if len(output.encode()) > 65536:
    raise ValueError("OUTPUT_LIMIT")
print(output)

"""Run generated analysis code against explicit aggregate inputs in a disposable container."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from banking_api.security.code_sandbox import run_isolated_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(
        run_isolated_analysis(
            args.code.read_text(),
            json.loads(args.input.read_text()),
        )
    )
    with args.audit.open("a") as target:
        target.write(json.dumps(result.audit(), ensure_ascii=False) + "\n")
    print(json.dumps(asdict(result), ensure_ascii=False))
    raise SystemExit(0 if result.status == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()

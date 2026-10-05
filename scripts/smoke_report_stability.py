"""Serial real-LLM report product stability; preserves every validator and Golden core."""

import argparse
import asyncio
import contextlib
import io
import json

from smoke_report_product import main as report_product
from sqlalchemy.engine import make_url

from banking_api.config.settings import Settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if not 10 <= args.runs <= 100:
        raise SystemExit("Use 10-100 runs")
    settings = Settings()
    if (
        settings.app_environment not in {"development", "test"}
        or "test" not in (make_url(settings.database_url).database or "").lower()
    ):
        raise SystemExit("Report stability requires a development/test isolated test database")
    totals = dict(
        runs=args.runs, successes=0, validation_failures=0, golden_mismatches=0, other_failures=0
    )
    for index in range(args.runs):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                await report_product()
        except Exception as exc:
            # Record transport/schema failures too, without printing credential-bearing
            # exception text. Every requested run contributes to the final totals.
            text = str(exc)
            key = (
                "golden_mismatches"
                if "Golden" in text
                else "validation_failures"
                if "REPORT_NARRATIVE_VALIDATION_FAILED" in text
                else "other_failures"
            )
            totals[key] += 1
            print(f"FAIL run={index + 1} category={key}", flush=True)
        else:
            totals["successes"] += 1
            print(f"PASS run={index + 1} golden_core_equal=true", flush=True)
    print(json.dumps(totals), flush=True)
    if totals["successes"] != totals["runs"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

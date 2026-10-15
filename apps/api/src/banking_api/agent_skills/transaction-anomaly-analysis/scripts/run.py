"""Read an anomaly snapshot from stdin; --review selects the compact projection."""

import argparse
import sys

from pydantic import ValidationError

from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
from banking_api.skills.transaction_anomaly_analysis import TransactionAnomalyAnalysisSkill


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    try:
        snapshot = TransactionAnomalySnapshot.model_validate_json(sys.stdin.read())
    except ValidationError as exc:
        print(f"Invalid anomaly snapshot: {exc}", file=sys.stderr)
        return 2
    skill = TransactionAnomalyAnalysisSkill()
    result = skill.review(snapshot) if args.review else skill.execute(snapshot)
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

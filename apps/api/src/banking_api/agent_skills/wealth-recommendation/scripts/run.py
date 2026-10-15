"""Read a validated wealth analysis from stdin and emit a customer response DTO."""

import sys

from pydantic import ValidationError

from banking_api.skills.wealth_recommendation import WealthRecommendationSkill
from banking_api.wealth.schemas import WealthAnalysis


def main():
    try:
        analysis = WealthAnalysis.model_validate_json(sys.stdin.read())
        response = WealthRecommendationSkill().present(analysis)
    except (ValidationError, ValueError, ArithmeticError) as exc:
        print(f"Invalid wealth analysis: {exc}", file=sys.stderr)
        return 2
    print(response.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

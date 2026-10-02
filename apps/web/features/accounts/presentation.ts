import type { components } from "@banking/api-client";

type AccountResult = components["schemas"]["AccountListResult"] | components["schemas"]["AccountBalanceResult"];

export function accountResults(outputs: Record<string, unknown>[]): AccountResult[] {
  // Plan results share the bank Tool format. Legacy untyped output stays in ReadPreview.
  return [...new Map(outputs.flatMap((output) => {
    if (!Array.isArray(output.account_results)) return [];
    return output.account_results.filter((result): result is AccountResult =>
      result?.kind === "ACCOUNT_LIST" || result?.kind === "ACCOUNT_BALANCE",
    );
  }).map((result) => [JSON.stringify(result), result])).values()];
}

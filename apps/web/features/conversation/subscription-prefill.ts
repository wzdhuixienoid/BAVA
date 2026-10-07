export function consumeSubscriptionPrefill(
  href: string,
  history: Pick<History, "replaceState" | "state">,
): string | null {
  const url = new URL(href);
  if (!url.searchParams.has("resume") && !url.searchParams.has("cancel")) return null;
  const resume = url.searchParams.get("resume");
  const cancel = url.searchParams.get("cancel");
  url.searchParams.delete("resume");
  url.searchParams.delete("cancel");
  history.replaceState(history.state, "", `${url.pathname}${url.search}${url.hash}`);
  return resume ? `恢复${resume}订阅` : cancel ? `取消${cancel}` : "";
}

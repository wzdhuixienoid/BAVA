import type { components } from "@banking/api-client";
import { StatusBadge } from "./StatusBadge";

export function TaskStatus({ status }: { status: components["schemas"]["TaskStatus"] }) {
  return <StatusBadge status={status} />;
}

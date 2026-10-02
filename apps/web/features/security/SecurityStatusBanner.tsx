import { StatusBadge } from "@/components/agent-ui/StatusBadge";
import type { components } from "@banking/api-client";

type SecurityStatus = components["schemas"]["SecurityStatus"];

export function SecurityStatusBanner({ status }: { status: SecurityStatus | null }) {
  if (!status || status.status !== "WRITE_LOCKED") return null;
  const reason =
    status.reason_code === "CONTROL_BYPASS"
      ? "检测到连续未满足安全条件的操作请求，新的业务写操作已暂时暂停。"
      : "检测到连续安全验证失败，新的业务写操作已暂时暂停。";
  const restoreAt = status.locked_until
    ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(
        new Date(status.locked_until),
      )
    : "请稍后重试";
  return (
    <div className="border-b border-red-200 bg-red-50 px-6 py-4 text-red-900" role="status">
      <p className="font-bold">安全保护已启动 <StatusBadge status={status.status} /></p>
      <p className="mt-1 text-sm">{reason}</p>
      <p className="mt-2 text-xs font-semibold">恢复时间：{restoreAt}</p>
    </div>
  );
}

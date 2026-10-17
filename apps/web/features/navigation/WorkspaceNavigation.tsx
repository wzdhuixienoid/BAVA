import Link from "next/link";

const services = [
  { href: "/transfers", label: "转账与收款" },
  { href: "/subscriptions", label: "订阅管理" },
  { href: "/wealth", label: "理财中心" },
  { href: "/reports", label: "历史消费报告" },
];

export function WorkspaceNavigation() {
  return (
    <nav aria-label="功能导航" className="mb-5 space-y-3">
      <Link href="/dashboard" className="block rounded-lg bg-slate-800 px-4 py-2.5 text-center text-sm font-semibold text-cyan-100 hover:bg-slate-700">
        金融总览 Dashboard
      </Link>
      {services.map(({ href, label }) => (
        <Link key={href} href={href} className="block rounded-lg border border-slate-700 px-4 py-2.5 text-center text-sm font-semibold text-slate-200 hover:bg-slate-900">
          {label}
        </Link>
      ))}
    </nav>
  );
}

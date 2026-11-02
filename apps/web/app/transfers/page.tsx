import Link from "next/link";
import { APP_VERSION } from "@/lib/version";

const services = [
  {
    href: "/scheduled-transfers",
    title: "预约与周期转账",
    description: "查看预约、周期任务与每期付款结果，管理后续转账安排。",
  },
  {
    href: "/aa",
    title: "AA 收款与付款",
    description: "查看发起的收款请求、待付款份额与收款进度。",
  },
  {
    href: "/payees",
    title: "收款人管理",
    description: "新增或维护收款人，核对收款银行与账户资料。",
  },
];

export default function TransfersPage() {
  return (
    <main className="min-h-screen min-w-0 bg-slate-50">
      <div className="mx-auto max-w-6xl space-y-8 px-4 py-6 sm:px-8 sm:py-10">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-wider text-cyan-700">BAVA · v{APP_VERSION}</p>
            <h1 className="mt-2 text-3xl font-semibold text-slate-950">转账与收款</h1>
            <p className="mt-2 text-sm text-slate-500">管理转账安排、AA 收付款与收款人。</p>
          </div>
          <Link href="/" className="rounded-lg border bg-white px-3 py-2 text-sm hover:bg-slate-100">返回工作台</Link>
        </header>
        <nav aria-label="转账与收款服务" className="grid gap-4 md:grid-cols-3">
          {services.map(({ href, title, description }) => (
            <Link key={href} href={href} className="group flex flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-cyan-300 hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-600">
              <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
              <p className="mt-3 flex-1 text-sm leading-6 text-slate-500">{description}</p>
              <span aria-hidden="true" className="mt-6 text-sm font-semibold text-cyan-700 group-hover:text-cyan-900">进入管理 →</span>
            </Link>
          ))}
        </nav>
        <section className="rounded-2xl border border-slate-200 bg-white p-6">
          <h2 className="font-semibold text-slate-950">在工作台发起转账与收款</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">告诉银行助理你的需求，例如“从工资卡给李小雨转 100 元”或“聚餐 100 元，和张三、李四 AA，我也参与”。助理会引导你核对资料并完成确认。</p>
          <Link href="/" className="mt-4 inline-block rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-800">前往工作台</Link>
        </section>
      </div>
    </main>
  );
}

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 银行助理 — Agent Runtime v0.2.2",
  description: "支持账户列表与余额查询的只读 AI 银行助理",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

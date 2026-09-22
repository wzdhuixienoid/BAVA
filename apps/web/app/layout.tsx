import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 银行助理",
  description: "支持账户查询、余额查询和确定性消费分析的只读 AI 银行助理",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

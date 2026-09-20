import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 银行助理 — 启动骨架",
  description: "AI 银行助理应用骨架",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

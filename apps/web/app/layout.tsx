import type { Metadata } from "next";
import "./globals.css";
import { AuthGate } from "@/components/auth/AuthGate";
import { AuthProvider } from "@/lib/auth/AuthProvider";

export const metadata: Metadata = {
  title: "AI 银行助理",
  description: "支持账户查询、余额查询和确定性消费分析的只读 AI 银行助理",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AuthProvider>
          <AuthGate>{children}</AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}

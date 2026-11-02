import type { Metadata } from "next";
import "./globals.css";
import { AuthGate } from "@/components/auth/AuthGate";
import { AuthProvider } from "@/lib/auth/AuthProvider";

export const metadata: Metadata = {
  title: "BAVA · Banking AI for Verified Actions",
  description: "BAVA 以 Ask. Plan. Verify. Act. 为理念，支持账户分析、订阅管理、智能转账与模拟理财，实现可核验、可追溯的受控执行。",
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

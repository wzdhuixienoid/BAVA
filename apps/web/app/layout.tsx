import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Banking Agent — Bootstrap",
  description: "Iteration 0 application skeleton",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}


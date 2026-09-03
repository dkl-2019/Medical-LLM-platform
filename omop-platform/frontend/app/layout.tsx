import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OMOP 医疗数据治理平台",
  description: "AI驱动的医疗数据标准化平台",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

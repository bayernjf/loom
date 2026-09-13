import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Loom",
  description: "Private-domain content production whitelist platform",
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

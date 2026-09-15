import { redirect } from "next/navigation";

// Q97 接缝③：语言根路径直接进工作台（D5 菜单 1）。
export default async function LocaleHome({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect(`/${locale}/workbench`);
}

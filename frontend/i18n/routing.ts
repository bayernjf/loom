import { defineRouting } from "next-intl/routing";

// Q96（docs/18 §2.1）：V1 仅注册 zh-CN；V3 启用外语时在此追加 locale，
// 组件与路由零改动。
export const routing = defineRouting({
  locales: ["zh-CN"],
  defaultLocale: "zh-CN",
});

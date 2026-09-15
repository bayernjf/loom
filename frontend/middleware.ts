import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

// 无语言前缀请求（/、/foo）307 到 /zh-CN/...（next-intl createMiddleware 默认，实测）；
// api/_next/带点文件不走中间件。
export default createMiddleware(routing);

export const config = {
  matcher: "/((?!api|_next|_vercel|.*\\..*).*)",
};

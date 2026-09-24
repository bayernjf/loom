// Q178：内部运营个人访问令牌（PAT）的浏览器侧载体——httpOnly cookie。
// 仅在 Next 服务端（RSC / Server Action / Route Handler）可读写，浏览器 JS 不可见，
// 不会进入客户端包；lib/api 的服务端请求统一读取本 cookie 注入 Authorization: Bearer。
// 门控（LOOM_STAFF_AUTH_ENABLED）由后端单边控制：门控关无 cookie 即沿用 V1 env 自报。
import { cookies } from "next/headers";

export const STAFF_COOKIE = "loom_staff_token";

export async function getStaffToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(STAFF_COOKIE)?.value ?? null;
}

export async function setStaffToken(token: string): Promise<void> {
  const store = await cookies();
  store.set(STAFF_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
}

export async function clearStaffToken(): Promise<void> {
  const store = await cookies();
  store.delete(STAFF_COOKIE);
}

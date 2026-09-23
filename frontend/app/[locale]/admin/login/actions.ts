"use server";

// Q178：内部运营登录录入 Server Action——粘贴 staff PAT，经后端 /api/auth/me 自检
// （门控开返回人员/角色，门控关返回 400），通过后写入 httpOnly cookie；登出清 cookie。
// 不做密码/注册/找回（公网自助形态 Q144 已 NO-GO，属 V2）。
import { ApiError, getStaffMe } from "@/lib/api";
import type { StaffMe } from "@/lib/api";
import { clearStaffToken, setStaffToken } from "@/lib/staff-auth";

export type { StaffMe };

export type StaffLoginResult =
  | ({ ok: true } & StaffMe)
  | { ok: false; status: "empty" | "disabled" | 401 | "unknown"; detail: string | null };

export async function loginStaffAction(token: string): Promise<StaffLoginResult> {
  const trimmed = token.trim();
  if (!trimmed) return { ok: false, status: "empty", detail: null };
  try {
    const me = await getStaffMe(trimmed);
    await setStaffToken(trimmed);
    return { ok: true, ...me };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 400) return { ok: false, status: "disabled", detail: null };
      if (err.status === 401) return { ok: false, status: 401, detail: null };
      return { ok: false, status: "unknown", detail: null };
    }
    throw err;
  }
}

export async function logoutStaffAction(): Promise<{ ok: true }> {
  await clearStaffToken();
  return { ok: true };
}

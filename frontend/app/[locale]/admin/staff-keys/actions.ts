"use server";

// Q178：内部运营个人访问令牌（PAT）治理 Server Action——签发（secret 仅一次返回）
// 与吊销。后端在 service 层硬闸 platform_admin；本地缺身份/缺角色零请求，同 Q167。
// client 岛只允许调用本模块，禁直连 lib/api。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  issueStaffKey,
  revokeStaffKey,
} from "@/lib/api";
import type { StaffKeyView } from "@/lib/api";
export type { StaffKeyView };

// 可签发的内部角色（与后端 INTERNAL_STAFF_ROLES 对齐，不含客户角色 whitelist_owner）。
// 角色码为系统标识，按 docs/18 原样直出，不进消息表翻译。
export const STAFF_ROLE_CODES = [
  "operations",
  "platform_admin",
  "product_reviewer",
  "dictionary_admin",
  "internal_compliance",
] as const;
export type StaffRoleCode = (typeof STAFF_ROLE_CODES)[number];

const KNOWN_STATUSES = new Set([400, 401, 403, 404, 409, 422]);

export type StaffKeyActionResult =
  | { ok: true; secret?: string }
  | { ok: false; status: 400 | 401 | 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    return typeof parsed.detail === "string" && parsed.detail
      ? parsed.detail
      : null;
  } catch {
    return null;
  }
}

function failure(err: unknown): StaffKeyActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 400 | 401 | 403 | 404 | 409 | 422,
      detail: errorDetail(err.message),
    };
  }
  // 非 ApiError（如 request 层 401 触发的 NEXT_REDIRECT）必须向上冒泡，不得吞掉。
  throw err;
}

function guardPlatform(): StaffKeyActionResult | null {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.includes("platform_admin"))
    return { ok: false, status: "missing_role" };
  return null;
}

function sanitizeRoles(roles: string[]): string[] {
  const allowed = new Set<string>(STAFF_ROLE_CODES);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const role of roles) {
    const trimmed = role.trim();
    if (allowed.has(trimmed) && !seen.has(trimmed)) {
      seen.add(trimmed);
      out.push(trimmed);
    }
  }
  return out;
}

export async function issueStaffKeyAction(
  staffId: string,
  staffName: string,
  roles: string[],
): Promise<StaffKeyActionResult> {
  const blocked = guardPlatform();
  if (blocked) return blocked;
  const id = staffId.trim();
  const name = staffName.trim();
  const cleanRoles = sanitizeRoles(roles);
  if (!id || !name || cleanRoles.length === 0)
    return { ok: false, status: 422, detail: null };
  try {
    const issued = await issueStaffKey({
      staff_id: id,
      staff_name: name,
      roles: cleanRoles,
    });
    return { ok: true, secret: issued.secret };
  } catch (err) {
    return failure(err);
  }
}

export async function revokeStaffKeyAction(
  keyId: string,
): Promise<StaffKeyActionResult> {
  const blocked = guardPlatform();
  if (blocked) return blocked;
  const trimmed = keyId.trim();
  if (!trimmed) return { ok: false, status: 422, detail: null };
  try {
    await revokeStaffKey(trimmed);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

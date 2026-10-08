"use server";

// Q177：D3.5 白名单组装引擎运营只读首片——六层原料包按需查询 Server Action。
// 纯只读：不做任何写操作、不触发列表刷新；client 岛只允许调本模块，禁直连
// lib/api（check-admin 守卫）。读 operations|platform_admin，与后端 _query_actor 对齐。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getAdminFcwMaterial,
  revokeAdminFcw,
} from "@/lib/api";

// client 岛禁引 @/lib/api（check-admin 守卫），原料包视图类型经本模块转出。
import type { FcwMaterialPack } from "@/lib/api";
export type { FcwMaterialPack };

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export type FcwMaterialResult =
  | { ok: true; pack: FcwMaterialPack }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

// FastAPI 错误体 {"detail": "..."}；lib/api 将其 JSON.stringify 进 Error.message。
function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object") return JSON.stringify(detail);
    return null;
  } catch {
    return null;
  }
}

export async function getFcwMaterialAction(
  finalId: string,
): Promise<FcwMaterialResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations" || r === "platform_admin"))
    return { ok: false, status: "missing_role" };
  try {
    const pack = await getAdminFcwMaterial(finalId);
    return { ok: true, pack };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return {
        ok: false,
        status: err.status as 403 | 404 | 409 | 422,
        detail: errorDetail(err.message),
      };
    }
    return { ok: false, status: "unknown" };
  }
}

// Q321：冻结管理——作废当前快照（Q251 裁决 b）。写闸＝operations（与后端
// require_internal_actor(OPERATIONS) 对齐）；reason 必填；成功后由岛内提示
// 重冻新版走组装台「复用」预填（不自动跳转、不刷新列表，保持零副作用契约）。
export type RevokeFcwResult =
  | { ok: true; finalId: string }
  | { ok: false; status: 403 | 404 | 409 | 422 | "unconfigured" | "missing_role" | "unknown"; detail: string | null };

export async function revokeFcwAction(
  finalId: string,
  reason: string,
): Promise<RevokeFcwResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured", detail: null };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations"))
    return { ok: false, status: "missing_role", detail: null };
  if (!reason.trim())
    return { ok: false, status: 422, detail: "reason is required" };
  try {
    await revokeAdminFcw(finalId, reason.trim());
    return { ok: true, finalId };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return {
        ok: false,
        status: err.status as 403 | 404 | 409 | 422,
        detail: errorDetail(err.message),
      };
    }
    return { ok: false, status: "unknown", detail: null };
  }
}

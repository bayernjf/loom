"use server";

// Q129/Q130：管理端效果运营台 Server Action——孤儿单条认领、批量认领（整批
// all-or-nothing）、取消认领/解绑、成品时序查询。写口 operations 硬闸（角色
// 缺失本地零请求，同 Q124/Q125）；client 岛只允许调用本模块，禁直连 lib/api。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  batchClaimEffects,
  claimEffect,
  getEffectSeries,
  unclaimEffect,
} from "@/lib/api";

// client 岛禁引 @/lib/api（check-admin 守卫），记录视图类型经本模块转出。
import type { EffectRecordView } from "@/lib/api";
export type { EffectRecordView };

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export type EffectActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

export type EffectSeriesResult =
  | { ok: true; rows: EffectRecordView[] }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "unknown" };

// FastAPI 错误体 {"detail": "..."} 或批量 422 的 {"detail": {index,field,message}}；
// lib/api 将其 JSON.stringify 进 Error.message。
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

function failure(err: unknown): EffectActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 403 | 404 | 409 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

function guardWrite(): EffectActionResult | null {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.includes("operations"))
    return { ok: false, status: "missing_role" };
  return null;
}

// Q127：单条孤儿认领。
export async function claimEffectAction(
  recordId: string,
  contentId: string,
): Promise<EffectActionResult> {
  const blocked = guardWrite();
  if (blocked) return blocked;
  const rid = recordId.trim();
  const cid = contentId.trim();
  if (!rid || !cid) return { ok: false, status: 422, detail: null };
  try {
    await claimEffect(rid, cid);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

// Q129：批量认领（整批 all-or-nothing；任一条失败整批拒）。
export async function batchClaimEffectsAction(
  items: { record_id: string; content_id: string }[],
): Promise<EffectActionResult> {
  const blocked = guardWrite();
  if (blocked) return blocked;
  const normalized = items
    .map((item) => ({
      record_id: item.record_id.trim(),
      content_id: item.content_id.trim(),
    }))
    .filter((item) => item.record_id);
  if (normalized.length === 0)
    return { ok: false, status: 422, detail: null };
  if (normalized.some((item) => !item.content_id))
    return { ok: false, status: 422, detail: null };
  const recordIds = normalized.map((item) => item.record_id);
  if (new Set(recordIds).size !== recordIds.length)
    return { ok: false, status: 422, detail: null };
  try {
    await batchClaimEffects(normalized);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

// Q129：取消认领/解绑。
export async function unclaimEffectAction(
  externalContentId: string,
): Promise<EffectActionResult> {
  const blocked = guardWrite();
  if (blocked) return blocked;
  const externalId = externalContentId.trim();
  if (!externalId) return { ok: false, status: 422, detail: null };
  try {
    await unclaimEffect(externalId);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

// Q126：成品效果时序只读查询（operations | platform_admin 读口）。
export async function queryEffectSeriesAction(
  contentId: string,
): Promise<EffectSeriesResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const cid = contentId.trim();
  if (!cid) return { ok: false, status: 422, detail: null };
  try {
    const rows = await getEffectSeries(cid, { limit: 100 });
    return { ok: true, rows };
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

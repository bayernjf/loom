"use server";

// Q306：Q38 降级动作字典的 Server Action。后端两口走 Q203/Q242 的 `require_internal_actor`
// ——门控关着也自行验真 staff 令牌，所以正文里自报角色不再是身份；这里不预检角色，
// 只把 401（没令牌/令牌失效）与 403（令牌没 dictionary_admin）分开报给界面。
import { ApiError, archiveDowngradeAction, upsertDowngradeAction } from "@/lib/api";
export type { DowngradeActionView } from "@/lib/api";

const KNOWN_STATUSES = new Set([401, 403, 404, 422]);

export type DowngradeActionResult =
  | { ok: true }
  | { ok: false; status: 401 | 403 | 404 | 422; detail: string | null }
  | { ok: false; status: "unknown" };

function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    return typeof parsed.detail === "string" && parsed.detail ? parsed.detail : null;
  } catch {
    return null;
  }
}

function failure(err: unknown): DowngradeActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 401 | 403 | 404 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

export async function saveDowngradeActionAction(input: {
  code: string;
  name: string;
  why: string;
}): Promise<DowngradeActionResult> {
  if (!input.code.trim()) return { ok: false, status: 422, detail: null };
  try {
    await upsertDowngradeAction({ code: input.code, name: input.name, why: input.why });
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

export async function archiveDowngradeActionAction(
  code: string,
): Promise<DowngradeActionResult> {
  if (!code.trim()) return { ok: false, status: 422, detail: null };
  try {
    await archiveDowngradeAction(code.trim());
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

"use server";

import {
  ADMIN_ROLE_LIST,
  adminDiscardContent,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  setPublishInfo,
} from "@/lib/api";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

// FastAPI 错误体为 {"detail": "..."}；lib/api 将其 JSON.stringify 进 Error.message。
function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    return typeof parsed.detail === "string" && parsed.detail ? parsed.detail : null;
  } catch {
    return null;
  }
}

export type ContentOpsResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

function failure(err: unknown): ContentOpsResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 403 | 404 | 409 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

// Q125/Q60c：运营回填平台链接/ID（写口 operations 硬闸）。
export async function setPublishInfoAction(
  contentId: string,
  url: string,
  platformPostId?: string,
): Promise<ContentOpsResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = contentId.trim();
  const trimmedUrl = url.trim();
  if (!id || !trimmedUrl) return { ok: false, status: 422, detail: null };
  if (!ADMIN_ROLE_LIST.includes("operations")) {
    return { ok: false, status: "missing_role" };
  }
  const trimmedPostId = platformPostId?.trim();
  try {
    await setPublishInfo(id, trimmedUrl, trimmedPostId || undefined);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

// Q124/Q56-b：运营作废骨架回池（写口 operations 硬闸，难产原因必填）。
export async function discardContentAction(
  contentId: string,
  reason: string,
): Promise<ContentOpsResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = contentId.trim();
  const trimmedReason = reason.trim();
  if (!id || !trimmedReason) return { ok: false, status: 422, detail: null };
  if (!ADMIN_ROLE_LIST.includes("operations")) {
    return { ok: false, status: "missing_role" };
  }
  try {
    await adminDiscardContent(id, trimmedReason);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

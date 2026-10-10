"use server";

import {
  ADMIN_ROLE_LIST,
  adminDiscardContent,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getAdminContentDetail,
  getAdminFcwMaterial,
  getAdminScriptRecheck,
  setPublishInfo,
  type ContentProductView,
  type FcwMaterialPack,
  type ScriptRecheckView,
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

// Q324：video-studio 生成结果区——成品详情（含 body=video_ref），只读、无写闸。
// Q326：内容运营台是跨租户管理页，详情改走管理端只读口 getAdminContentDetail；
// 原先复用客户租户隔离口 getContent（tenant 固定为占位租户）会让非该租户成品 404。
export type ContentDetailResult =
  | { ok: true; content: ContentProductView }
  | { ok: false; status: 403 | 404 | "unknown" };

export async function getContentDetailAction(
  contentId: string,
): Promise<ContentDetailResult> {
  const id = contentId.trim();
  if (!id) return { ok: false, status: "unknown" };
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unknown" };
  try {
    const content = await getAdminContentDetail(id);
    return { ok: true, content };
  } catch (err) {
    if (err instanceof ApiError && [403, 404].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 };
    }
    return { ok: false, status: "unknown" };
  }
}

// Q324：video-studio 白名单信息区——六层原料包（Q177 管理端只读口，读闸放行）。
export type WhitelistMaterialResult =
  | { ok: true; pack: FcwMaterialPack }
  | { ok: false; status: 403 | 404 | "unknown" };

export async function getVideoWhitelistMaterialAction(
  finalId: string,
): Promise<WhitelistMaterialResult> {
  const id = finalId.trim();
  if (!id) return { ok: false, status: "unknown" };
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unknown" };
  try {
    const pack = await getAdminFcwMaterial(id);
    return { ok: true, pack };
  } catch (err) {
    if (err instanceof ApiError && [403, 404].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 };
    }
    return { ok: false, status: "unknown" };
  }
}

// Q328（D2 甲）：video-studio 内容清洗区——FCW 表达层脚本文本只读 CCR 复检。
// 只读无写闸；text_present=false＋detail（未发证/无文本）为正常业务结果。
export type ScriptRecheckResult =
  | { ok: true; check: ScriptRecheckView }
  | { ok: false; status: 403 | 404 | "unknown" };

export async function getScriptRecheckAction(
  contentId: string,
): Promise<ScriptRecheckResult> {
  const id = contentId.trim();
  if (!id) return { ok: false, status: "unknown" };
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unknown" };
  try {
    const check = await getAdminScriptRecheck(id);
    return { ok: true, check };
  } catch (err) {
    if (err instanceof ApiError && [403, 404].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 };
    }
    return { ok: false, status: "unknown" };
  }
}

// Q336：video-studio 分段编目（①甲）＋原片留档（③甲）操作面。
// 写口 operations 凭证闸；人员以已验真令牌为准（body.actor 仅为占位）。
export type VideoSegmentsResult =
  | { ok: true; segments: import("@/lib/api").VideoSegmentView[] }
  | { ok: false; status: 403 | 404 | "unknown" };

export async function listVideoSegmentsAction(
  contentId: string,
): Promise<VideoSegmentsResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unknown" };
  try {
    const { listVideoSegments } = await import("@/lib/api");
    return { ok: true, segments: await listVideoSegments(contentId) };
  } catch (err) {
    if (err instanceof ApiError && [403, 404].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 };
    }
    return { ok: false, status: "unknown" };
  }
}

export type VideoSegmentSaveResult =
  | { ok: true; needsRegen: boolean }
  | { ok: false; status: 403 | 404 | 422 | "missing_role" | "unconfigured" | "unknown" };

export async function createVideoSegmentAction(
  contentId: string,
  type: string,
  text: string,
): Promise<VideoSegmentSaveResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.includes("operations")) {
    return { ok: false, status: "missing_role" };
  }
  if (!text.trim()) return { ok: false, status: 422 };
  try {
    const { createVideoSegment } = await import("@/lib/api");
    await createVideoSegment(contentId, { type, text: text.trim() });
    return { ok: true, needsRegen: false };
  } catch (err) {
    if (err instanceof ApiError && [403, 404, 422].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 | 422 };
    }
    return { ok: false, status: "unknown" };
  }
}

export async function updateVideoSegmentTextAction(
  segmentId: string,
  text: string,
): Promise<VideoSegmentSaveResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.includes("operations")) {
    return { ok: false, status: "missing_role" };
  }
  if (!text.trim()) return { ok: false, status: 422 };
  try {
    const { updateVideoSegment } = await import("@/lib/api");
    const result = await updateVideoSegment(segmentId, { text: text.trim() });
    return { ok: true, needsRegen: result.needs_regen };
  } catch (err) {
    if (err instanceof ApiError && [403, 404, 422].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 | 422 };
    }
    return { ok: false, status: "unknown" };
  }
}

export type VideoObjectsResult =
  | { ok: true; objects: import("@/lib/api").VideoObjectView[] }
  | { ok: false; status: 403 | 404 | "unknown" };

export async function listVideoObjectsAction(
  contentId: string,
): Promise<VideoObjectsResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unknown" };
  try {
    const { listVideoObjects } = await import("@/lib/api");
    return { ok: true, objects: await listVideoObjects(contentId) };
  } catch (err) {
    if (err instanceof ApiError && [403, 404].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 };
    }
    return { ok: false, status: "unknown" };
  }
}

export type VideoObjectUploadResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 422 | 502 | 503 | "missing_role" | "unconfigured" | "unknown" };

export async function uploadVideoObjectAction(
  contentId: string,
  filename: string,
  base64: string,
  contentType: string,
): Promise<VideoObjectUploadResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.includes("operations")) {
    return { ok: false, status: "missing_role" };
  }
  if (!filename.trim() || !base64) return { ok: false, status: 422 };
  try {
    const { uploadVideoObject } = await import("@/lib/api");
    const bytes = Buffer.from(base64, "base64");
    await uploadVideoObject(
      contentId,
      filename.trim(),
      new Blob([bytes], { type: contentType || "application/octet-stream" }),
    );
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError && [403, 404, 422, 502, 503].includes(err.status)) {
      return { ok: false, status: err.status as 403 | 404 | 422 | 502 | 503 };
    }
    return { ok: false, status: "unknown" };
  }
}

"use server";

// Q122：客户内容页写操作（客户审阅 Q59 + Q56-a 人工编辑）。
// 生成 / 重生成是 operations 端点（Q116 定稿），不在此外放；身份 roles 恒空。
import {
  ApiError,
  CURRENT_TENANT_ID,
  approveContent,
  customerBackfillEffects,
  editContentBody,
  rejectContent,
  reviseContent,
  type EffectBatchReceipt,
} from "@/lib/api";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export type ContentActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422 }
  | { ok: false; status: "unconfigured" | "unknown" };

function failure(err: unknown): ContentActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status))
    return { ok: false, status: err.status as 403 | 404 | 409 | 422 };
  return { ok: false, status: "unknown" };
}

export async function decideContentAction(
  contentId: string,
  decision: "approve" | "reject" | "revise",
  reason?: string,
): Promise<ContentActionResult> {
  if (!contentId.trim()) return { ok: false, status: 422 };
  // reject 必带非空原因（后端 422 同口径，前端先挡一次）。
  if (decision === "reject" && !reason?.trim()) return { ok: false, status: 422 };
  try {
    if (decision === "approve") await approveContent(contentId);
    else if (decision === "reject") await rejectContent(contentId, reason as string);
    else await reviseContent(contentId);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

export async function saveContentBodyAction(
  contentId: string,
  body: string,
): Promise<ContentActionResult> {
  if (!contentId.trim()) return { ok: false, status: 422 };
  if (!body.trim()) return { ok: false, status: 422 };
  try {
    await editContentBody(contentId, body);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

// Q128/Q131：客户效果手工回填（客户专用通道，无 Agent Key、绝不产生孤儿）。
// V1 仅单条录入；capturedAt 必须是带时区的 ISO 串（岛端用本地时间转 toISOString）。
export type BackfillActionResult =
  | { ok: true; receipt: EffectBatchReceipt }
  | {
      ok: false;
      status: 403 | 404 | 409 | 422 | "unconfigured" | "unknown";
      detail: string | null;
    };

function errorDetail(err: ApiError): string | null {
  try {
    const parsed = JSON.parse(err.message) as unknown;
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      if (typeof obj.message === "string") {
        const field = typeof obj.field === "string" ? `${obj.field}: ` : "";
        return `${field}${obj.message}`;
      }
      return JSON.stringify(parsed);
    }
  } catch {
    return err.message || null;
  }
  return null;
}

export async function backfillEffectAction(
  contentId: string,
  platformPostId: string,
  capturedAt: string,
  metrics: Record<string, number>,
): Promise<BackfillActionResult> {
  if (!CURRENT_TENANT_ID) return { ok: false, status: "unconfigured", detail: null };
  if (!contentId.trim() || !platformPostId.trim() || !capturedAt)
    return { ok: false, status: 422, detail: null };
  try {
    const receipt = await customerBackfillEffects(CURRENT_TENANT_ID, [
      {
        content_id: contentId,
        platform_post_id: platformPostId,
        captured_at: capturedAt,
        metrics,
      },
    ]);
    return { ok: true, receipt };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status))
      return {
        ok: false,
        status: err.status as 403 | 404 | 409 | 422,
        detail: errorDetail(err),
      };
    return { ok: false, status: "unknown", detail: null };
  }
}

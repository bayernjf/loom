"use server";

// Q122：客户内容页写操作（客户审阅 Q59 + Q56-a 人工编辑）。
// 生成 / 重生成是 operations 端点（Q116 定稿），不在此外放；身份 roles 恒空。
import {
  ApiError,
  approveContent,
  editContentBody,
  rejectContent,
  reviseContent,
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

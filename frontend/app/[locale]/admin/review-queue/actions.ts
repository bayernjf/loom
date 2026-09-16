"use server";

import {
  ApiError,
  batchApprove,
  CURRENT_ADMIN_ACTOR_ID,
  decideCandidate,
} from "@/lib/api";

export type CandidateDecision = "confirmed" | "modified" | "rejected";

export type BatchApproveActionResult =
  | { ok: true; count: number }
  | { ok: false; status: number | "unconfigured" | "unknown" };

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

export type DecideActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "unknown" };

export async function decideCandidateAction(
  candidateId: string,
  decision: CandidateDecision,
  payload?: unknown,
  reason?: string,
): Promise<DecideActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = candidateId.trim();
  if (!id) return { ok: false, status: 404, detail: null };
  const note = (reason ?? "").trim();
  try {
    await decideCandidate(id, {
      decision,
      payload: decision === "modified" ? payload : undefined,
      reason: note.length > 0 ? note : null,
    });
    return { ok: true };
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

export async function batchApproveAction(
  candidateIds: string[],
  reason: string,
): Promise<BatchApproveActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const ids = candidateIds.map((id) => id.trim()).filter(Boolean);
  if (ids.length === 0) return { ok: false, status: 422 };
  const note = reason.trim();
  try {
    const result = await batchApprove(ids, note.length > 0 ? note : null);
    return { ok: true, count: result.count };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return { ok: false, status: err.status };
    }
    return { ok: false, status: "unknown" };
  }
}

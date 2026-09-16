"use server";

import { ApiError, batchApprove, CURRENT_ADMIN_ACTOR_ID } from "@/lib/api";

export type BatchApproveActionResult =
  | { ok: true; count: number }
  | { ok: false; status: number | "unconfigured" | "unknown" };

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

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

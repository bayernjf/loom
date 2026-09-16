"use server";

import {
  ADMIN_ROLE_LIST,
  adminTransitionIntake,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
} from "@/lib/api";
import { isOpsIntakeEvent } from "./ops-intake-codes";

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

export type OpsIntakeActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

export async function opsTransitionIntakeAction(
  intakeId: string,
  event: string,
): Promise<OpsIntakeActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = intakeId.trim();
  if (!id || !isOpsIntakeEvent(event)) return { ok: false, status: 422, detail: null };
  // 状态机对全部 ops 白名单事件硬要求 operations 角色；角色不符不发请求。
  if (!ADMIN_ROLE_LIST.includes("operations")) {
    return { ok: false, status: "missing_role" };
  }
  try {
    await adminTransitionIntake(id, event);
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

"use server";

// Q364（Q56 配置功能页）：运行配置写口 Server Action。当前仅 content.regen_limit
// 一项（重生成上限，Q56 要求有配置页面）。配置中心读写均仅 platform_admin
// （Q113，未随 Q345 放宽 operations），本地缺身份/缺角色零请求，同 Q167。
// client 岛只允许调用本模块，禁直连 lib/api。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  updateConfigItem,
} from "@/lib/api";

const REGEN_LIMIT_KEY = "content.regen_limit";
const KNOWN_STATUSES = new Set([403, 404, 422]);

export type ConfigActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    return typeof parsed.detail === "string" && parsed.detail
      ? parsed.detail
      : null;
  } catch {
    return null;
  }
}

function failure(err: unknown): ConfigActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 403 | 404 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

function guardPlatformAdmin(): ConfigActionResult | null {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.some((role) => role === "platform_admin"))
    return { ok: false, status: "missing_role" };
  return null;
}

export async function updateRegenLimitAction(input: {
  limit: number;
  changeNote: string;
}): Promise<ConfigActionResult> {
  const blocked = guardPlatformAdmin();
  if (blocked) return blocked;
  // 与种子 validation {"min": 1} 同口径，本地先挡一次；非整数亦拒（int 键）。
  if (!Number.isInteger(input.limit) || input.limit < 1)
    return { ok: false, status: 422, detail: null };
  try {
    await updateConfigItem(
      REGEN_LIMIT_KEY,
      input.limit,
      input.changeNote || undefined,
    );
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

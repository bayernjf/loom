"use server";

// Q167：入站 Agent Key 治理 Server Action——签发（secret 仅一次返回）与吊销。
// 后端 Q88 在 service 层硬闸 platform_admin；本地缺身份/缺角色零请求，同 Q105。
// client 岛只允许调用本模块，禁直连 lib/api。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  issueAgentKey,
  revokeAgentKey,
} from "@/lib/api";
import type { AgentKeyView } from "@/lib/api";
export type { AgentKeyView };

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export type AgentKeyActionResult =
  | { ok: true; secret?: string }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
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

function failure(err: unknown): AgentKeyActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 403 | 404 | 409 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

function guardPlatform(): AgentKeyActionResult | null {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.includes("platform_admin"))
    return { ok: false, status: "missing_role" };
  return null;
}

export async function issueAgentKeyAction(
  name: string,
): Promise<AgentKeyActionResult> {
  const blocked = guardPlatform();
  if (blocked) return blocked;
  const trimmed = name.trim();
  if (!trimmed) return { ok: false, status: 422, detail: null };
  try {
    const issued = await issueAgentKey(trimmed);
    return { ok: true, secret: issued.secret };
  } catch (err) {
    return failure(err);
  }
}

export async function revokeAgentKeyAction(
  keyId: string,
): Promise<AgentKeyActionResult> {
  const blocked = guardPlatform();
  if (blocked) return blocked;
  const trimmed = keyId.trim();
  if (!trimmed) return { ok: false, status: 422, detail: null };
  try {
    await revokeAgentKey(trimmed);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

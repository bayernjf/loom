"use server";

// Q359：灵感库写口 Server Action——新建/编辑（含启停）/删除，三写均落审计（Q358）。
// 后端在 service 层硬闸 operations/platform_admin；本地缺身份/缺角色零请求，同 Q167。
// client 岛只允许调用本模块，禁直连 lib/api。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  createInspirationEntry,
  deleteInspirationEntry,
  updateInspirationEntry,
} from "@/lib/api";
export type { InspirationEntryView } from "@/lib/api";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);
const LAYERS = new Set(["common", "product"]);

export type InspirationActionResult =
  | { ok: true }
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

function failure(err: unknown): InspirationActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 403 | 404 | 409 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

function guardOps(): InspirationActionResult | null {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (
    !ADMIN_ROLE_LIST.some(
      (role) => role === "operations" || role === "platform_admin",
    )
  )
    return { ok: false, status: "missing_role" };
  return null;
}

export async function createInspirationEntryAction(input: {
  tenantId: string;
  layer: string;
  productSpaceId?: string;
  content: string;
  tags: string[];
  enabled: boolean;
}): Promise<InspirationActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const tenantId = input.tenantId.trim();
  const content = input.content.trim();
  const productSpaceId = input.productSpaceId?.trim() ?? "";
  if (!tenantId || !content || !LAYERS.has(input.layer))
    return { ok: false, status: 422, detail: null };
  if (input.layer === "product" && !productSpaceId)
    return { ok: false, status: 422, detail: null };
  try {
    await createInspirationEntry({
      tenantId,
      layer: input.layer,
      productSpaceId: productSpaceId || null,
      content,
      tags: input.tags,
      enabled: input.enabled,
    });
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

export async function updateInspirationEntryAction(
  entryId: string,
  input: { content: string; tags: string[]; enabled: boolean },
): Promise<InspirationActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = entryId.trim();
  const content = input.content.trim();
  if (!trimmedId || !content) return { ok: false, status: 422, detail: null };
  try {
    await updateInspirationEntry(trimmedId, {
      content,
      tags: input.tags,
      enabled: input.enabled,
    });
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

export async function deleteInspirationEntryAction(
  entryId: string,
): Promise<InspirationActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = entryId.trim();
  if (!trimmedId) return { ok: false, status: 422, detail: null };
  try {
    await deleteInspirationEntry(trimmedId);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

"use server";

import {
  ApiError,
  changeTenantPlan,
  CURRENT_ADMIN_ACTOR_ID,
  pauseTenant,
  provisionTenant,
  resumeTenant,
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

export type TenantActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "unknown" };

export async function provisionTenantAction(
  tenantId: string,
  name: string,
  plan: string,
): Promise<TenantActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = tenantId.trim();
  if (!id) return { ok: false, status: 422, detail: null };
  const trimmedName = name.trim();
  try {
    await provisionTenant({
      tenantId: id,
      name: trimmedName ? trimmedName : null,
      plan,
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

export async function changePlanAction(
  tenantId: string,
  plan: string,
): Promise<TenantActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = tenantId.trim();
  if (!id) return { ok: false, status: 404, detail: null };
  try {
    await changeTenantPlan(id, plan);
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

export async function pauseTenantAction(
  tenantId: string,
): Promise<TenantActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = tenantId.trim();
  if (!id) return { ok: false, status: 404, detail: null };
  try {
    await pauseTenant(id);
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

export async function resumeTenantAction(
  tenantId: string,
): Promise<TenantActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = tenantId.trim();
  if (!id) return { ok: false, status: 404, detail: null };
  try {
    await resumeTenant(id);
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

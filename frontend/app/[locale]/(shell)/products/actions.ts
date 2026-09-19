"use server";

import {
  ApiError,
  CURRENT_ACTOR_ID,
  CURRENT_TENANT_ID,
  PRODUCT_NAME_PROFILE_KEY,
  createIntake,
  patchIntakeProfile,
  setIntakeTargetLanguages,
  transitionIntake,
} from "@/lib/api";
import { isCustomerIntakeEvent } from "./intake-codes";

export type CreateProductResult =
  | { ok: true; id: string }
  | { ok: false; status: number };

export async function createProductAction(formData: FormData): Promise<CreateProductResult> {
  const name = String(formData.get("productName") ?? "").trim();
  if (!name || name.length > 100 || !CURRENT_TENANT_ID) return { ok: false, status: 422 };

  try {
    const intake = await createIntake(CURRENT_TENANT_ID, {
      [PRODUCT_NAME_PROFILE_KEY]: name,
    });
    return { ok: true, id: intake.intake_id };
  } catch (err) {
    return { ok: false, status: err instanceof ApiError ? err.status : 0 };
  }
}

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

// transitions 的 422 体为 {"detail":{"missing_fids":[...]}}（FastAPI 的 detail 包装，
// 区别于字符串 detail）；lib/api 把 body JSON.stringify 进 Error.message，这里解析取回 fid 原样码。
function missingFids(message: string): string[] | null {
  try {
    const body = JSON.parse(message) as unknown;
    const detail = (body as { detail?: unknown })?.detail;
    if (
      detail &&
      typeof detail === "object" &&
      Array.isArray((detail as { missing_fids?: unknown }).missing_fids)
    ) {
      return ((detail as { missing_fids: unknown[] }).missing_fids).map(String);
    }
  } catch {
    // 非 JSON body（如纯字符串 detail），按普通 422 处理。
  }
  return null;
}

export type IntakeActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; missingFids: string[] | null }
  | { ok: false; status: "unconfigured" | "unknown" };

export async function transitionIntakeAction(
  intakeId: string,
  event: string,
): Promise<IntakeActionResult> {
  if (!CURRENT_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!intakeId.trim() || !isCustomerIntakeEvent(event))
    return { ok: false, status: 422, missingFids: null };

  try {
    await transitionIntake(intakeId, event);
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError) {
      if (KNOWN_STATUSES.has(err.status))
        return {
          ok: false,
          status: err.status as 403 | 404 | 409 | 422,
          missingFids: err.status === 422 ? missingFids(err.message) : null,
        };
    }
    return { ok: false, status: "unknown" };
  }
}

export async function updateDraftProfileAction(
  intakeId: string,
  name: string,
): Promise<IntakeActionResult> {
  if (!CURRENT_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const trimmed = name.trim();
  if (!intakeId.trim() || !trimmed || trimmed.length > 100)
    return { ok: false, status: 422, missingFids: null };

  try {
    await patchIntakeProfile(intakeId, { [PRODUCT_NAME_PROFILE_KEY]: trimmed });
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status))
      return {
        ok: false,
        status: err.status as 403 | 404 | 409 | 422,
        missingFids: null,
      };
    return { ok: false, status: "unknown" };
  }
}

// B3/Q122：客户在段1 录入详情页保存产品目标语言（空数组 = 未声明）。
export async function setTargetLanguagesAction(
  intakeId: string,
  languages: string[],
): Promise<IntakeActionResult> {
  if (!CURRENT_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!intakeId.trim() || languages.some((code) => !code.trim()))
    return { ok: false, status: 422, missingFids: null };

  try {
    await setIntakeTargetLanguages(intakeId, languages);
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status))
      return {
        ok: false,
        status: err.status as 403 | 404 | 409 | 422,
        missingFids: null,
      };
    return { ok: false, status: "unknown" };
  }
}

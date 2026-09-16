"use server";

import {
  ApiError,
  CURRENT_TENANT_ID,
  PRODUCT_NAME_PROFILE_KEY,
  createIntake,
} from "@/lib/api";

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

"use server";

// Q249 / D3.5 §3.1 甲：组装工作台——表单数据源 + 预检只读口 + 手动单条发证。
// 预检（previewAssemble）与签发（assembleManual）都经 lib/api 走 httpOnly staff
// Bearer；client 岛只允许调本模块，禁直连 lib/api（check-admin 守卫）。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  assembleManual,
  getAdminContentGoals,
  getAdminFcwMaterial,
  getAdminPublishSlots,
  previewAssemble,
  suggestAiSelect,
  type AdminContentGoal,
  type AdminPublishSlot,
  type AiSelectSuggestBody,
  type AiSelectSuggestView,
  type AssembleManualBody,
  type AssemblePreview,
  type FcwCardView,
  type Wf07Scene,
} from "@/lib/api";
import { mapConflictChecks, type ConflictCheckRow } from "@/lib/fcw-conflict-map";

export type {
  AdminContentGoal,
  AdminPublishSlot,
  AssembleManualBody,
  AssemblePreview,
  FcwCardView,
  ConflictCheckRow,
  Wf07Scene,
};

const KNOWN_STATUSES = new Set([401, 403, 404, 409, 422]);

export type FormDataResult =
  | { ok: true; slots: AdminPublishSlot[]; goals: AdminContentGoal[] }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

export async function getAssembleFormDataAction(): Promise<FormDataResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations" || r === "platform_admin"))
    return { ok: false, status: "missing_role" };
  try {
    const [slots, goals] = await Promise.all([
      getAdminPublishSlots(),
      getAdminContentGoals(),
    ]);
    return { ok: true, slots, goals };
  } catch (err) {
    return { ok: false, status: "unknown" };
  }
}

function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object") return JSON.stringify(detail);
    return null;
  } catch {
    return null;
  }
}

export type PreviewResult =
  | { ok: true; preview: AssemblePreview; conflicts: ConflictCheckRow[] }
  | {
      ok: false;
      status: 401 | 403 | 404 | 409 | 422 | "unconfigured" | "missing_role" | "unknown";
      detail: string | null;
    };

export async function previewAssembleAction(
  body: AssembleManualBody,
): Promise<PreviewResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured", detail: null };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations" || r === "platform_admin"))
    return { ok: false, status: "missing_role", detail: null };
  try {
    const preview = await previewAssemble(body);
    return {
      ok: true,
      preview,
      conflicts: mapConflictChecks({
        guards: preview.guards,
        scoreIncomplete: preview.score_incomplete,
      }),
    };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return {
        ok: false,
        status: err.status as 401 | 403 | 404 | 409 | 422,
        detail: errorDetail(err.message),
      };
    }
    return { ok: false, status: "unknown", detail: null };
  }
}

export type AssembleResult =
  | { ok: true; fcw: FcwCardView }
  | {
      ok: false;
      status: 401 | 403 | 404 | 409 | 422 | "unconfigured" | "missing_role" | "unknown";
      detail: string | null;
    };

export async function assembleManualAction(
  body: AssembleManualBody,
): Promise<AssembleResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured", detail: null };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations" || r === "platform_admin"))
    return { ok: false, status: "missing_role", detail: null };
  try {
    const fcw = await assembleManual(body);
    return { ok: true, fcw };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return {
        ok: false,
        status: err.status as 401 | 403 | 404 | 409 | 422,
        detail: errorDetail(err.message),
      };
    }
    return { ok: false, status: "unknown", detail: null };
  }
}

export type ReuseResult =
  | {
      ok: true;
      product_space_id: string;
      platform: string;
      slot_id: string;
      goal: string;
      country: string | null;
    }
  | {
      ok: false;
      status: 401 | 403 | 404 | 409 | 422 | "unconfigured" | "missing_role" | "unknown";
      detail: string | null;
    };

export async function getFcwReuseAction(
  finalId: string,
): Promise<ReuseResult> {
  // Q251 裁决 c：复用＝已签发成品再发证。取 Q177 管理端六层原料包（issued 段含
  // 组装入参：product_space_id/platform/slot_id/goal/country）→ 预填组装表单，
  // 走 E1.1 重新预检/签发；与第 4 项候选池复制（segment-4）划清。
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured", detail: null };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations" || r === "platform_admin"))
    return { ok: false, status: "missing_role", detail: null };
  try {
    const pack = await getAdminFcwMaterial(finalId);
    const issued = pack.issued as {
      product_space_id?: string;
      platform?: string;
      slot_id?: string;
      goal?: string;
      country?: string | null;
    };
    if (!issued.product_space_id || !issued.platform || !issued.slot_id || !issued.goal) {
      return { ok: false, status: "unknown", detail: null };
    }
    return {
      ok: true,
      product_space_id: issued.product_space_id,
      platform: issued.platform,
      slot_id: issued.slot_id,
      goal: issued.goal,
      country: issued.country ?? null,
    };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return {
        ok: false,
        status: err.status as 401 | 403 | 404 | 409 | 422,
        detail: errorDetail(err.message),
      };
    }
    return { ok: false, status: "unknown", detail: null };
  }
}

// Q328（WF-07 操作面 D3 甲）：组装工作台「AI 选包建议」触发。
// AI 只产候选（pending_review＋SLA 待办），operations 在统一审核工作台裁决；
// 采用后的预填在包管理页走既有包 create/update 审批（D5 甲，本 V1 不预填包表单）。
export type AiSelectResult =
  | { ok: true; suggest: AiSelectSuggestView }
  | {
      ok: false;
      status: 401 | 403 | 404 | 409 | 422 | "unconfigured" | "missing_role" | "unknown";
      detail: string | null;
    };

export async function suggestAiSelectAction(
  body: AiSelectSuggestBody,
): Promise<AiSelectResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured", detail: null };
  if (!ADMIN_ROLE_LIST.some((r) => r === "operations" || r === "platform_admin"))
    return { ok: false, status: "missing_role", detail: null };
  try {
    const suggest = await suggestAiSelect(body);
    return { ok: true, suggest };
  } catch (err) {
    if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
      return {
        ok: false,
        status: err.status as 401 | 403 | 404 | 409 | 422,
        detail: errorDetail(err.message),
      };
    }
    return { ok: false, status: "unknown", detail: null };
  }
}

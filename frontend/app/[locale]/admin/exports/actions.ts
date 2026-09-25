"use server";

// Q168：中台导出任务管理 Server Action——创建导出任务（门控关同步 completed、
// 门控开 queued 由 worker 消费）与下载成品（csv/json 文本，经 action 回传 client 落盘）。
// 中台面无 RBAC 闸（同 Q100/Q132），actor 仅留痕；client 岛只调本模块，禁直连 lib/api。
import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  createExportJob,
  downloadExportJob,
} from "@/lib/api";
import type { ExportJobView } from "@/lib/api";
export type { ExportJobView };

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export type ExportActionResult =
  | { ok: true }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "unknown" };

export type ExportDownloadResult =
  | { ok: true; content: string; fileName: string; mediaType: string }
  | { ok: false; status: 403 | 404 | 409 | 422; detail: string | null }
  | { ok: false; status: "unconfigured" | "unknown" };

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

function failure(err: unknown): ExportActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 403 | 404 | 409 | 422,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

export async function createExportJobAction(
  tenantId: string,
  productSpaceId: string,
  format: string,
): Promise<ExportActionResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const tenant = tenantId.trim();
  if (!tenant) return { ok: false, status: 422, detail: null };
  if (format !== "csv" && format !== "json")
    return { ok: false, status: 422, detail: null };
  const productSpace = productSpaceId.trim();
  try {
    await createExportJob({
      tenantId: tenant,
      productSpaceId: productSpace || undefined,
      format,
    });
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

export async function downloadExportJobAction(
  jobId: string,
  tenantId: string,
): Promise<ExportDownloadResult> {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  const id = jobId.trim();
  if (!id) return { ok: false, status: 422, detail: null };
  const tenant = tenantId.trim();
  if (!tenant) return { ok: false, status: 422, detail: null };
  try {
    const downloaded = await downloadExportJob(id, tenant);
    return { ok: true, ...downloaded };
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

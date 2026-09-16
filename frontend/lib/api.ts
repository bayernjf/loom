// Q98：产品中心对后端的唯一访问层。仅允许在服务端模块/RSC/Server Action 中引用——
// LOOM_API_BASE_URL / LOOM_TENANT_ID 不带 NEXT_PUBLIC 前缀，不会进入浏览器包；
// 浏览器经 RSC 与 Server Action 间接访问，规避后端无 CORS 的现状（V2 真实认证后改为会话派生租户）。

// 工程临时键：产品名在 profile 中的 fid 基线未回填（g2_fields cat='common' 为空表，
// docs/04:58 仅有中文名枚举，溯 line 682-698），基线落地后须对齐替换，挂账 Q98。
export const PRODUCT_NAME_PROFILE_KEY = "product_name";

export interface IntakeView {
  intake_id: string;
  tenant_id: string;
  status: string;
  profile: Record<string, string>;
  category_pending_id: string | null;
}

export interface IntakeList {
  items: IntakeView[];
  total: number;
  limit: number;
  offset: number;
}

export interface IntakeOverview {
  total: number;
  by_status: Record<string, number>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const API_BASE = (process.env.LOOM_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export const CURRENT_TENANT_ID = process.env.LOOM_TENANT_ID ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new ApiError(res.status, detail || res.statusText);
  }
  return (await res.json()) as T;
}

export async function listIntakes(
  tenantId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<IntakeList> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  return request<IntakeList>(`/api/intakes?${params}`);
}

export async function createIntake(
  tenantId: string,
  profile: Record<string, string>,
): Promise<IntakeView> {
  return request<IntakeView>("/api/intakes", {
    method: "POST",
    body: JSON.stringify({ tenant_id: tenantId, profile }),
  });
}

export async function getIntake(intakeId: string): Promise<IntakeView> {
  return request<IntakeView>(`/api/intakes/${encodeURIComponent(intakeId)}`);
}

export async function getIntakeOverview(tenantId: string): Promise<IntakeOverview> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  return request<IntakeOverview>(`/api/intakes/overview?${params}`);
}

export function intakeDisplayName(intake: IntakeView): string {
  return intake.profile[PRODUCT_NAME_PROFILE_KEY]?.trim() || intake.intake_id.slice(0, 8);
}

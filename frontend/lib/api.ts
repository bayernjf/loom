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

export interface CcrBanHit {
  word: string;
  level: string;
  layer: string;
  country: string | null;
  entry_id: string;
}

export interface CcrDowngradeHit extends CcrBanHit {
  downgrade_target: string;
}

export interface CcrMarket {
  country: string | null;
  status: string;
  block_required: boolean;
  created_at: string | null;
  bans: CcrBanHit[];
  downgrades: CcrDowngradeHit[];
}

export interface CcrOverview {
  worst_status: string;
  block_required: boolean;
  latest_at: string | null;
  markets: CcrMarket[];
}

export interface LawReviewView {
  status: string;
  domain: string;
  conclusion: string | null;
  decided_at: string | null;
}

export interface ComplianceOverviewItem {
  pws_id: string;
  product_space_id: string;
  intake_id: string | null;
  product_name: string | null;
  version: string;
  ccr: CcrOverview | null;
  law_review: LawReviewView | null;
}

export interface ComplianceOverview {
  items: ComplianceOverviewItem[];
}

export async function getComplianceOverview(tenantId: string): Promise<ComplianceOverview> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  return request<ComplianceOverview>(`/api/compliance/overview?${params}`);
}

// Q102：管理端（Q92 驾驶舱）管理员身份。V1 actor 自报（同写端点口径），
// 真认证随 V2 改会话派生；不进浏览器包，shell 客户侧不持有该身份。
export const CURRENT_ADMIN_ACTOR_ID = process.env.LOOM_ADMIN_ACTOR_ID ?? "";
const ADMIN_ROLES = (process.env.LOOM_ADMIN_ROLES ?? "platform_admin")
  .split(",")
  .map((role) => role.trim())
  .filter(Boolean);

export interface TokenCostDailyRow {
  date: string;
  model_id: string;
  currency_code: string | null;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  input_cost: number;
  output_cost: number;
  total_cost: number;
}

export interface TokenCostSkillRow {
  skill_id: string;
  currency_code: string | null;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
}

export interface FailedSkillRow {
  skill_id: string;
  failed_runs: number;
}

export interface TokenCostDashboard {
  window: { from: string; to: string };
  daily: TokenCostDailyRow[];
  by_skill: TokenCostSkillRow[];
  failed_by_skill: FailedSkillRow[];
  totals: {
    runs: number;
    input_tokens: number;
    output_tokens: number;
    failed_runs: number;
  };
}

export interface CandidateBacklogRow {
  target_type: string;
  pending: number;
  oldest_wait_seconds: number | null;
}

export interface TodoBacklogRow {
  todo_type: string;
  open: number;
  overdue: number;
  escalated: number;
}

export interface DecidedCountRow {
  state: string;
  count: number;
}

export interface ResolvedCountRow {
  todo_type: string;
  count: number;
}

export interface ReviewWorkloadDashboard {
  window: { from: string; to: string };
  snapshot_at: string;
  backlog: {
    candidates: CandidateBacklogRow[];
    todos: TodoBacklogRow[];
    totals: {
      pending_candidates: number;
      open_todos: number;
      overdue_todos: number;
      escalated_todos: number;
    };
  };
  window_output: {
    candidates_decided: DecidedCountRow[];
    todos_resolved: ResolvedCountRow[];
  };
}

function adminPath(path: string): string {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLES) params.append("roles", role);
  return `${path}?${params}`;
}

export async function getTokenCostDashboard(): Promise<TokenCostDashboard> {
  return request<TokenCostDashboard>(adminPath("/api/admin/dashboards/token-cost"));
}

export async function getReviewWorkloadDashboard(): Promise<ReviewWorkloadDashboard> {
  return request<ReviewWorkloadDashboard>(adminPath("/api/admin/dashboards/review-workload"));
}

// Q103：统一审核工作台（Q93 后端）。可见角色 = 注册表 WF skill7 Gate 角色并集
// （operations+product_reviewer）；本切片仅队列消费 + 批量通过，逐条
// confirmed/modified/rejected 裁决留下一切片。
export interface ReviewQueueCandidate {
  candidate_id: string;
  run_id: string;
  candidate_index: number;
  skill_id: string;
  wf_id: string;
  tenant_id: string | null;
  product_space_id: string | null;
  intake_id: string | null;
  target_type: string;
  payload: unknown;
  state: string;
  human_modified: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
  wait_seconds: number | null;
  confidence: number | null;
  risk_level: string;
  risk_rank: number;
  risk_reason: string;
  batch_eligible: boolean;
}

export interface ReviewQueue {
  total: number;
  limit: number;
  offset: number;
  batch_pass_confidence: number;
  candidates: ReviewQueueCandidate[];
}

export interface ReviewQueueQuery {
  state?: string;
  targetTypes?: string[];
  wfId?: string;
  riskLevel?: string;
  limit?: number;
  offset?: number;
}

export async function getReviewQueue(query: ReviewQueueQuery = {}): Promise<ReviewQueue> {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLES) params.append("roles", role);
  if (query.state) params.set("state", query.state);
  for (const type of query.targetTypes ?? []) params.append("target_type", type);
  if (query.wfId) params.set("wf_id", query.wfId);
  if (query.riskLevel) params.set("risk_level", query.riskLevel);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  return request<ReviewQueue>(`/api/review-workbench/candidates?${params}`);
}

export interface BatchApproveResult {
  approved: Array<{ candidate_id: string }>;
  count: number;
}

export async function batchApprove(
  candidateIds: string[],
  reason: string | null,
): Promise<BatchApproveResult> {
  return request<BatchApproveResult>("/api/review-workbench/batch-approve", {
    method: "POST",
    body: JSON.stringify({
      candidate_ids: candidateIds,
      reason,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLES },
    }),
  });
}

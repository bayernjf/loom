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

// Q106：V1 无真实认证，客户侧写操作（PATCH profile / transitions）的操作人由 server env 自报，
// roles 恒空——客户事件在状态机中 requires_role 均为 None；运营事件不在客户页外放。V2 改会话派生。
export const CURRENT_ACTOR_ID = process.env.LOOM_ACTOR_ID ?? "";

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

// Q106：录入单 15 态操作（客户页消费既有段1 端点，无新写口）。
export interface AllowedEvents {
  status: string;
  allowed_events: string[];
}

export interface ProductSpaceView {
  product_space_id: string;
  tenant_id: string;
  intake_id: string;
  lifecycle: string;
  profile_snapshot: Record<string, string>;
  // B3/Q122：产品目标语言（null = 未声明、不收窄语言交集）。
  target_languages: string[] | null;
}

export async function getAllowedEvents(intakeId: string): Promise<AllowedEvents> {
  return request<AllowedEvents>(
    `/api/intakes/${encodeURIComponent(intakeId)}/allowed-events`,
  );
}

export async function transitionIntake(
  intakeId: string,
  event: string,
  categoryPendingId?: string | null,
): Promise<IntakeView> {
  return request<IntakeView>(`/api/intakes/${encodeURIComponent(intakeId)}/transitions`, {
    method: "POST",
    body: JSON.stringify({
      event,
      category_pending_id: categoryPendingId ?? null,
      actor: { id: CURRENT_ACTOR_ID, roles: [] },
    }),
  });
}

export async function patchIntakeProfile(
  intakeId: string,
  profile: Record<string, string>,
): Promise<IntakeView> {
  return request<IntakeView>(`/api/intakes/${encodeURIComponent(intakeId)}/profile`, {
    method: "PATCH",
    body: JSON.stringify({ profile, actor: { id: CURRENT_ACTOR_ID, roles: [] } }),
  });
}

export async function getProductSpace(intakeId: string): Promise<ProductSpaceView | null> {
  try {
    return await request<ProductSpaceView>(
      `/api/intakes/${encodeURIComponent(intakeId)}/product-space`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

// B3/Q122：客户在段1 录入页设置产品目标语言（客户口径，无运营闸；空数组 = 未声明）。
export async function setIntakeTargetLanguages(
  intakeId: string,
  languages: string[],
): Promise<ProductSpaceView> {
  return request<ProductSpaceView>(
    `/api/intakes/${encodeURIComponent(intakeId)}/target-languages`,
    {
      method: "PATCH",
      body: JSON.stringify({
        languages,
        actor: { id: CURRENT_ACTOR_ID, roles: [] },
      }),
    },
  );
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

// Q162①：CCR 分市场清洗报告历史只读列表（分页甲案；区别于 overview 只取每市场最新）。
export interface CcrHistoryItem {
  ccr_id: string;
  pws_id: string;
  product_space_id: string;
  country: string | null;
  status: string;
  block_required: boolean;
  created_at: string | null;
}

export interface CcrHistoryPage {
  items: CcrHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export async function getCcrHistory(
  tenantId: string,
  opts: { pwsId?: string; country?: string; limit?: number; offset?: number } = {},
): Promise<CcrHistoryPage> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  if (opts.pwsId) params.set("pws_id", opts.pwsId);
  if (opts.country) params.set("country", opts.country);
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  return request<CcrHistoryPage>(`/api/compliance/ccr-history?${params}`);
}

// Q162①：单条 CCR 报告详情（含 hits 完整 JSON）。
export interface CcrDetail extends CcrHistoryItem {
  hits: { bans: CcrBanHit[]; downgrades: CcrDowngradeHit[] };
  wordlist_context: Record<string, unknown>;
  decided_by: string | null;
  decided_at: string | null;
}

export async function getCcrDetail(
  ccrId: string,
  tenantId: string,
): Promise<CcrDetail> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  return request<CcrDetail>(
    `/api/compliance/ccr/${encodeURIComponent(ccrId)}?${params}`,
  );
}

// Q162②：法审记录只读 + 服务端派生 SLA 倒计时（normal/overdue/resolved）。
export interface LawReviewSlaItem {
  law_review_id: string;
  pws_id: string;
  product_space_id: string;
  domain: string;
  status: string;
  conclusion: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string | null;
  sla_remaining_seconds: number | null;
  sla_state: "normal" | "overdue" | "resolved";
}

export async function getTenantLawReviews(
  tenantId: string,
): Promise<LawReviewSlaItem[]> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  return request<LawReviewSlaItem[]>(`/api/compliance/law-reviews?${params}`);
}

// Q162③：客户侧只读合规词库（仅 active；写口归 internal_compliance 管理端）。
export interface WordlistEntryView {
  word: string;
  level: string;
  action: string;
  country: string | null;
  layer: string;
  effective_from: string | null;
  effective_until: string | null;
}

export async function getComplianceWordlist(
  opts: { level?: string; layer?: string } = {},
): Promise<WordlistEntryView[]> {
  const params = new URLSearchParams();
  if (opts.level) params.set("level", opts.level);
  if (opts.layer) params.set("layer", opts.layer);
  const qs = params.toString();
  return request<WordlistEntryView[]>(
    `/api/compliance/wordlist${qs ? `?${qs}` : ""}`,
  );
}

// Q114：settings 只读账户面板——客户侧租户读口（无 admin 闸，复用 Q95 租户注册表）。
// Q163：追加派生 onboarding 进度（接缝甲案，待负责人追认；复用既有 TenantOnboarding）。
export interface CustomerTenantView {
  tenant_id: string;
  name: string | null;
  plan: string;
  status: string;
  monthly_token_quota: number | null;
  onboarding: TenantOnboarding;
}

export async function getCurrentTenant(tenantId: string): Promise<CustomerTenantView> {
  return request<CustomerTenantView>(`/api/tenants/${encodeURIComponent(tenantId)}`);
}

// Q122：客户「内容生产与发布」页（段12 成品只读 + 客户审阅 Q59 + Q56-a 人工编辑）。
// 生成 / 重生成仍为 operations 端点（Q116 定稿），客户页不调用；列表项不带 body。
export interface ContentSemanticFinding {
  code: string;
  message?: string | null;
  excerpt?: string | null;
}

export interface ContentSemanticResult {
  checked: boolean;
  findings: ContentSemanticFinding[];
  error?: string | null;
}

export interface ContentReviewHits {
  bans: CcrBanHit[];
  downgrades: CcrDowngradeHit[];
  block_required: boolean;
  semantic?: ContentSemanticResult;
}

export interface ContentQualityIssue {
  code?: string;
  message?: string;
  [key: string]: unknown;
}

export interface ContentProductListItem {
  content_id: string;
  tenant_id: string;
  product_space_id: string;
  final_id: string;
  goal: string;
  platform: string;
  slot_id: string | null;
  country: string | null;
  kind: string;
  language: string;
  review_hits: ContentReviewHits;
  status: string;
  reject_reason: string | null;
  regenerate_count: number;
  created_at: string | null;
  // Q124/Q56-b：运营作废回池的难产原因（仅 discarded 态非空）。
  discard_reason: string | null;
  // Q125/Q60c：运营发布回填（published_at 非空即已发布）。
  published_url: string | null;
  platform_post_id: string | null;
  published_at: string | null;
  quality_score: number | null;
  quality_issues: ContentQualityIssue[] | null;
  quality_threshold: number | null;
  quality_advisory: boolean | null;
}

export interface ContentProductView extends ContentProductListItem {
  body: string | null;
}

// B3/Q122：目标语言控件的只读 active 语言清单（无闸；归档语言不返）。
export interface ContentLanguageView {
  code: string;
  name: string;
  markets: string[];
  status: string;
}

export async function getContentLanguages(): Promise<ContentLanguageView[]> {
  return request<ContentLanguageView[]>("/api/content/languages");
}

export async function listContent(tenantId: string): Promise<ContentProductListItem[]> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  return request<ContentProductListItem[]>(`/api/content?${params}`);
}

export async function getContent(contentId: string): Promise<ContentProductView> {
  return request<ContentProductView>(
    `/api/content/${encodeURIComponent(contentId)}`,
  );
}

function contentPost(
  path: string,
  payload: Record<string, unknown>,
): Promise<ContentProductView> {
  return request<ContentProductView>(path, {
    method: "POST",
    body: JSON.stringify({
      actor: { id: CURRENT_ACTOR_ID, roles: [] },
      ...payload,
    }),
  });
}

export function approveContent(contentId: string): Promise<ContentProductView> {
  return contentPost(`/api/content/${encodeURIComponent(contentId)}/approve`, {});
}

export function rejectContent(
  contentId: string,
  reason: string,
): Promise<ContentProductView> {
  return contentPost(`/api/content/${encodeURIComponent(contentId)}/reject`, { reason });
}

export function reviseContent(contentId: string): Promise<ContentProductView> {
  return contentPost(`/api/content/${encodeURIComponent(contentId)}/revise`, {});
}

export async function editContentBody(
  contentId: string,
  body: string,
): Promise<ContentProductView> {
  return request<ContentProductView>(
    `/api/content/${encodeURIComponent(contentId)}/body`,
    {
      method: "PATCH",
      body: JSON.stringify({ body, actor: { id: CURRENT_ACTOR_ID, roles: [] } }),
    },
  );
}

// Q102：管理端（Q92 驾驶舱）管理员身份。V1 actor 自报（同写端点口径），
// 真认证随 V2 改会话派生；不进浏览器包，shell 客户侧不持有该身份。
export const CURRENT_ADMIN_ACTOR_ID = process.env.LOOM_ADMIN_ACTOR_ID ?? "";
export const ADMIN_ROLE_LIST = (process.env.LOOM_ADMIN_ROLES ?? "platform_admin")
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
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
  return `${path}?${params}`;
}

export interface DashboardWindowOpts {
  /** ISO date (YYYY-MM-DD)，半开区间左端；缺省由后端取近 30 天。 */
  dateFrom?: string;
  /** ISO date (YYYY-MM-DD)，半开区间右端 [from, to)；缺省由后端取今天。 */
  dateTo?: string;
}

function appendWindow(params: URLSearchParams, opts?: DashboardWindowOpts): void {
  if (!opts) return;
  if (opts.dateFrom) params.append("date_from", opts.dateFrom);
  if (opts.dateTo) params.append("date_to", opts.dateTo);
}

export async function getTokenCostDashboard(
  opts?: DashboardWindowOpts,
): Promise<TokenCostDashboard> {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
  appendWindow(params, opts);
  return request<TokenCostDashboard>(`/api/admin/dashboards/token-cost?${params}`);
}

export async function getReviewWorkloadDashboard(
  opts?: DashboardWindowOpts,
): Promise<ReviewWorkloadDashboard> {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
  appendWindow(params, opts);
  return request<ReviewWorkloadDashboard>(
    `/api/admin/dashboards/review-workload?${params}`,
  );
}

// Q103：统一审核工作台（Q93 后端）。可见角色 = 注册表 WF skill7 Gate 角色并集
// （operations+product_reviewer）；Q104 起逐条裁决复用既有
// POST /api/skill-candidates/{id}/decision（confirmed/modified/rejected，
// modified 携带替换 payload），工作台不另设写口。
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
  review_note: string | null;
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
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
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
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

export type CandidateDecision = "confirmed" | "modified" | "rejected";

export interface CandidateDecisionBody {
  decision: CandidateDecision;
  payload?: unknown;
  reason?: string | null;
}

// Q104：逐条裁决。后端按该候选所属 WF 的 review_role 校角色，modified 必给
// 替换 payload（先结构校验再过适配器业务规则），403/404/409/422 齐。
export async function decideCandidate(
  candidateId: string,
  body: CandidateDecisionBody,
): Promise<{ candidate_id: string; state: string }> {
  return request<{ candidate_id: string; state: string }>(
    `/api/skill-candidates/${candidateId}/decision`,
    {
      method: "POST",
      body: JSON.stringify({
        decision: body.decision,
        payload: body.payload ?? null,
        reason: body.reason ?? null,
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

// Q105：租户管理 + Onboarding（Q95 后端，platform_admin 红线）。
// 读端点 actor 走 query（adminPath），写端点 actor 在请求体；无删除端点。
export interface TenantView {
  tenant_id: string;
  name: string | null;
  plan: string;
  status: string;
  monthly_token_quota: number | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface TenantOnboarding {
  intakes: number;
  product_spaces: number;
  first_modeling_started: boolean;
}

export interface TenantDetailView extends TenantView {
  onboarding: TenantOnboarding;
}

export async function listTenants(): Promise<TenantView[]> {
  return request<TenantView[]>(adminPath("/api/admin/tenants"));
}

export async function getTenant(tenantId: string): Promise<TenantDetailView> {
  return request<TenantDetailView>(
    adminPath(`/api/admin/tenants/${encodeURIComponent(tenantId)}`),
  );
}

export async function provisionTenant(body: {
  tenantId: string;
  name: string | null;
  plan: string;
}): Promise<TenantView> {
  return request<TenantView>("/api/admin/tenants", {
    method: "POST",
    body: JSON.stringify({
      tenant_id: body.tenantId,
      name: body.name,
      plan: body.plan,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

export async function changeTenantPlan(
  tenantId: string,
  plan: string,
): Promise<TenantView> {
  return request<TenantView>(
    `/api/admin/tenants/${encodeURIComponent(tenantId)}/change-plan`,
    {
      method: "POST",
      body: JSON.stringify({
        plan,
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

export async function pauseTenant(tenantId: string): Promise<TenantView> {
  return request<TenantView>(
    `/api/admin/tenants/${encodeURIComponent(tenantId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify({
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

export async function resumeTenant(tenantId: string): Promise<TenantView> {
  return request<TenantView>(
    `/api/admin/tenants/${encodeURIComponent(tenantId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

// Q107：录入单运营跨租户队列（GET /api/intakes/ops-queue，operations|platform_admin）。
// 写操作复用段1 既有 POST /{id}/transitions，仅 actor 换成管理员身份（须含 operations，
// 状态机对 ops 事件硬角色闸）；不另设写口。
export interface OpsIntakeView extends IntakeView {
  created_at: string;
}

export interface OpsIntakeList {
  items: OpsIntakeView[];
  total: number;
  limit: number;
  offset: number;
}

export async function getOpsIntakeQueue(
  opts: { status?: string; limit?: number; offset?: number } = {},
): Promise<OpsIntakeList> {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
  if (opts.status) params.set("status", opts.status);
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  return request<OpsIntakeList>(`/api/intakes/ops-queue?${params}`);
}

export async function adminTransitionIntake(
  intakeId: string,
  event: string,
  categoryPendingId?: string | null,
): Promise<IntakeView> {
  return request<IntakeView>(
    `/api/intakes/${encodeURIComponent(intakeId)}/transitions`,
    {
      method: "POST",
      body: JSON.stringify({
        event,
        category_pending_id: categoryPendingId ?? null,
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

export interface SlaTodoView {
  todo_id: string;
  tenant_id: string;
  todo_type: string;
  entity_type: string;
  entity_id: string;
  status: string;
  assignee_role: string;
  due_at: string;
  escalated_at: string | null;
  sla_state: "green" | "yellow" | "red" | "resolved";
}

export async function getSlaTodos(status: string): Promise<SlaTodoView[]> {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
  params.set("status", status);
  return request<SlaTodoView[]>(`/api/admin/sla/todos?${params}`);
}

// Q124/Q125：管理端内容运营台（发布队列回填 + 难产作废回池）。
// 读口 operations | platform_admin（adminPath）；写口 operations 硬闸，
// Server Action 在 ADMIN_ROLE_LIST 不含 operations 时直接拒发（同 Q107）。
export async function getReadyToPublishQueue(): Promise<ContentProductListItem[]> {
  return request<ContentProductListItem[]>(
    adminPath("/api/admin/content/ready-to-publish"),
  );
}

export async function getNeedsAttentionQueue(): Promise<ContentProductListItem[]> {
  return request<ContentProductListItem[]>(
    adminPath("/api/admin/content/needs-attention"),
  );
}

export async function setPublishInfo(
  contentId: string,
  url: string,
  platformPostId?: string,
): Promise<ContentProductView> {
  return request<ContentProductView>(
    `/api/admin/content/${encodeURIComponent(contentId)}/publish-info`,
    {
      method: "PUT",
      body: JSON.stringify({
        url,
        platform_post_id: platformPostId ?? null,
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

export async function adminDiscardContent(
  contentId: string,
  reason: string,
): Promise<ContentProductView> {
  return request<ContentProductView>(
    `/api/content/${encodeURIComponent(contentId)}/discard`,
    {
      method: "POST",
      body: JSON.stringify({
        reason,
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

// Q126–Q131：段13 效果回流。管理端孤儿认领台（读双角色、写 operations），
// 客户回填走无 Agent Key 的客户通道（body actor、roles 恒空、租户隔离）。
export interface EffectRecordView {
  record_id: string;
  source: string;
  // 推送方自报的外部内容 ID（对不上本系统成品即为孤儿）。
  content_id: string;
  matched_content_id: string | null;
  tenant_id: string | null;
  platform_post_id: string;
  captured_at: string;
  // 七键稀疏子集；未采集的键缺席（界面显 "—"，绝不显 0）。
  metrics: Record<string, number> | null;
  status: "matched" | "orphan";
  claimed_by: string | null;
  claimed_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface EffectClaimView {
  external_content_id: string;
  content_id: string;
  claimed_by: string;
  claimed_at: string;
  updated_rows: number;
}

export interface EffectClaimBatchView {
  claimed: number;
  updated_rows: number;
}

export interface EffectUnclaimView {
  external_content_id: string;
  reverted_rows: number;
}

export interface EffectBatchReceipt {
  received: number;
  matched: number;
  orphan: number;
  upserted: number;
}

export interface EffectRecordIn {
  content_id: string;
  platform_post_id: string;
  captured_at: string;
  metrics?: Record<string, number>;
}

function adminQuery(path: string, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ actor_id: CURRENT_ADMIN_ACTOR_ID });
  for (const role of ADMIN_ROLE_LIST) params.append("roles", role);
  if (extra)
    for (const [key, value] of Object.entries(extra)) params.set(key, value);
  return `${path}?${params}`;
}

export async function getEffectOrphans(
  opts: { limit?: number; offset?: number } = {},
): Promise<EffectRecordView[]> {
  const extra: Record<string, string> = {};
  if (opts.limit !== undefined) extra.limit = String(opts.limit);
  if (opts.offset !== undefined) extra.offset = String(opts.offset);
  return request<EffectRecordView[]>(
    adminQuery("/api/admin/effects/orphans", extra),
  );
}

export async function getEffectSeries(
  contentId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<EffectRecordView[]> {
  const extra: Record<string, string> = { content_id: contentId };
  if (opts.limit !== undefined) extra.limit = String(opts.limit);
  if (opts.offset !== undefined) extra.offset = String(opts.offset);
  return request<EffectRecordView[]>(adminQuery("/api/admin/effects", extra));
}

export async function claimEffect(
  recordId: string,
  contentId: string,
): Promise<EffectClaimView> {
  return request<EffectClaimView>("/api/admin/effects/claims", {
    method: "POST",
    body: JSON.stringify({
      record_id: recordId,
      content_id: contentId,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

export async function batchClaimEffects(
  items: { record_id: string; content_id: string }[],
): Promise<EffectClaimBatchView> {
  return request<EffectClaimBatchView>("/api/admin/effects/claims/batch", {
    method: "POST",
    body: JSON.stringify({
      items,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

export async function unclaimEffect(
  externalContentId: string,
): Promise<EffectUnclaimView> {
  return request<EffectUnclaimView>("/api/admin/effects/claims/unclaim", {
    method: "POST",
    body: JSON.stringify({
      external_content_id: externalContentId,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

// Q128/Q131：客户效果回填（source 服务端固定 customer-backfill，绝不产生孤儿）。
export async function customerBackfillEffects(
  tenantId: string,
  records: EffectRecordIn[],
): Promise<EffectBatchReceipt> {
  return request<EffectBatchReceipt>("/api/effects/backfill", {
    method: "POST",
    body: JSON.stringify({
      tenant_id: tenantId,
      records,
      actor: { id: CURRENT_ACTOR_ID, roles: [] },
    }),
  });
}

// Q156：批量回填服务端上传逐行回执中的一行（index＝数据行 0 基、line＝含表头物理行号）。
export interface BackfillUploadRow {
  index: number;
  line: number;
  platform_post_id: string;
  captured_at: string;
}

export interface BackfillUploadReceipt extends EffectBatchReceipt {
  filename: string | null;
  rows: BackfillUploadRow[];
}

// Q156/Q159：批量 CSV 回填走服务端上传端点（JSON body 携 CSV 原文，零 multipart 依赖）。
// 服务端解析固定 9 列表头、逐行校验（权威），全合法才整批 all-or-nothing 落库，绝不产生孤儿。
export async function uploadBackfillCsv(
  tenantId: string,
  contentId: string,
  csv: string,
  filename?: string,
): Promise<BackfillUploadReceipt> {
  return request<BackfillUploadReceipt>("/api/effects/backfill/upload", {
    method: "POST",
    body: JSON.stringify({
      tenant_id: tenantId,
      content_id: contentId,
      csv,
      ...(filename ? { filename } : {}),
      actor: { id: CURRENT_ACTOR_ID, roles: [] },
    }),
  });
}

// Q160：批量 Excel（.xlsx）回填，与 CSV 上传同契约。contentBase64 为 .xlsx 字节的
// 标准 base64（JSON body 携文本，零 multipart）；服务端 openpyxl 解析、逐行校验，
// 全合法才整批 all-or-nothing 落库。浏览器不本地解析 xlsx，服务端为唯一权威。
export async function uploadBackfillExcel(
  tenantId: string,
  contentId: string,
  contentBase64: string,
  filename?: string,
): Promise<BackfillUploadReceipt> {
  return request<BackfillUploadReceipt>("/api/effects/backfill/upload-excel", {
    method: "POST",
    body: JSON.stringify({
      tenant_id: tenantId,
      content_id: contentId,
      content_base64: contentBase64,
      ...(filename ? { filename } : {}),
      actor: { id: CURRENT_ACTOR_ID, roles: [] },
    }),
  });
}

// Q166：客户效果数据分析只读聚合（GET /api/effects/analytics，无闸客户读口径）。
export interface EffectAnalyticsContentRow {
  content_id: string | null;
  records: number;
  metrics: Record<string, number>;
}

export interface EffectAnalytics {
  tenant_id: string;
  records_total: number;
  contents_covered: number;
  metrics_totals: Record<string, number>;
  read_rate_avg: number | null;
  read_rate_samples: number;
  captured_from: string | null;
  captured_to: string | null;
  by_content: EffectAnalyticsContentRow[];
  truncated: boolean;
  scan_limit: number;
}

export async function getEffectAnalytics(
  tenantId: string,
  opts: { dateFrom?: string; dateTo?: string } = {},
): Promise<EffectAnalytics> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  if (opts.dateFrom) params.set("date_from", opts.dateFrom);
  if (opts.dateTo) params.set("date_to", opts.dateTo);
  return request<EffectAnalytics>(`/api/effects/analytics?${params}`);
}

// Q167：入站 Agent Key 治理（消费 Q88 后端三端点；列表 GET 免闸不返 secret，
// 签发/吊销 POST 在后端 service 层硬闸 platform_admin，secret 仅签发时返回一次）。
export interface AgentKeyView {
  key_id: string;
  name: string;
  key_prefix: string;
  status: string;
  created_at: string;
  last_used_at: string | null;
}

export interface AgentKeyIssued extends AgentKeyView {
  secret: string;
}

export async function listAgentKeys(
  opts: { includeRevoked?: boolean } = {},
): Promise<AgentKeyView[]> {
  const params = new URLSearchParams();
  if (opts.includeRevoked) params.set("include_revoked", "true");
  const qs = params.toString();
  return request<AgentKeyView[]>(
    `/api/admin/agent-keys${qs ? `?${qs}` : ""}`,
  );
}

export async function issueAgentKey(name: string): Promise<AgentKeyIssued> {
  return request<AgentKeyIssued>("/api/admin/agent-keys", {
    method: "POST",
    body: JSON.stringify({
      name,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

export async function revokeAgentKey(keyId: string): Promise<AgentKeyView> {
  return request<AgentKeyView>(
    `/api/admin/agent-keys/${encodeURIComponent(keyId)}/revoke`,
    {
      method: "POST",
      body: JSON.stringify({
        actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
      }),
    },
  );
}

// Q168：中台导出任务管理（消费 Q132/Q137 /api/exports/jobs；中台无 RBAC 闸，actor 留痕）。
export interface ExportJobView {
  job_id: string;
  tenant_id: string;
  product_space_id: string | null;
  format: string;
  status: string;
  row_count: number;
  file_name: string;
  requested_by: string;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  download_url: string;
}

export interface ExportJobsPage {
  tenant_id: string;
  count: number;
  jobs: ExportJobView[];
}

export interface ExportDownload {
  content: string;
  fileName: string;
  mediaType: string;
}

export async function listExportJobs(
  tenantId: string,
  limit = 50,
): Promise<ExportJobsPage> {
  const params = new URLSearchParams({
    tenant_id: tenantId,
    limit: String(limit),
  });
  return request<ExportJobsPage>(`/api/exports/jobs?${params}`);
}

export async function createExportJob(opts: {
  tenantId: string;
  productSpaceId?: string;
  format: "csv" | "json";
}): Promise<ExportJobView> {
  return request<ExportJobView>("/api/exports/jobs", {
    method: "POST",
    body: JSON.stringify({
      tenant_id: opts.tenantId,
      ...(opts.productSpaceId ? { product_space_id: opts.productSpaceId } : {}),
      format: opts.format,
      actor: { id: CURRENT_ADMIN_ACTOR_ID, roles: ADMIN_ROLE_LIST },
    }),
  });
}

// 下载口返回 csv/json 文本（非 JSON）；文件名取 Content-Disposition，由 client 岛落盘。
export async function downloadExportJob(jobId: string): Promise<ExportDownload> {
  return requestText(`/api/exports/jobs/${encodeURIComponent(jobId)}/download`);
}

// 文本下载通道（与 request 同构，但解析文本体与 Content-Disposition；函数声明提升）。
async function requestText(path: string): Promise<ExportDownload> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new ApiError(res.status, detail || res.statusText);
  }
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  return {
    content: await res.text(),
    fileName: match?.[1] ?? "export.txt",
    mediaType: res.headers.get("content-type") ?? "text/plain",
  };
}

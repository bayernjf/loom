#!/usr/bin/env node
/**
 * Q102：管理端首片（独立布局 + Q92 两驾驶舱只读页）一致性（零依赖）。
 * - admin.* / tokenCost.* / workload.* 消息键齐备；枚举码（model_id/skill_id/
 *   currency_code/target_type/todo_type/state）不进消息表，页面原样直出；
 * - 管理端为 [locale] 下与 (shell) 平级的独立路由组：五文件齐备、两页 force-dynamic、
 *   只经 getTokenCostDashboard/getReviewWorkloadDashboard 访问，禁止 NEXT_PUBLIC；
 * - 管理员身份 V1 env 自报（LOOM_ADMIN_ACTOR_ID / LOOM_ADMIN_ROLES），query 带 actor_id 与重复 roles；
 * - 回归守卫：客户 shell 不放入口（nav.ts 仍恰 8 项、不含 admin），admin 目录不得位于 (shell) 内；
 * - 样式只消费语义 token（禁硬编码颜色）；后端两驾驶舱路由必须存在。
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(here, "..");
const repoRoot = join(frontendRoot, "..");
const adminDir = join(frontendRoot, "app", "[locale]", "admin");
const shellDir = join(frontendRoot, "app", "[locale]", "(shell)");

const messages = JSON.parse(
  readFileSync(join(frontendRoot, "messages", "zh-CN.json"), "utf8"),
);

const requiredKeys = [
  "admin.appName",
  "admin.navLabel",
  "admin.tokenCostNav",
  "admin.reviewWorkloadNav",
  "admin.reviewQueueNav",
  "admin.tenantsNav",
  "admin.opsIntakesNav",
  "admin.slaTodosNav",
  "admin.unconfigured",
  "admin.window",
  "admin.empty",
  "admin.back",
  ...[
    "title",
    "intro",
    "totals",
    "totalRuns",
    "inputTokens",
    "outputTokens",
    "failedRuns",
    "dailyTitle",
    "date",
    "model",
    "currency",
    "runs",
    "inputTokensCol",
    "outputTokensCol",
    "cost",
    "bySkillTitle",
    "skill",
    "failedTitle",
    "failedRunsCol",
    "noDaily",
  ].map((k) => `admin.tokenCost.${k}`),
  ...[
    "title",
    "intro",
    "snapshotAt",
    "candidateBacklog",
    "targetType",
    "pending",
    "oldestWait",
    "todoBacklog",
    "todoType",
    "open",
    "overdue",
    "escalated",
    "totals",
    "pendingCandidates",
    "openTodos",
    "overdueTodos",
    "escalatedTodos",
    "output",
    "candidatesDecided",
    "state",
    "count",
    "todosResolved",
    "empty",
  ].map((k) => `admin.workload.${k}`),
  ...[
    "title",
    "intro",
    "thresholdNote",
    "filters",
    "state",
    "targetType",
    "riskLevel",
    "wfId",
    "apply",
    "reset",
    "colBatch",
    "colType",
    "colRisk",
    "colConfidence",
    "colWait",
    "colWf",
    "colSkill",
    "colCandidate",
    "colCreated",
    "colTenant",
    "colPayload",
    "colDecision",
    "showPayload",
    "humanModified",
    "reviewedBy",
    "reviewedAt",
    "reviewNote",
    "decideConfirm",
    "decideModify",
    "decideReject",
    "submitDecision",
    "submitReject",
    "cancel",
    "reasonField",
    "payloadReplacement",
    "invalidJson",
    "criticalConfirm",
    "decideSuccess",
    "batchApprove",
    "batchReason",
    "batchSuccess",
    "selectFirst",
    "notEligible",
    "prev",
    "next",
    "pageInfo",
    "empty",
  ].map((k) => `admin.reviewQueue.${k}`),
  ...[
    "title",
    "intro",
    "provisionTitle",
    "tenantId",
    "nameOptional",
    "plan",
    "provisionSubmit",
    "provisionSuccess",
    "changePlan",
    "pause",
    "resume",
    "actionSuccess",
    "colTenantId",
    "colName",
    "colPlan",
    "colStatus",
    "colQuota",
    "colCreated",
    "colActions",
    "empty",
    "detailTitle",
    "backToList",
    "onboardingTitle",
    "onboardingNote",
    "intakeCount",
    "spaceCount",
    "firstModelingStarted",
    "yes",
    "no",
  ].map((k) => `admin.tenants.${k}`),
  ...[
    "title",
    "intro",
    "filters",
    "filterStatus",
    "filterAll",
    "apply",
    "reset",
    "colIntake",
    "colTenant",
    "colStatus",
    "colCreated",
    "empty",
    "prev",
    "next",
    "pageInfo",
    "detailTitle",
    "detailSection",
    "fieldIntake",
    "fieldTenant",
    "fieldStatus",
    "fieldCategoryPending",
    "profileTitle",
    "profileEmpty",
    "actionsTitle",
    "noOpsActions",
    "actorUnconfigured",
    "actorMissingRole",
    "actionPending",
    "actionSuccess",
    "eventLabels.ops_confirm",
    "eventLabels.to_cold_start",
    "eventLabels.reject",
    "eventLabels.b2_approved",
    "eventLabels.b2_parent_fallback",
    "eventLabels.b2_rejected",
    "spaceTitle",
    "spaceFieldId",
    "spaceFieldLifecycle",
    "spaceSnapshot",
    "backToQueue",
  ].map((k) => `admin.opsIntakes.${k}`),
  ...[
    "title",
    "intro",
    "yellowNote",
    "filters",
    "filterStatus",
    "filter_open",
    "filter_escalated",
    "filter_resolved",
    "filter_all",
    "apply",
    "reset",
    "colTodo",
    "colTenant",
    "colType",
    "colRole",
    "colEntity",
    "colStatus",
    "colSlaState",
    "colDue",
    "colEscalated",
    "empty",
  ].map((k) => `admin.slaTodos.${k}`),
];

const requiredFiles = [
  "layout.tsx",
  "admin-sidebar.tsx",
  "admin.module.css",
  "page.tsx",
  join("token-cost", "page.tsx"),
  join("review-workload", "page.tsx"),
  join("review-queue", "page.tsx"),
  join("review-queue", "actions.ts"),
  join("review-queue", "batch-bar.tsx"),
  join("review-queue", "decision-cell.tsx"),
  join("tenants", "page.tsx"),
  join("tenants", "actions.ts"),
  join("tenants", "tenant-codes.ts"),
  join("tenants", "provision-form.tsx"),
  join("tenants", "tenant-row-actions.tsx"),
  join("tenants", "[tenantId]", "page.tsx"),
  join("intakes", "page.tsx"),
  join("intakes", "[intakeId]", "page.tsx"),
  join("intakes", "actions.ts"),
  join("intakes", "ops-intake-codes.ts"),
  join("intakes", "ops-intake-actions.tsx"),
  join("sla-todos", "page.tsx"),
];

const problems = [];

function getKey(messages, dotted) {
  return dotted.split(".").reduce((node, part) => node?.[part], messages);
}

for (const key of requiredKeys) {
  const value = getKey(messages, key);
  if (typeof value !== "string" || !value)
    problems.push(`missing message key: ${key}`);
}

// 枚举码不得被翻译进消息表（守 docs/18：系统标识原样展示）。
for (const banned of [
  "pwc_combo",
  "field_plan",
  "c1_recognition",
  "atom_batch",
  "c7_layer4",
  "critical",
  "high",
  "medium",
  "low",
  "pending_review",
  "applied",
  "archived",
  "trial",
  "basic",
  "pro",
  "enterprise",
  "active",
  "paused",
]) {
  const flat = JSON.stringify(messages.admin ?? {});
  if (flat.includes(`"${banned}"`) || flat.includes(`>${banned}<`))
    problems.push(`enum code must not be translated into admin messages: ${banned}`);
}

for (const rel of requiredFiles) {
  if (!existsSync(join(adminDir, rel))) problems.push(`missing file: app/[locale]/admin/${rel}`);
}

function readAdmin(rel) {
  return readFileSync(join(adminDir, rel), "utf8");
}

const tokenPage = readAdmin(join("token-cost", "page.tsx"));
const workloadPage = readAdmin(join("review-workload", "page.tsx"));
const sidebarText = readAdmin("admin-sidebar.tsx");
const layoutText = readAdmin("layout.tsx");
const cssText = readAdmin("admin.module.css");
const indexText = readAdmin("page.tsx");

for (const [name, text] of [
  ["token-cost/page.tsx", tokenPage],
  ["review-workload/page.tsx", workloadPage],
]) {
  if (!/export const dynamic = "force-dynamic"/.test(text))
    problems.push(`${name} must be force-dynamic (server-only env)`);
  if (/NEXT_PUBLIC/.test(text))
    problems.push(`${name} must not read NEXT_PUBLIC_* env (no browser direct API)`);
  if (/https?:\/\//.test(text))
    problems.push(`${name} must not hardcode backend URLs (go through lib/api)`);
}
if (!/\bgetTokenCostDashboard\b/.test(tokenPage))
  problems.push("token-cost page must fetch via getTokenCostDashboard");
if (!/\bgetReviewWorkloadDashboard\b/.test(workloadPage))
  problems.push("review-workload page must fetch via getReviewWorkloadDashboard");

for (const [name, text] of [
  ["token-cost/page.tsx", tokenPage],
  ["review-workload/page.tsx", workloadPage],
]) {
  for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
    if (text.includes(forbidden))
      problems.push(`${name} is read-only; must not contain ${forbidden}`);
  }
}

if (!sidebarText.includes("/admin/token-cost") || !sidebarText.includes("/admin/review-workload"))
  problems.push("admin sidebar must link both dashboards");
if (!sidebarText.includes("/admin/review-queue"))
  problems.push("admin sidebar must link the unified review queue");
if (!sidebarText.includes("/admin/tenants"))
  problems.push("admin sidebar must link tenant management");
if (!sidebarText.includes("/admin/intakes"))
  problems.push("admin sidebar must link the ops intake queue (Q107)");
if (!sidebarText.includes("/admin/sla-todos"))
  problems.push("admin sidebar must link the SLA todo board (Q108)");
{
  const navCount = [...sidebarText.matchAll(/href:\s*"\/admin\/[^"]+"/g)].length;
  if (navCount !== 6)
    problems.push(`admin sidebar must keep exactly 6 admin entries, got ${navCount}`);
}
if (!sidebarText.includes('"/workbench"'))
  problems.push("admin sidebar must provide back link to /workbench");
if (!layoutText.includes("AdminSidebar"))
  problems.push("admin layout must render AdminSidebar");
if (!/redirect\(/.test(indexText))
  problems.push("admin index must redirect to a dashboard");

if (/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(cssText))
  problems.push("admin.module.css must use semantic tokens only (no hardcoded colors)");

const apiText = readFileSync(join(frontendRoot, "lib", "api.ts"), "utf8");
for (const token of [
  "LOOM_ADMIN_ACTOR_ID",
  "LOOM_ADMIN_ROLES",
  "/api/admin/dashboards/token-cost",
  "/api/admin/dashboards/review-workload",
  "getTokenCostDashboard",
  "getReviewWorkloadDashboard",
  "getReviewQueue",
  "batchApprove",
  "decideCandidate",
  "listTenants",
  "getTenant",
  "provisionTenant",
  "changeTenantPlan",
  "pauseTenant",
  "resumeTenant",
  "/api/review-workbench/candidates",
  "/api/review-workbench/batch-approve",
  "/api/skill-candidates/",
  "/api/admin/tenants",
  "actor_id",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}
if (!/append\("roles"/.test(apiText))
  problems.push("lib/api.ts must append repeated roles query params");
if (/NEXT_PUBLIC_ADMIN|NEXT_PUBLIC_LOOM/.test(apiText))
  problems.push("admin identity must not be exposed via NEXT_PUBLIC_*");

// 回归守卫：客户 shell 八菜单不含管理端入口。
const navText = readFileSync(
  join(frontendRoot, "app", "[locale]", "nav.ts"),
  "utf8",
);
const navHrefs = [...navText.matchAll(/href:\s*"([^"]+)"/g)].map((m) => m[1]);
if (navHrefs.length !== 8)
  problems.push(`customer nav must keep exactly 8 entries, got ${navHrefs.length}`);
if (navHrefs.some((href) => href.startsWith("/admin")))
  problems.push("customer nav must not contain admin entries");
if (existsSync(join(shellDir, "admin")))
  problems.push("admin route group must be outside (shell)");

const routerText = readFileSync(
  join(repoRoot, "backend", "app", "core", "dashboards", "router.py"),
  "utf8",
);
if (!routerText.includes('prefix="/api/admin/dashboards"'))
  problems.push('backend dashboards router must mount at /api/admin/dashboards');
for (const path of ["/token-cost", "/review-workload"]) {
  if (!new RegExp(`@router\\.get\\("${path.replace("/", "\\/")}"\\)`).test(routerText))
    problems.push(`backend dashboards router must register GET ${path}`);
}
if (!/require_admin_view/.test(routerText))
  problems.push("dashboards router must depend on require_admin_view");

// Q103：统一审核工作台页（队列消费 + 批量通过 Server Action）。
const queuePage = readAdmin(join("review-queue", "page.tsx"));
const queueActions = readAdmin(join("review-queue", "actions.ts"));
const queueClient = readAdmin(join("review-queue", "batch-bar.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(queuePage))
  problems.push("review-queue/page.tsx must be force-dynamic (server-only env)");
if (!/\bgetReviewQueue\b/.test(queuePage))
  problems.push("review-queue page must fetch via getReviewQueue");
if (/NEXT_PUBLIC/.test(queuePage) || /https?:\/\//.test(queuePage))
  problems.push("review-queue page must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (queuePage.includes(forbidden))
    problems.push(`review-queue page is read-only; must not contain ${forbidden}`);
}
for (const code of [
  "pwc_combo",
  "field_plan",
  "c1_recognition",
  "atom_batch",
  "c7_layer4",
  "critical",
  "high",
  "medium",
  "low",
  "pending_review",
  "applied",
  "archived",
]) {
  if (!queuePage.includes(code))
    problems.push(`review-queue page must render enum code raw: ${code}`);
}
if (!queuePage.includes("data-batch-candidate"))
  problems.push("review-queue rows must expose data-batch-candidate checkboxes");
if (!queuePage.includes("<details>") || !queuePage.includes("JSON.stringify"))
  problems.push("review-queue payload must render as raw JSON in a details/pre fold");
if (!/"use server"/.test(queueActions))
  problems.push("review-queue actions must be a Server Action module");
if (!/\bbatchApproveAction\b/.test(queueActions))
  problems.push("review-queue actions must expose batchApproveAction");
for (const status of [403, 404, 409, 422]) {
  if (!queueActions.includes(String(status)))
    problems.push(`batchApproveAction must map failure status ${status}`);
}
if (!/CURRENT_ADMIN_ACTOR_ID/.test(queueActions))
  problems.push("batchApproveAction must derive actor from server env");
if (queueClient.includes("@/lib/api") || /https?:\/\//.test(queueClient))
  problems.push("batch bar client island must call only the Server Action, never the API directly");
if (!queueClient.includes("data-batch-candidate") || !queueClient.includes("router.refresh"))
  problems.push("batch bar must collect checked rows and refresh the RSC list");

const workbenchRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "workbench", "router.py"),
  "utf8",
);
if (!workbenchRouter.includes('prefix="/api/review-workbench"'))
  problems.push("backend workbench router must mount at /api/review-workbench");
if (!/@router\.get\("\/candidates"\)/.test(workbenchRouter))
  problems.push("workbench router must register GET /candidates");
if (!/@router\.post\("\/batch-approve"\)/.test(workbenchRouter))
  problems.push("workbench router must register POST /batch-approve");
if (!/require_workbench_view/.test(workbenchRouter))
  problems.push("workbench queue endpoint must depend on require_workbench_view");
const workbenchService = readFileSync(
  join(repoRoot, "backend", "app", "core", "workbench", "service.py"),
  "utf8",
);
if (!workbenchService.includes('"payload": cand.payload'))
  problems.push("workbench queue view must return raw candidate payload (Q103 additive)");
if (!workbenchService.includes('"review_note": cand.review_note'))
  problems.push("workbench queue view must return review_note (Q104 additive)");

// Q104：逐条裁决（confirmed/modified/rejected + payload 替换编辑器）。
const decisionCellPath = join("review-queue", "decision-cell.tsx");
const decisionCell = existsSync(join(adminDir, decisionCellPath))
  ? readAdmin(decisionCellPath)
  : "";

if (decisionCell) {
  if (!/^"use client"/m.test(decisionCell))
    problems.push("decision cell must be a client island");
  if (decisionCell.includes("@/lib/api") || /https?:\/\//.test(decisionCell))
    problems.push("decision cell must call only the Server Action, never the API directly");
  for (const token of [
    "decideCandidateAction",
    "router.refresh",
    "JSON.parse",
    "window.confirm",
    "modified",
    "rejected",
    "confirmed",
  ]) {
    if (!decisionCell.includes(token))
      problems.push(`decision cell must contain ${token}`);
  }
}
if (!/"use server"/.test(queueActions))
  problems.push("review-queue actions must be a Server Action module");
if (!/\bdecideCandidateAction\b/.test(queueActions))
  problems.push("review-queue actions must expose decideCandidateAction");
const decideActionBody = queueActions.split("decideCandidateAction")[1] ?? "";
for (const status of [403, 404, 409, 422]) {
  if (!decideActionBody.includes(String(status)))
    problems.push(`decideCandidateAction must map failure status ${status}`);
}
if (!/\/api\/skill-candidates\//.test(apiText))
  problems.push("per-candidate decision must POST to /api/skill-candidates/{id}/decision");
if (!apiText.includes("/decision`"))
  problems.push("decideCandidate must hit the /decision sub-path");
if (!queuePage.includes("<DecisionCell") || !queuePage.includes("colDecision"))
  problems.push("review-queue page must render the decision column and island");
if (!queuePage.includes('cand.state === "pending_review"'))
  problems.push("decision island must render only for pending_review rows");

// Q105：租户管理 + Onboarding（Q95 后端的前端消费；纯前端无迁移）。
const tenantsDir = join(adminDir, "tenants");
const tenantsPage = readFileSync(join(tenantsDir, "page.tsx"), "utf8");
const tenantDetailPage = readFileSync(
  join(tenantsDir, "[tenantId]", "page.tsx"),
  "utf8",
);
const tenantsActions = readFileSync(join(tenantsDir, "actions.ts"), "utf8");
const tenantCodes = readFileSync(join(tenantsDir, "tenant-codes.ts"), "utf8");
const provisionClient = readFileSync(join(tenantsDir, "provision-form.tsx"), "utf8");
const rowClient = readFileSync(join(tenantsDir, "tenant-row-actions.tsx"), "utf8");

for (const [name, text] of [
  ["tenants/page.tsx", tenantsPage],
  ["tenants/[tenantId]/page.tsx", tenantDetailPage],
]) {
  if (!/export const dynamic = "force-dynamic"/.test(text))
    problems.push(`${name} must be force-dynamic (server-only env)`);
  if (/NEXT_PUBLIC/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must not read NEXT_PUBLIC_* or hardcode URLs`);
  for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
    if (text.includes(forbidden))
      problems.push(`${name} is read-only; must not contain ${forbidden}`);
  }
}
if (!/\blistTenants\b/.test(tenantsPage))
  problems.push("tenants page must fetch via listTenants");
if (!/\bgetTenant\b/.test(tenantDetailPage))
  problems.push("tenant detail page must fetch via getTenant");
for (const field of ["intakes", "product_spaces", "first_modeling_started"]) {
  if (!tenantDetailPage.includes(field))
    problems.push(`tenant detail page must render derived onboarding field ${field}`);
}
if (!/"use server"/.test(tenantsActions))
  problems.push("tenants actions must be a Server Action module");
for (const name of [
  "provisionTenantAction",
  "changePlanAction",
  "pauseTenantAction",
  "resumeTenantAction",
]) {
  if (!tenantsActions.includes(name))
    problems.push(`tenants actions must expose ${name}`);
}
for (const status of [403, 404, 409, 422]) {
  if (!tenantsActions.includes(String(status)))
    problems.push(`tenant actions must map failure status ${status}`);
}
if (!/CURRENT_ADMIN_ACTOR_ID/.test(tenantsActions))
  problems.push("tenant actions must derive actor from server env");
for (const [name, text] of [
  ["provision-form", provisionClient],
  ["tenant-row-actions", rowClient],
]) {
  if (!/^"use client"/m.test(text))
    problems.push(`${name} must be a client island`);
  if (text.includes("@/lib/api") || /https?:\/\//.test(text))
    problems.push(`${name} client island must call only Server Actions, never the API directly`);
  if (!text.includes("router.refresh"))
    problems.push(`${name} island must refresh the RSC view after success`);
}
for (const token of [
  "provisionTenantAction",
  "changePlanAction",
  "pauseTenantAction",
  "resumeTenantAction",
]) {
  if (!provisionClient.includes(token) && !rowClient.includes(token))
    problems.push(`no tenant island calls ${token}`);
}
for (const code of ["trial", "basic", "pro", "enterprise"]) {
  if (!tenantCodes.includes(`"${code}"`))
    problems.push(`tenant plan code must render raw: ${code}`);
}
for (const code of ["trial", "active", "paused"]) {
  if (!tenantCodes.includes(`"${code}"`) && !tenantsPage.includes(`"${code}"`) && !tenantDetailPage.includes(`"${code}"`))
    problems.push(`tenant status code must appear raw in codes or pages: ${code}`);
}
if (!/statusTrial/.test(tenantsPage) || !/statusActive/.test(tenantsPage) || !/statusPaused/.test(tenantsPage))
  problems.push("tenant status chips must map trial/active/paused to semantic styles");
if (!/\/change-plan/.test(apiText) || !/\/pause`/.test(apiText) || !/\/resume`/.test(apiText))
  problems.push("lib/api.ts must expose change-plan/pause/resume tenant endpoints");

const tenantsRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "tenants", "router.py"),
  "utf8",
);
if (!tenantsRouter.includes('prefix="/api/admin/tenants"'))
  problems.push("backend tenants router must mount at /api/admin/tenants");
if (!/require_admin_view/.test(tenantsRouter))
  problems.push("tenants read endpoints must depend on require_admin_view (platform_admin)");
for (const route of ['@router.post("",', '@router.get("",', '@router.get("/{tenant_id}"', 'change-plan",', 'pause",', 'resume",']) {
  if (!tenantsRouter.includes(route))
    problems.push(`backend tenants router must register route ${route}`);
}

// Q107：录入单运营跨租户队列与操作岛（后端一只读端点，写复用 transitions）。
const intakesDir = join(adminDir, "intakes");
const opsListPage = readFileSync(join(intakesDir, "page.tsx"), "utf8");
const opsDetailPage = readFileSync(join(intakesDir, "[intakeId]", "page.tsx"), "utf8");
const opsActions = readFileSync(join(intakesDir, "actions.ts"), "utf8");
const opsCodes = readFileSync(join(intakesDir, "ops-intake-codes.ts"), "utf8");
const opsIsland = readFileSync(join(intakesDir, "ops-intake-actions.tsx"), "utf8");

for (const [name, text] of [
  ["intakes/page.tsx", opsListPage],
  ["intakes/[intakeId]/page.tsx", opsDetailPage],
]) {
  if (!/export const dynamic = "force-dynamic"/.test(text))
    problems.push(`${name} must be force-dynamic (server-only env)`);
  if (/NEXT_PUBLIC/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must not read NEXT_PUBLIC_* or hardcode URLs`);
  for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
    if (text.includes(forbidden))
      problems.push(`${name} is read-only; must not contain ${forbidden}`);
  }
}
if (!/\bgetOpsIntakeQueue\b/.test(opsListPage))
  problems.push("ops intake list page must fetch via getOpsIntakeQueue");
for (const token of ["getIntake", "getAllowedEvents", "getProductSpace", "OpsIntakeActions"]) {
  if (!opsDetailPage.includes(token))
    problems.push(`ops intake detail page must use ${token}`);
}
if (!/notFound\(/.test(opsDetailPage))
  problems.push("ops intake detail page must map 404 to notFound()");

// 白名单恰为 6 个 requires_role=operations 事件；系统/客户事件一律不得外放。
const opsEventKeys = [
  "ops_confirm",
  "to_cold_start",
  "reject",
  "b2_approved",
  "b2_parent_fallback",
  "b2_rejected",
];
{
  const listMatch = opsCodes.match(/OPS_INTAKE_EVENTS\s*=\s*\[([\s\S]*?)\]/);
  const listed = listMatch ? [...listMatch[1].matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]) : [];
  if (JSON.stringify(listed) !== JSON.stringify(opsEventKeys))
    problems.push(`OPS_INTAKE_EVENTS must be exactly ${opsEventKeys.join(",")}, got ${listed.join(",")}`);
  // 注释行只做排除说明（白名单设计依据），禁词扫描只看代码本体。
  const opsCode = opsCodes.replace(/^\s*\/\/.*$/gm, "");
  const opsActionCode = opsActions.replace(/^\s*\/\/.*$/gm, "");
  for (const banned of [
    "auto_confirm",
    "wf01_",
    "send_review",
    "review_approve",
    "review_reject",
    "start_modeling",
    "params_completed",
    "quota_confirmed",
    "resubmit",
  ]) {
    if (opsCode.includes(banned) || opsIsland.includes(banned) || opsActionCode.includes(banned))
      problems.push(`ops intake whitelist must not expose non-ops event: ${banned}`);
  }
  const statusMatch = opsCodes.match(/INTAKE_STATUS_FILTERS\s*=\s*\[([\s\S]*?)\]/);
  const statuses = statusMatch
    ? [...statusMatch[1].matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1])
    : [];
  if (statuses.length !== 15)
    problems.push(`INTAKE_STATUS_FILTERS must list all 15 productIntake states, got ${statuses.length}`);
}
{
  const labels = messages.admin?.opsIntakes?.eventLabels ?? {};
  if (JSON.stringify(Object.keys(labels).sort()) !== JSON.stringify([...opsEventKeys].sort()))
    problems.push("admin.opsIntakes.eventLabels must cover exactly the 6 ops event codes");
}

if (!/^"use server"/m.test(opsActions))
  problems.push("ops intake actions must be a Server Action module");
if (!/\bopsTransitionIntakeAction\b/.test(opsActions))
  problems.push("ops intake actions must expose opsTransitionIntakeAction");
for (const status of [403, 404, 409, 422]) {
  if (!opsActions.includes(String(status)))
    problems.push(`opsTransitionIntakeAction must map failure status ${status}`);
}
for (const token of ["unconfigured", "missing_role", "CURRENT_ADMIN_ACTOR_ID", "ADMIN_ROLE_LIST", "isOpsIntakeEvent"]) {
  if (!opsActions.includes(token))
    problems.push(`ops intake actions must contain ${token}`);
}
if (!/^"use client"/m.test(opsIsland))
  problems.push("ops intake action island must be a client island");
if (opsIsland.includes("@/lib/api") || /https?:\/\//.test(opsIsland))
  problems.push("ops intake island must call only the Server Action, never the API directly");
if (!opsIsland.includes("router.refresh"))
  problems.push("ops intake island must refresh the RSC view after success");
if (!opsIsland.includes("OPS_INTAKE_EVENTS") || !opsIsland.includes("isOpsIntakeEvent"))
  problems.push("ops intake island must render buttons in whitelist order intersect allowed-events");

for (const token of [
  "getOpsIntakeQueue",
  "adminTransitionIntake",
  "/api/intakes/ops-queue",
  "ADMIN_ROLE_LIST",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

const intakeRouter = readFileSync(
  join(repoRoot, "backend", "app", "product", "product_intake", "router.py"),
  "utf8",
);
if (!intakeRouter.includes('@router.get("/ops-queue"'))
  problems.push("intake router must register GET /api/intakes/ops-queue");
if (!/require_ops_view/.test(intakeRouter))
  problems.push("ops queue endpoint must depend on require_ops_view");
if (!/require_any_role\(actor, OPERATIONS, PLATFORM_ADMIN\)/.test(intakeRouter))
  problems.push("require_ops_view must allow OPERATIONS and PLATFORM_ADMIN only");
if (!/STATE_LABELS/.test(intakeRouter) || !/status_code=422/.test(intakeRouter))
  problems.push("ops queue must reject unknown status filters with 422 against STATE_LABELS");
if (
  intakeRouter.indexOf('@router.get("/ops-queue"') === -1 ||
  intakeRouter.indexOf('@router.get("/ops-queue"') >
    intakeRouter.indexOf('@router.get("/{intake_id}"')
)
  problems.push("/ops-queue must be registered before /{intake_id} to avoid path capture");
{
  const opsService = readFileSync(
    join(repoRoot, "backend", "app", "product", "product_intake", "service.py"),
    "utf8",
  );
  if (!/async def list_ops_intakes/.test(opsService))
    problems.push("intake service must define list_ops_intakes (cross-tenant)");
}

// Q108：待办 SLA 看板（纯只读 RSC；枚举码原样，POST /sla/run 不上页面）。
const slaPage = readFileSync(join(adminDir, "sla-todos", "page.tsx"), "utf8");
if (!/export const dynamic = "force-dynamic"/.test(slaPage))
  problems.push("sla-todos/page.tsx must be force-dynamic (server-only env)");
if (/"use server"/.test(slaPage))
  problems.push("sla-todos/page.tsx must stay read-only (no Server Actions)");
const slaPageCode = slaPage.replace(/^\s*\/\/.*$/gm, "");
if (/NEXT_PUBLIC/.test(slaPageCode) || /https?:\/\//.test(slaPageCode))
  problems.push("sla-todos/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
if (/\/zh-CN\//.test(slaPageCode))
  problems.push("sla-todos/page.tsx must use i18n Link, no hardcoded locale paths");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE", "/sla/run"]) {
  if (slaPageCode.includes(forbidden))
    problems.push(`sla-todos/page.tsx is read-only; must not contain ${forbidden}`);
}
for (const token of [
  "getSlaTodos",
  "CURRENT_ADMIN_ACTOR_ID",
  '"open"',
  '"escalated"',
  '"resolved"',
  '"all"',
  "yellowNote",
  "shortId",
  "riskCritical",
  "riskMedium",
  "riskLow",
  "stateArchived",
  "sla_state",
]) {
  if (!slaPage.includes(token))
    problems.push(`sla-todos/page.tsx must contain ${token}`);
}

for (const token of [
  "getSlaTodos",
  "SlaTodoView",
  "/api/admin/sla/todos",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

const slaRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "sla", "router.py"),
  "utf8",
);
if (!/def require_sla_view/.test(slaRouter))
  problems.push("SLA board must gate via require_sla_view");
if (!/require_any_role\(actor, PLATFORM_ADMIN\)/.test(slaRouter))
  problems.push("require_sla_view must allow PLATFORM_ADMIN only");
if (!/Depends\(require_sla_view\)/.test(slaRouter))
  problems.push("GET /todos must depend on require_sla_view");
if (!/@router\.get\("\/todos"\)/.test(slaRouter))
  problems.push("SLA router must register GET /todos");
for (const token of ["TODO_STATUS_FILTERS", "unknown todo status:"]) {
  if (!slaRouter.includes(token))
    problems.push(`SLA router must contain ${token} (422 whitelist)`);
}

if (problems.length > 0) {
  console.error(`check-admin: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-admin: admin layout, dashboards, env identity and shell isolation consistent");

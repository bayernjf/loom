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
  "admin.contentOpsNav",
  "admin.effectsNav",
  "admin.agentKeysNav",
  "admin.staffKeysNav",
  "admin.exportsNav",
  "admin.fcwNav",
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
    "publishTitle",
    "publishIntro",
    "publishEmpty",
    "attentionTitle",
    "attentionIntro",
    "attentionEmpty",
    "colFinal",
    "colTenant",
    "colPlatform",
    "colLanguage",
    "colStatus",
    "colQuality",
    "colReview",
    "colCreated",
    "colPublish",
    "colDiscard",
    "publishFormLabel",
    "urlLabel",
    "urlPlaceholder",
    "postIdLabel",
    "postIdPlaceholder",
    "publishSubmit",
    "republishSubmit",
    "publishSuccess",
    "discardFormLabel",
    "reasonLabel",
    "reasonPlaceholder",
    "discardSubmit",
    "discardConfirm",
    "discardSuccess",
    "actorUnconfigured",
    "actorMissingRole",
  ].map((k) => `admin.contentOps.${k}`),
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
  ...[
    "title",
    "intro",
    "orphanTitle",
    "orphanIntro",
    "orphanEmpty",
    "seriesTitle",
    "seriesIntro",
    "colSelect",
    "colExternal",
    "colSource",
    "colPost",
    "colCaptured",
    "colMetrics",
    "colTarget",
    "colAction",
    "colStatus",
    "colClaim",
    "targetPlaceholder",
    "claimSubmit",
    "claimSuccess",
    "batchSubmit",
    "seriesInputLabel",
    "seriesInputPlaceholder",
    "seriesQuery",
    "seriesEmpty",
    "claimedBy",
    "unclaimSubmit",
    "unclaimConfirm",
    "unclaimSuccess",
    "status.matched",
    "status.orphan",
    "metric.plays",
    "metric.likes",
    "metric.comments",
    "metric.shares",
    "metric.inquiries",
    "metric.conversions",
    "metric.read_rate",
    "actorUnconfigured",
    "actorMissingRole",
  ].map((k) => `admin.effects.${k}`),
  ...[
    "title",
    "intro",
    "issueTitle",
    "nameLabel",
    "namePlaceholder",
    "issueSubmit",
    "secretOnceWarning",
    "copySecret",
    "copied",
    "listTitle",
    "showRevoked",
    "hideRevoked",
    "empty",
    "loadFailed",
    "colName",
    "colPrefix",
    "colStatus",
    "colCreated",
    "colLastUsed",
    "colAction",
    "revokeSubmit",
    "revokeConfirm",
    "statusRevoked",
    "actorUnconfigured",
    "actorMissingRole",
  ].map((k) => `admin.agentKeys.${k}`),
  ...[
    "title",
    "intro",
    "issueTitle",
    "staffIdLabel",
    "staffIdPlaceholder",
    "staffNameLabel",
    "staffNamePlaceholder",
    "rolesLabel",
    "issueSubmit",
    "secretOnceWarning",
    "copySecret",
    "copied",
    "listTitle",
    "showRevoked",
    "hideRevoked",
    "empty",
    "loadFailed",
    "colStaff",
    "colName",
    "colRoles",
    "colPrefix",
    "colStatus",
    "colCreated",
    "colLastUsed",
    "colAction",
    "revokeSubmit",
    "revokeConfirm",
    "statusRevoked",
    "actorUnconfigured",
    "actorMissingRole",
  ].map((k) => `admin.staffKeys.${k}`),
  ...[
    "title",
    "intro",
    "identityLabel",
    "logout",
    "tokenLabel",
    "tokenPlaceholder",
    "submit",
    "emptyToken",
    "disabledHint",
    "invalidHint",
  ].map((k) => `admin.staffAuth.${k}`),
  ...[
    "title",
    "intro",
    "tenantLabel",
    "tenantPlaceholder",
    "querySubmit",
    "needTenant",
    "createTitle",
    "formatLabel",
    "productSpaceLabel",
    "productSpacePlaceholder",
    "createSubmit",
    "listTitle",
    "empty",
    "loadFailed",
    "colJob",
    "colFormat",
    "colStatus",
    "colRows",
    "colFile",
    "colCreated",
    "colCompleted",
    "colAction",
    "downloadSubmit",
    "notReady",
    "actorUnconfigured",
  ].map((k) => `admin.exports.${k}`),
  ...[
    "title",
    "intro",
    "tenantLabel",
    "tenantPlaceholder",
    "querySubmit",
    "reset",
    "listTitle",
    "empty",
    "loadFailed",
    "actorUnconfigured",
    "actorMissingRole",
    "colFinal",
    "colTenant",
    "colPlatform",
    "colSlot",
    "colGoal",
    "colScore",
    "colStatus",
    "colCreated",
    "colAction",
    "pageInfo",
    "prev",
    "next",
    "materialShow",
    "materialHide",
    "materialLoading",
    "downloadMaterial",
    "copyId",
    "copied",
    "bulkCopy",
    "bulkCopyHint",
    "selectAll",
    "warningsTitle",
    "guardsTitle",
    "layer.product",
    "layer.platform",
    "layer.strategy",
    "layer.structure",
    "layer.expression",
    "layer.compliance",
  ].map((k) => `admin.fcw.${k}`),
  ...["from", "to", "apply", "reset", "placeholderFrom", "placeholderTo", "invalidRange"].map(
    (k) => `admin.dateFilter.${k}`,
  ),
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
  join("content", "page.tsx"),
  join("content", "actions.ts"),
  join("content", "publish-info-island.tsx"),
  join("content", "discard-island.tsx"),
  join("effects", "page.tsx"),
  join("effects", "actions.ts"),
  join("effects", "orphan-table-island.tsx"),
  join("effects", "series-island.tsx"),
  join("effects", "effect-fields.ts"),
  join("agent-keys", "page.tsx"),
  join("agent-keys", "actions.ts"),
  join("agent-keys", "issue-island.tsx"),
  join("agent-keys", "revoke-island.tsx"),
  join("staff-keys", "page.tsx"),
  join("staff-keys", "actions.ts"),
  join("staff-keys", "issue-staff-island.tsx"),
  join("staff-keys", "revoke-staff-island.tsx"),
  join("login", "page.tsx"),
  join("login", "actions.ts"),
  join("login", "login-island.tsx"),
  join("exports", "page.tsx"),
  join("exports", "actions.ts"),
  join("exports", "create-island.tsx"),
  join("exports", "download-island.tsx"),
  join("fcw", "page.tsx"),
  join("fcw", "actions.ts"),
  join("fcw", "material-island.tsx"),
  join("fcw", "fcw-table.tsx"),
  join("_components", "DateRangeFilter.tsx"),
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
if (!sidebarText.includes("/admin/content"))
  problems.push("admin sidebar must link the content ops page (Q124/Q125)");
if (!sidebarText.includes("/admin/effects"))
  problems.push("admin sidebar must link the effects ops page (Q130)");
if (!sidebarText.includes("/admin/agent-keys"))
  problems.push("admin sidebar must link the agent key admin page (Q167)");
if (!sidebarText.includes("/admin/staff-keys"))
  problems.push("admin sidebar must link the staff PAT admin page (Q178)");
if (!sidebarText.includes("/admin/exports"))
  problems.push("admin sidebar must link the export jobs admin page (Q168)");
if (!sidebarText.includes("/admin/fcw"))
  problems.push("admin sidebar must link the in-platform whitelist card page (Q177)");
{
  const navCount = [...sidebarText.matchAll(/href:\s*"\/admin\/[^"]+"/g)].length;
  if (navCount !== 12)
    problems.push(`admin sidebar must keep exactly 12 admin entries, got ${navCount}`);
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
  "listAgentKeys",
  "issueAgentKey",
  "revokeAgentKey",
  "/api/admin/agent-keys",
  "listStaffKeys",
  "issueStaffKey",
  "revokeStaffKey",
  "getStaffMe",
  "/api/admin/staff-keys",
  "/api/auth/me",
  "getStaffToken",
  "Authorization",
  "Bearer ",
  "/admin/login",
  "listExportJobs",
  "createExportJob",
  "downloadExportJob",
  "/api/exports/jobs",
  "listAdminFcw",
  "getAdminFcwMaterial",
  "/api/admin/fcw",
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

// Q124/Q125：管理端内容运营台（发布回填 + 作废回池；读双角色、写 operations）。
const contentOpsDir = join(adminDir, "content");
const contentOpsPage = readAdmin(join("content", "page.tsx"));
const contentOpsActions = readAdmin(join("content", "actions.ts"));
const publishIsland = readAdmin(join("content", "publish-info-island.tsx"));
const discardIsland = readAdmin(join("content", "discard-island.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(contentOpsPage))
  problems.push("admin/content/page.tsx must be force-dynamic (server-only env)");
if (/NEXT_PUBLIC/.test(contentOpsPage) || /https?:\/\//.test(contentOpsPage))
  problems.push("admin/content/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (contentOpsPage.includes(forbidden))
    problems.push(`admin/content/page.tsx is read-only; must not contain ${forbidden}`);
}
for (const token of ["getReadyToPublishQueue", "getNeedsAttentionQueue", "PublishInfoIsland", "DiscardIsland"]) {
  if (!contentOpsPage.includes(token))
    problems.push(`admin/content/page.tsx must use ${token}`);
}
if (!/^"use server"/m.test(contentOpsActions))
  problems.push("admin/content/actions.ts must be a Server Action module");
for (const token of [
  "setPublishInfoAction",
  "discardContentAction",
  "CURRENT_ADMIN_ACTOR_ID",
  "missing_role",
  "unconfigured",
  "ADMIN_ROLE_LIST",
  "setPublishInfo",
  "adminDiscardContent",
]) {
  if (!contentOpsActions.includes(token))
    problems.push(`admin/content/actions.ts must contain ${token}`);
}
for (const status of [403, 404, 409, 422]) {
  if (!contentOpsActions.includes(String(status)))
    problems.push(`content ops actions must map failure status ${status}`);
}
for (const [name, text] of [
  ["publish-info-island", publishIsland],
  ["discard-island", discardIsland],
]) {
  if (!/^"use client"/m.test(text))
    problems.push(`${name} must be a client island`);
  if (text.includes("@/lib/api") || /\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must call only the Server Action, never the API directly`);
  if (!text.includes("router.refresh"))
    problems.push(`${name} must refresh the RSC view after success`);
}
if (!discardIsland.includes("window.confirm"))
  problems.push("discard island must confirm the terminal discard action");
for (const token of [
  "getReadyToPublishQueue",
  "getNeedsAttentionQueue",
  "setPublishInfo",
  "adminDiscardContent",
  "/api/admin/content/ready-to-publish",
  "/api/admin/content/needs-attention",
  "/publish-info",
  "/discard",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

// Windows 检出（core.autocrlf=true）下后端源码可能为 CRLF，统一归一为 LF，
// 使下方跨行字面量匹配与平台无关（LF 检出时此 replace 为空操作）。
const contentRouter = readFileSync(
  join(repoRoot, "backend", "app", "content", "router.py"),
  "utf8",
).replace(/\r\n/g, "\n");
for (const route of [
  '@router.get(\n    "/api/admin/content/ready-to-publish"',
  '@router.get(\n    "/api/admin/content/needs-attention"',
  '@router.put(\n    "/api/admin/content/{content_id}/publish-info"',
  '@router.post(\n    "/api/content/{content_id}/discard"',
]) {
  if (!contentRouter.includes(route))
    problems.push(`backend content router must register ${route.replace(/\s+/g, " ")}`);
}
// 两个静态 GET 队列必须先于参数路径 PUT/POST 注册，避免被 {content_id} 吞掉。
const needsAttentionAt = contentRouter.indexOf("/api/admin/content/needs-attention");
const publishInfoAt = contentRouter.indexOf("/api/admin/content/{content_id}/publish-info");
if (needsAttentionAt === -1 || publishInfoAt === -1 || needsAttentionAt > publishInfoAt)
  problems.push("GET needs-attention must be registered before the publish-info parameter route");

// Q129/Q130：管理端效果回流运营台（孤儿认领/批量/解绑 + 成品时序查询）。
const effectsDir = join(adminDir, "effects");
const effectsPage = readAdmin(join("effects", "page.tsx"));
const effectsActions = readAdmin(join("effects", "actions.ts"));
const orphanIsland = readAdmin(join("effects", "orphan-table-island.tsx"));
const seriesIsland = readAdmin(join("effects", "series-island.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(effectsPage))
  problems.push("admin/effects/page.tsx must be force-dynamic (server-only env)");
if (/NEXT_PUBLIC/.test(effectsPage) || /https?:\/\//.test(effectsPage))
  problems.push("admin/effects/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (effectsPage.includes(forbidden))
    problems.push(`admin/effects/page.tsx is read-only; must not contain ${forbidden}`);
}
for (const token of ["getEffectOrphans", "OrphanTableIsland", "SeriesQueryIsland"]) {
  if (!effectsPage.includes(token))
    problems.push(`admin/effects/page.tsx must use ${token}`);
}
if (!/^"use server"/m.test(effectsActions))
  problems.push("admin/effects/actions.ts must be a Server Action module");
for (const token of [
  "claimEffectAction",
  "batchClaimEffectsAction",
  "unclaimEffectAction",
  "queryEffectSeriesAction",
  "CURRENT_ADMIN_ACTOR_ID",
  "missing_role",
  "unconfigured",
  "ADMIN_ROLE_LIST",
  "claimEffect",
  "batchClaimEffects",
  "unclaimEffect",
  "getEffectSeries",
]) {
  if (!effectsActions.includes(token))
    problems.push(`admin/effects/actions.ts must contain ${token}`);
}
for (const status of [403, 404, 409, 422]) {
  if (!effectsActions.includes(String(status)))
    problems.push(`effects actions must map failure status ${status}`);
}
for (const [name, text] of [
  ["orphan-table-island", orphanIsland],
  ["series-island", seriesIsland],
]) {
  if (!/^"use client"/m.test(text)) problems.push(`${name} must be a client island`);
  if (text.includes("@/lib/api") || /\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must call only the Server Action, never the API directly`);
  if (!text.includes("router.refresh"))
    problems.push(`${name} must refresh the RSC view after success`);
}
if (!orphanIsland.includes("batchClaimEffectsAction"))
  problems.push("orphan island must expose batch claim via batchClaimEffectsAction");
if (!seriesIsland.includes("window.confirm"))
  problems.push("series island must confirm the unclaim (revoke) action");
for (const token of [
  "getEffectOrphans",
  "getEffectSeries",
  "claimEffect",
  "batchClaimEffects",
  "unclaimEffect",
  "customerBackfillEffects",
  "/api/admin/effects/orphans",
  "/api/admin/effects/claims/batch",
  "/api/admin/effects/claims/unclaim",
  "/api/effects/backfill",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

const effectsRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "effects", "router.py"),
  "utf8",
);
for (const route of [
  '"/api/effect-callback"',
  '"/api/effects/backfill"',
  '"/api/admin/effects/claims"',
  '"/api/admin/effects/claims/batch"',
  '"/api/admin/effects/claims/unclaim"',
  '"/api/admin/effects/orphans"',
]) {
  if (!effectsRouter.includes(route))
    problems.push(`backend effects router must register ${route}`);
}

// Q164：两驾驶舱日期范围筛选器（共享 RSC 组件 + URL searchParams 透传）。
const dateFilterComp = readAdmin(join("_components", "DateRangeFilter.tsx"));
for (const token of [
  "data-date-range-filter",
  'name="date_from"',
  'name="date_to"',
  'type="date"',
  'getTranslations("admin.dateFilter")',
  'defaultFromIso',
  'defaultToIso',
]) {
  if (!dateFilterComp.includes(token))
    problems.push(`_components/DateRangeFilter.tsx must contain ${token}`);
}
if (/^"use client"/m.test(dateFilterComp))
  problems.push("DateRangeFilter must stay a server component (no client state)");
for (const [name, text] of [
  ["token-cost/page.tsx", tokenPage],
  ["review-workload/page.tsx", workloadPage],
]) {
  if (!text.includes("<DateRangeFilter"))
    problems.push(`${name} must render the shared <DateRangeFilter>`);
  if (!/searchParams/.test(text))
    problems.push(`${name} must read URL searchParams for date_from/date_to`);
  if (!/sp\.date_from/.test(text) || !/sp\.date_to/.test(text))
    problems.push(`${name} must read sp.date_from / sp.date_to`);
}
for (const token of ["date_from", "date_to", "DashboardWindowOpts"]) {
  if (!apiText.includes(token))
    problems.push(`lib/api.ts must pass dashboard date window param: ${token}`);
}

// Q167：入站 Agent Key 治理页（消费 Q88 三端点；platform_admin 写闸）。
const akDir = join(adminDir, "agent-keys");
const akPage = readAdmin(join("agent-keys", "page.tsx"));
const akActions = readAdmin(join("agent-keys", "actions.ts"));
const akIssue = readAdmin(join("agent-keys", "issue-island.tsx"));
const akRevoke = readAdmin(join("agent-keys", "revoke-island.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(akPage))
  problems.push("agent-keys/page.tsx must be force-dynamic (server-only env)");
if (/NEXT_PUBLIC/.test(akPage) || /https?:\/\//.test(akPage))
  problems.push("agent-keys/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (akPage.includes(forbidden))
    problems.push(`agent-keys/page.tsx is read-only RSC; must not contain ${forbidden}`);
}
for (const token of ["listAgentKeys", "IssueKeyIsland", "RevokeKeyButton", "agent-keys"]) {
  if (!akPage.includes(token))
    problems.push(`agent-keys page must use ${token}`);
}
if (!/^"use server"/m.test(akActions))
  problems.push("agent-keys/actions.ts must be a Server Action module");
for (const token of [
  "issueAgentKeyAction",
  "revokeAgentKeyAction",
  "CURRENT_ADMIN_ACTOR_ID",
  "platform_admin",
  "unconfigured",
  "missing_role",
  "issueAgentKey",
  "revokeAgentKey",
]) {
  if (!akActions.includes(token))
    problems.push(`agent-keys actions must contain ${token}`);
}
for (const status of [403, 404, 409, 422]) {
  if (!akActions.includes(String(status)))
    problems.push(`agent-keys actions must map failure status ${status}`);
}
for (const [name, text] of [["issue-island", akIssue], ["revoke-island", akRevoke]]) {
  if (!/^"use client"/m.test(text))
    problems.push(`${name} must be a client island`);
  if (text.includes("@/lib/api") || /\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must call only the Server Action, never the API directly`);
  if (!text.includes("router.refresh"))
    problems.push(`${name} must refresh the RSC view after success`);
}
if (!akIssue.includes('data-testid="issued-secret"'))
  problems.push("issue island must show the one-time secret in a marked region");
if (!akRevoke.includes("window.confirm"))
  problems.push("revoke island must confirm the terminal revoke action");
if (!getKey(messages, "admin.agentKeys.revokeConfirm")?.includes("{name}"))
  problems.push("admin.agentKeys.revokeConfirm must contain the {name} placeholder");
const apiKeysRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "api_keys", "router.py"), "utf8",
);
for (const route of [
  '"/api/admin/agent-keys"',
  '"/api/admin/agent-keys/{key_id}/revoke"',
]) {
  if (!apiKeysRouter.includes(route))
    problems.push(`backend api_keys router must register ${route}`);
}
const apiKeysService = readFileSync(
  join(repoRoot, "backend", "app", "core", "api_keys", "service.py"), "utf8",
);
for (const token of ["issue_key", "revoke_key", "PLATFORM_ADMIN"]) {
  if (!apiKeysService.includes(token))
    problems.push(`api_keys service must keep platform_admin gate on ${token}`);
}

// Q178：内部运营个人访问令牌（PAT）治理页（甲案第一切片；platform_admin 写闸）。
const skPage = readAdmin(join("staff-keys", "page.tsx"));
const skActions = readAdmin(join("staff-keys", "actions.ts"));
const skIssue = readAdmin(join("staff-keys", "issue-staff-island.tsx"));
const skRevoke = readAdmin(join("staff-keys", "revoke-staff-island.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(skPage))
  problems.push("staff-keys/page.tsx must be force-dynamic (server-only env)");
if (/NEXT_PUBLIC/.test(skPage) || /https?:\/\//.test(skPage))
  problems.push("staff-keys/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (skPage.includes(forbidden))
    problems.push(`staff-keys/page.tsx is read-only RSC; must not contain ${forbidden}`);
}
for (const token of ["listStaffKeys", "IssueStaffKeyIsland", "RevokeStaffKeyButton", "staff-keys"]) {
  if (!skPage.includes(token))
    problems.push(`staff-keys page must use ${token}`);
}
if (!/^"use server"/m.test(skActions))
  problems.push("staff-keys/actions.ts must be a Server Action module");
for (const token of [
  "issueStaffKeyAction",
  "revokeStaffKeyAction",
  "STAFF_ROLE_CODES",
  "CURRENT_ADMIN_ACTOR_ID",
  "platform_admin",
  "unconfigured",
  "missing_role",
  "issueStaffKey",
  "revokeStaffKey",
]) {
  if (!skActions.includes(token))
    problems.push(`staff-keys actions must contain ${token}`);
}
for (const status of [400, 401, 403, 404, 409, 422]) {
  if (!skActions.includes(String(status)))
    problems.push(`staff-keys actions must map failure status ${status}`);
}
for (const [name, text] of [["issue-staff-island", skIssue], ["revoke-staff-island", skRevoke]]) {
  if (!/^"use client"/m.test(text))
    problems.push(`${name} must be a client island`);
  if (text.includes("@/lib/api") || /\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must call only the Server Action, never the API directly`);
  if (!text.includes("router.refresh"))
    problems.push(`${name} must refresh the RSC view after success`);
}
if (!skIssue.includes('data-testid="issued-staff-secret"'))
  problems.push("staff issue island must show the one-time secret in a marked region");
if (!skRevoke.includes("window.confirm"))
  problems.push("staff revoke island must confirm the terminal revoke action");
if (!getKey(messages, "admin.staffKeys.revokeConfirm")?.includes("{name}"))
  problems.push("admin.staffKeys.revokeConfirm must contain the {name} placeholder");
// 角色码为系统标识，必须在 actions 以常量原样提供、不得翻译进消息表。
if (!/operations[\s\S]*platform_admin[\s\S]*product_reviewer[\s\S]*dictionary_admin[\s\S]*internal_compliance/.test(skActions))
  problems.push("staff-keys actions must list the five internal role codes raw");
const staffRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "staff_auth", "router.py"), "utf8",
);
for (const route of ['"/api/admin/staff-keys"', "/revoke", '"/api/auth/me"']) {
  if (!staffRouter.includes(route))
    problems.push(`backend staff_auth router must register ${route}`);
}
const staffService = readFileSync(
  join(repoRoot, "backend", "app", "core", "staff_auth", "service.py"), "utf8",
);
for (const token of ["loom_staff_", "INTERNAL_STAFF_ROLES", "PLATFORM_ADMIN"]) {
  if (!staffService.includes(token))
    problems.push(`staff_auth service must keep ${token} (staff token prefix / internal roles / admin gate)`);
}

// Q178：内部运营登录录入页（粘贴 PAT → /api/auth/me 自检 → httpOnly cookie）。
const loginPage = readAdmin(join("login", "page.tsx"));
const loginActions = readAdmin(join("login", "actions.ts"));
const loginIsland = readAdmin(join("login", "login-island.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(loginPage))
  problems.push("login/page.tsx must be force-dynamic (reads the auth cookie)");
if (/NEXT_PUBLIC/.test(loginPage) || /https?:\/\//.test(loginPage))
  problems.push("login/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const token of ["LoginIsland", "getStaffMe", "getStaffToken"]) {
  if (!loginPage.includes(token))
    problems.push(`login page must use ${token}`);
}
if (!/^"use server"/m.test(loginActions))
  problems.push("login/actions.ts must be a Server Action module");
for (const token of [
  "loginStaffAction",
  "logoutStaffAction",
  "getStaffMe",
  "setStaffToken",
  "clearStaffToken",
]) {
  if (!loginActions.includes(token))
    problems.push(`login actions must contain ${token}`);
}
if (!/^"use client"/m.test(loginIsland))
  problems.push("login-island must be a client island");
if (loginIsland.includes("@/lib/api") || /\bfetch\s*\(/.test(loginIsland) || /https?:\/\//.test(loginIsland))
  problems.push("login island must call only the Server Action, never the API directly");
for (const token of ["loginStaffAction", "logoutStaffAction"]) {
  if (!loginIsland.includes(token))
    problems.push(`login island must expose ${token}`);
}
if (!/loom_staff_/.test(getKey(messages, "admin.staffAuth.tokenPlaceholder") ?? ""))
  problems.push("admin.staffAuth.tokenPlaceholder must hint the loom_staff_ prefix");

// Q168：中台导出任务管理页（消费 Q132/Q137 jobs；创建/下载经 Server Action）。
const exPage = readAdmin(join("exports", "page.tsx"));
const exActions = readAdmin(join("exports", "actions.ts"));
const exCreate = readAdmin(join("exports", "create-island.tsx"));
const exDownload = readAdmin(join("exports", "download-island.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(exPage))
  problems.push("exports/page.tsx must be force-dynamic (server-only env)");
if (/NEXT_PUBLIC/.test(exPage) || /https?:\/\//.test(exPage))
  problems.push("exports/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (exPage.includes(forbidden))
    problems.push(`exports/page.tsx is read-only RSC; must not contain ${forbidden}`);
}
for (const token of [
  "listExportJobs",
  "CreateExportIsland",
  "DownloadExportButton",
  'name="tenant_id"',
  'data-testid="exports-tenant-filter"',
]) {
  if (!exPage.includes(token))
    problems.push(`exports page must contain ${token}`);
}
if (!/^"use server"/m.test(exActions))
  problems.push("exports/actions.ts must be a Server Action module");
for (const token of [
  "createExportJobAction",
  "downloadExportJobAction",
  "CURRENT_ADMIN_ACTOR_ID",
  "unconfigured",
  "createExportJob",
  "downloadExportJob",
]) {
  if (!exActions.includes(token))
    problems.push(`exports actions must contain ${token}`);
}
for (const status of [403, 404, 409, 422]) {
  if (!exActions.includes(String(status)))
    problems.push(`exports actions must map failure status ${status}`);
}
for (const [name, text] of [["create-island", exCreate], ["download-island", exDownload]]) {
  if (!/^"use client"/m.test(text))
    problems.push(`${name} must be a client island`);
  if (text.includes("@/lib/api") || /\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${name} must call only the Server Action, never the API directly`);
  if (!text.includes("router.refresh"))
    problems.push(`${name} must refresh the RSC view after success`);
}
if (!exDownload.includes("Blob") || !exDownload.includes("createObjectURL"))
  problems.push("download island must save the text payload via a Blob object URL (no bare API URL)");
const exportsRouter = readFileSync(
  join(repoRoot, "backend", "app", "core", "exports", "router.py"), "utf8",
);
if (!exportsRouter.includes('prefix="/api/exports"'))
  problems.push("backend exports router must mount at /api/exports");
for (const route of ['"/jobs"', '"/jobs/{job_id}"', '"/jobs/{job_id}/download"']) {
  if (!exportsRouter.includes(route))
    problems.push(`backend exports router must register ${route}`);
}

// Q177：D3.5 白名单组装引擎运营只读首片（跨租户 FCW 列表 + 六层原料包按需展开）。
const fcwPage = readAdmin(join("fcw", "page.tsx"));
const fcwActions = readAdmin(join("fcw", "actions.ts"));
const fcwIsland = readAdmin(join("fcw", "material-island.tsx"));
const fcwTable = readAdmin(join("fcw", "fcw-table.tsx"));

if (!/export const dynamic = "force-dynamic"/.test(fcwPage))
  problems.push("fcw/page.tsx must be force-dynamic (server-only env)");
if (/NEXT_PUBLIC/.test(fcwPage) || /https?:\/\//.test(fcwPage))
  problems.push("fcw/page.tsx must not read NEXT_PUBLIC_* or hardcode URLs");
for (const forbidden of ["method:", "POST", "PATCH", "DELETE"]) {
  if (fcwPage.includes(forbidden))
    problems.push(`fcw/page.tsx is read-only RSC; must not contain ${forbidden}`);
}
for (const token of ["listAdminFcw", "FcwTable", 'name="tenant_id"', "data-testid"]) {
  if (!fcwPage.includes(token))
    problems.push(`fcw/page.tsx must contain ${token}`);
}
if (!/^"use server"/m.test(fcwActions))
  problems.push("fcw/actions.ts must be a Server Action module");
for (const token of [
  "getFcwMaterialAction",
  "CURRENT_ADMIN_ACTOR_ID",
  "unconfigured",
  "missing_role",
  "getAdminFcwMaterial",
]) {
  if (!fcwActions.includes(token))
    problems.push(`fcw/actions.ts must contain ${token}`);
}
for (const status of [403, 404, 409, 422]) {
  if (!fcwActions.includes(String(status)))
    problems.push(`getFcwMaterialAction must map failure status ${status}`);
}
if (!/^"use client"/m.test(fcwIsland))
  problems.push("fcw material island must be a client island");
if (
  fcwIsland.includes("@/lib/api") ||
  /\bfetch\s*\(/.test(fcwIsland) ||
  /https?:\/\//.test(fcwIsland)
)
  problems.push("fcw material island must call only the Server Action, never the API directly");
if (fcwIsland.includes("router.refresh"))
  problems.push("fcw material island is read-only and must not refresh the router");
for (const token of ["getFcwMaterialAction", "data-testid", "JSON.stringify"]) {
  if (!fcwIsland.includes(token))
    problems.push(`fcw material island must contain ${token}`);
}
// Q186：六层原料包一键存盘（与 Q168 导出下载同范式，Blob + object URL，不经裸 URL）。
if (!fcwIsland.includes("Blob") || !fcwIsland.includes("createObjectURL"))
  problems.push("fcw material island must save the pack via a Blob object URL");
for (const token of ["downloadMaterial", "revokeObjectURL"]) {
  if (!fcwIsland.includes(token))
    problems.push(`fcw material island download must contain ${token}`);
}
// Q186：D3.5 余项 final_id 单条/多选复制。表格下沉 client 岛只为承载本页选中态，
// 仍不得直连后端、不得写数据、不得刷新路由。
if (!/^"use client"/m.test(fcwTable))
  problems.push("fcw-table.tsx must be a client island");
if (
  /\bfetch\s*\(/.test(fcwTable) ||
  /https?:\/\//.test(fcwTable) ||
  /^import\s+(?!type\b).*"@\/lib\/api"/m.test(fcwTable)
)
  problems.push("fcw-table.tsx must not call the API directly (type-only import allowed)");
if (fcwTable.includes("router.refresh"))
  problems.push("fcw-table.tsx is read-only and must not refresh the router");
for (const token of [
  "navigator.clipboard.writeText",
  'data-testid="fcw-copy-id"',
  'data-testid="fcw-bulk-copy"',
  'data-testid="fcw-select-all"',
  "MaterialIsland",
  'import type { FcwListItem }',
]) {
  if (!fcwTable.includes(token))
    problems.push(`fcw-table.tsx must contain ${token}`);
}
const fcwRouter = readFileSync(
  join(repoRoot, "backend", "app", "final", "final_whitelist", "router.py"),
  "utf8",
);
for (const route of ['"/api/admin/fcw"', '"/api/admin/fcw/{final_id}/material"']) {
  if (!fcwRouter.includes(route))
    problems.push(`backend fcw router must register ${route}`);
}
for (const token of ["require_fcw_admin_view", "OPERATIONS", "PLATFORM_ADMIN"]) {
  if (!fcwRouter.includes(token))
    problems.push(`backend fcw admin endpoints must gate via ${token}`);
}

if (problems.length > 0) {
  console.error(`check-admin: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-admin: admin layout, dashboards, env identity and shell isolation consistent");

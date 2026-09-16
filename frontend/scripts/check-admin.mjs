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
  "/api/review-workbench/candidates",
  "/api/review-workbench/batch-approve",
  "/api/skill-candidates/",
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

if (problems.length > 0) {
  console.error(`check-admin: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-admin: admin layout, dashboards, env identity and shell isolation consistent");

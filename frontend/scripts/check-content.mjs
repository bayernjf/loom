#!/usr/bin/env node
/**
 * Q122：客户「内容生产与发布」切片一致性（零依赖）。
 * - content.* 消息键齐备（含六态 content.status.*）；
 * - 列表页 / 详情页 / Server Action / 两个 client 岛 / 样式文件齐备；
 * - 占位页必须移除（nav content 已转 v1，不得再渲染 MenuPlaceholder）；
 * - lib/api.ts 只允许服务端引用：禁 NEXT_PUBLIC；
 * - Server Action 必须 "use server"；client 岛必须 "use client"、禁引 @/lib/api、
 *   禁裸 fetch/URL，成功后 router.refresh；
 * - nav.ts 中 content 必须为 v1；
 * - 后端防漂移：客户列表 / 详情 / 人工编辑路由与 manual_resubmit 状态边必须存在，
 *   生成端点 operations 闸不得外放给客户页。
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const shell = join(root, "app", "[locale]", "(shell)");
const backend = join(root, "..", "backend");

const messages = JSON.parse(
  readFileSync(join(root, "messages", "zh-CN.json"), "utf8"),
);

const requiredKeys = [
  "content.title",
  "content.pageNote",
  "content.unconfigured",
  "content.empty",
  "content.columnWhitelist",
  "content.columnPlatform",
  "content.columnLanguage",
  "content.columnStatus",
  "content.columnQuality",
  "content.columnReview",
  "content.qualityScore",
  "content.qualityAdvisoryNote",
  "content.qualityAdvisory",
  "content.qualityMissing",
  "content.flagBlocked",
  "content.flagDowngrade",
  "content.flagSemantic",
  "content.flagClean",
  "content.fieldStatus",
  "content.fieldPlatform",
  "content.fieldGoal",
  "content.fieldLanguage",
  "content.fieldCountry",
  "content.fieldRegenCount",
  "content.fieldCreatedAt",
  "content.bodyTitle",
  "content.bodyEmpty",
  "content.qualityTitle",
  "content.reviewTitle",
  "content.bansTitle",
  "content.bansClean",
  "content.downgradesTitle",
  "content.semanticTitle",
  "content.semanticClean",
  "content.semanticUnavailable",
  "content.rejectedReasonTitle",
  "content.decisionTitle",
  "content.blockRequiredNote",
  "content.rejectReasonLabel",
  "content.rejectReasonPlaceholder",
  "content.approve",
  "content.reject",
  "content.revise",
  "content.actionSuccess",
  "content.editTitle",
  "content.editNote",
  "content.submitEdit",
  "content.editSuccess",
  "content.readyNote",
  "content.publishedLinkTitle",
  "content.publishedLinkMissing",
  "content.discardedReasonTitle",
  "content.backToList",
  "content.actorUnconfigured",
  "content.backfillTitle",
  "content.backfillNote",
  "content.backfillPostLabel",
  "content.backfillPostPlaceholder",
  "content.backfillPostRequired",
  "content.backfillCapturedLabel",
  "content.backfillCapturedRequired",
  "content.backfillMetricsLabel",
  "content.backfillMetricAbsent",
  "content.backfillMetricInteger",
  "content.backfillReadRateRange",
  "content.backfillSubmit",
  "content.backfillSuccess",
  "content.backfillBatchTitle",
  "content.backfillBatchNote",
  "content.backfillBatchFormat",
  "content.backfillBatchFile",
  "content.backfillBatchPlaceholder",
  "content.backfillBatchParsed",
  "content.backfillBatchErrors",
  "content.backfillBatchLine",
  "content.backfillBatchHeaderMissing",
  "content.backfillBatchTooMany",
  "content.backfillBatchSubmit",
  "content.backfillBatchSuccess",
  "content.backfillBatchPreviewMore",
  "content.backfillMetric.plays",
  "content.backfillMetric.likes",
  "content.backfillMetric.comments",
  "content.backfillMetric.shares",
  "content.backfillMetric.inquiries",
  "content.backfillMetric.conversions",
  "content.backfillMetric.read_rate",
  "content.status.draft",
  "content.status.generating",
  "content.status.review",
  "content.status.ready_for_publish",
  "content.status.rejected",
  "content.status.revising",
  "content.status.discarded",
  "error.403",
  "error.404",
  "error.409",
  "error.422",
  "error.unknown",
];

const requiredFiles = [
  "lib/api.ts",
  "app/[locale]/(shell)/content/page.tsx",
  "app/[locale]/(shell)/content/[contentId]/page.tsx",
  "app/[locale]/(shell)/content/actions.ts",
  "app/[locale]/(shell)/content/decision-island.tsx",
  "app/[locale]/(shell)/content/body-edit-island.tsx",
  "app/[locale]/(shell)/content/backfill-island.tsx",
  "app/[locale]/(shell)/content/backfill-batch-island.tsx",
  "app/[locale]/(shell)/content/content.module.css",
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

// 计数/分数句式必须带占位。
for (const [key, token] of [
  ["content.flagBlocked", "{count}"],
  ["content.flagDowngrade", "{count}"],
  ["content.flagSemantic", "{count}"],
  ["content.bansTitle", "{count}"],
  ["content.downgradesTitle", "{count}"],
  ["content.qualityScore", "{score}"],
  ["content.backfillSuccess", "{count}"],
  ["content.backfillBatchFormat", "{max}"],
  ["content.backfillBatchParsed", "{count}"],
  ["content.backfillBatchErrors", "{count}"],
  ["content.backfillBatchLine", "{line}"],
  ["content.backfillBatchLine", "{message}"],
  ["content.backfillBatchTooMany", "{max}"],
  ["content.backfillBatchTooMany", "{count}"],
  ["content.backfillBatchSuccess", "{count}"],
  ["content.backfillBatchPreviewMore", "{count}"],
]) {
  if (!getKey(messages, key)?.includes(token))
    problems.push(`${key} must contain the ${token} placeholder`);
}

for (const rel of requiredFiles) {
  if (!existsSync(join(root, rel))) problems.push(`missing file: ${rel}`);
}

const apiText = readFileSync(join(root, "lib", "api.ts"), "utf8");
if (/process\.env\.NEXT_PUBLIC/.test(apiText))
  problems.push("lib/api.ts must not read NEXT_PUBLIC_* env (would leak into browser bundle)");
for (const token of [
  "listContent",
  "getContent",
  "approveContent",
  "rejectContent",
  "reviseContent",
  "editContentBody",
  "customerBackfillEffects",
  "/api/content",
  "/api/effects/backfill",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must export/use ${token}`);
}
// 客户页不得调用 operations 闸的生成 / 重生成端点。
for (const banned of ["/generate", "/regenerate"]) {
  if (apiText.includes(`/api/content/${banned}`) || apiText.includes(banned))
    problems.push(`customer api layer must not expose the operations ${banned} endpoint`);
}

const navText = readFileSync(join(root, "app", "[locale]", "nav.ts"), "utf8");
if (!/\{\s*href:\s*"\/content"[^}]*phase:\s*"v1"/.test(navText))
  problems.push('nav.ts must register /content as phase "v1" (Q122)');

const listPageText = readFileSync(join(shell, "content", "page.tsx"), "utf8");
if (listPageText.includes("MenuPlaceholder"))
  problems.push("content/page.tsx must no longer render the V2 MenuPlaceholder");
if (!listPageText.includes('getTranslations("content.status")'))
  problems.push("content/page.tsx must render status via content.status messages");
if (!listPageText.includes("force-dynamic"))
  problems.push("content/page.tsx must be force-dynamic");

const detailPageText = readFileSync(
  join(shell, "content", "[contentId]", "page.tsx"), "utf8",
);
if (!detailPageText.includes("DecisionIsland"))
  problems.push("detail page must mount DecisionIsland");
if (!detailPageText.includes("BodyEditIsland"))
  problems.push("detail page must mount BodyEditIsland");
if (!detailPageText.includes("BackfillIsland"))
  problems.push("detail page must mount BackfillIsland (Q131 customer backfill)");
if (!detailPageText.includes("BatchBackfillIsland"))
  problems.push("detail page must mount BatchBackfillIsland (Q136 CSV batch backfill)");
if (!detailPageText.includes('getTranslations("content.status")'))
  problems.push("detail page must load the content.status namespace");

const actionsText = readFileSync(join(shell, "content", "actions.ts"), "utf8");
if (!actionsText.startsWith('"use server"'))
  problems.push('content/actions.ts must start with "use server"');
// Q124/Q125：作废与发布回填是 operations 写口，客户侧一律不得引用。
for (const banned of ["adminDiscardContent", "setPublishInfo", "/discard", "/publish-info"]) {
  if (actionsText.includes(banned))
    problems.push(`customer content actions must not expose operations endpoint token: ${banned}`);
}
for (const token of [
  "decideContentAction",
  "saveContentBodyAction",
  "backfillEffectAction",
  "batchBackfillEffectsAction",
  "approveContent",
  "rejectContent",
  "reviseContent",
  "editContentBody",
  "customerBackfillEffects",
  "CURRENT_TENANT_ID",
]) {
  if (!actionsText.includes(token))
    problems.push(`content/actions.ts must use ${token}`);
}

// client 岛纪律：禁直连服务端层 / 裸 URL，必须经 Server Action 并 router.refresh。
for (const rel of ["content/decision-island.tsx", "content/body-edit-island.tsx", "content/backfill-island.tsx", "content/backfill-batch-island.tsx"]) {
  const text = readFileSync(join(shell, rel), "utf8");
  if (!text.startsWith('"use client"')) problems.push(`${rel} must start with "use client"`);
  if (text.includes("@/lib/api")) problems.push(`${rel} must not import @/lib/api (server-only)`);
  if (/\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${rel} must not call fetch/embed URLs directly; use server actions`);
  if (!text.includes("router.refresh"))
    problems.push(`${rel} must call router.refresh after a successful action`);
}

// 后端防漂移守卫。
const routerText = readFileSync(
  join(backend, "app", "content", "router.py"), "utf8",
);
for (const route of [
  '"/api/content"',
  '"/api/content/languages"',
  '"/api/content/{content_id}"',
  '"/api/content/{content_id}/body"',
]) {
  if (!routerText.includes(route))
    problems.push(`backend content router must keep ${route}`);
}
// B3：静态 /languages 必须先于 {content_id} 注册，否则被路径参数吞掉。
const languagesAt = routerText.indexOf('"/api/content/languages"');
const contentIdAt = routerText.indexOf('"/api/content/{content_id}"');
if (languagesAt === -1 || contentIdAt === -1 || languagesAt > contentIdAt)
  problems.push("GET /api/content/languages must be registered before /api/content/{content_id}");
// Q124/Q125：运营作废与发布回填路由必须存在。
for (const route of [
  '"/api/content/{content_id}/discard"',
  '"/api/admin/content/{content_id}/publish-info"',
  '"/api/admin/content/ready-to-publish"',
  '"/api/admin/content/needs-attention"',
]) {
  if (!routerText.includes(route))
    problems.push(`backend content router must keep ${route}`);
}
const smText = readFileSync(join(backend, "app", "content", "statemachine.py"), "utf8");
for (const token of ["manual_resubmit", "CONTENT_REVISING", "CONTENT_REVIEW", "EVENT_DISCARD", "CONTENT_DISCARDED"]) {
  if (!smText.includes(token))
    problems.push(`content statemachine must keep ${token}`);
}
// Q124：客户列表必须能渲染 discarded 终态 chip。
const contentCss = readFileSync(join(shell, "content", "content.module.css"), "utf8");
if (!contentCss.includes(".toneDiscarded"))
  problems.push("content.module.css must define toneDiscarded for the discarded terminal state");
if (!listPageText.includes("toneDiscarded"))
  problems.push("content list page must map discarded status to toneDiscarded");
// 生成 / 重生成 operations 闸不得被移除。
const serviceText = readFileSync(join(backend, "app", "content", "service.py"), "utf8");
if (!serviceText.includes("require_any_role(body.actor, OPERATIONS)"))
  problems.push("generate_content must keep the OPERATIONS role gate");
if (!serviceText.includes("require_any_role(actor, OPERATIONS)"))
  problems.push("regenerate_content must keep the OPERATIONS role gate");

// Q128/Q131：客户效果回填走无 Agent Key 的客户专用通道，且绝不产生孤儿。
const backfillIsland = readFileSync(
  join(shell, "content", "backfill-island.tsx"), "utf8",
);
for (const token of ["datetime-local", "toISOString", "backfillEffectAction"]) {
  if (!backfillIsland.includes(token))
    problems.push(`backfill island must contain ${token} (tz-aware capture time)`);
}
// Q136：批量岛纯前端 CSV 解析（文件载入 + 行级校验），整批仍走客户通道、转 UTC、刷新页面。
const batchIsland = readFileSync(
  join(shell, "content", "backfill-batch-island.tsx"), "utf8",
);
for (const token of [
  "batchBackfillEffectsAction",
  "toISOString",
  "FileReader",
  "readAsText",
  "router.refresh",
  "all-or-nothing",
]) {
  if (!batchIsland.includes(token))
    problems.push(`batch backfill island must contain ${token} (Q136 CSV import)`);
}
if (/\bfetch\s*\(/.test(batchIsland) || /https?:\/\//.test(batchIsland) || batchIsland.includes("@/lib/api"))
  problems.push("batch backfill island must use server actions, not direct fetch/api imports");
const effectsRouterText = readFileSync(
  join(backend, "app", "core", "effects", "router.py"), "utf8",
);
if (!effectsRouterText.includes('"/api/effects/backfill"'))
  problems.push("backend effects router must keep POST /api/effects/backfill (customer channel)");

if (problems.length > 0) {
  console.error(`check-content: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-content: messages, pages, islands, actions and backend routes consistent");

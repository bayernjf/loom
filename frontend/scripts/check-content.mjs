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
  "content.backToList",
  "content.actorUnconfigured",
  "content.status.draft",
  "content.status.generating",
  "content.status.review",
  "content.status.ready_for_publish",
  "content.status.rejected",
  "content.status.revising",
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
  "/api/content",
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
if (!detailPageText.includes('getTranslations("content.status")'))
  problems.push("detail page must load the content.status namespace");

const actionsText = readFileSync(join(shell, "content", "actions.ts"), "utf8");
if (!actionsText.startsWith('"use server"'))
  problems.push('content/actions.ts must start with "use server"');
for (const token of [
  "decideContentAction",
  "saveContentBodyAction",
  "approveContent",
  "rejectContent",
  "reviseContent",
  "editContentBody",
]) {
  if (!actionsText.includes(token))
    problems.push(`content/actions.ts must use ${token}`);
}

// client 岛纪律：禁直连服务端层 / 裸 URL，必须经 Server Action 并 router.refresh。
for (const rel of ["content/decision-island.tsx", "content/body-edit-island.tsx"]) {
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
  '"/api/content/{content_id}"',
  '"/api/content/{content_id}/body"',
]) {
  if (!routerText.includes(route))
    problems.push(`backend content router must keep ${route}`);
}
const smText = readFileSync(join(backend, "app", "content", "statemachine.py"), "utf8");
for (const token of ["manual_resubmit", "CONTENT_REVISING", "CONTENT_REVIEW"]) {
  if (!smText.includes(token))
    problems.push(`content statemachine must keep ${token}`);
}
// 生成 / 重生成 operations 闸不得被移除。
const serviceText = readFileSync(join(backend, "app", "content", "service.py"), "utf8");
if (!serviceText.includes("require_any_role(body.actor, OPERATIONS)"))
  problems.push("generate_content must keep the OPERATIONS role gate");
if (!serviceText.includes("require_any_role(actor, OPERATIONS)"))
  problems.push("regenerate_content must keep the OPERATIONS role gate");

if (problems.length > 0) {
  console.error(`check-content: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-content: messages, pages, islands, actions and backend routes consistent");

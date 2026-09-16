#!/usr/bin/env node
/**
 * Q101：客户「合规风控」功能页切片一致性（零依赖）。
 * - compliance.* 消息键齐备，CCR 四态（ccr_rules.REPORT_*）与法审三态文案键齐备；
 * - 页面/样式与服务端访问层 getComplianceOverview 齐备，页面必须 force-dynamic；
 * - 只读：页面不得直连后端（无 NEXT_PUBLIC、无写操作调用）；
 * - 后端聚合路由 GET /api/compliance/overview 必须存在且 tenant_id 为必填查询参数；
 * - 产品名走工程临时键 profile.product_name（G2 fid 基线回填后替换，挂账 Q98）。
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(here, "..");
const repoRoot = join(frontendRoot, "..");
const shell = join(frontendRoot, "app", "[locale]", "(shell)");

const messages = JSON.parse(
  readFileSync(join(frontendRoot, "messages", "zh-CN.json"), "utf8"),
);

const requiredKeys = [
  "compliance.intro",
  "compliance.empty",
  "compliance.unconfigured",
  "compliance.version",
  "compliance.ccrTitle",
  "compliance.lawTitle",
  "compliance.noReport",
  "compliance.noLawReview",
  "compliance.blockRequired",
  "compliance.latestAt",
  "compliance.marketBase",
  "compliance.market",
  "compliance.bans",
  "compliance.downgradeArrow",
  "compliance.decidedAt",
  "compliance.lawDomain",
  "compliance.lawStatusLabel",
  "compliance.lawConclusion",
  "compliance.detailTitle",
  ...["clean", "downgrade_pending", "approved", "blocked"].map(
    (code) => `compliance.ccr.${code}`,
  ),
  ...["pending", "approved", "rejected"].map(
    (code) => `compliance.law.${code}`,
  ),
];

const requiredFiles = [
  ["app/[locale]/(shell)/compliance/page.tsx"],
  ["app/[locale]/(shell)/compliance/compliance.module.css"],
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

for (const [rel] of requiredFiles) {
  if (!existsSync(join(frontendRoot, rel))) problems.push(`missing file: ${rel}`);
}

const pageText = readFileSync(join(shell, "compliance", "page.tsx"), "utf8");
if (!/export const dynamic = "force-dynamic"/.test(pageText))
  problems.push("compliance/page.tsx must be force-dynamic (server-only env)");
if (!/\bgetComplianceOverview\b/.test(pageText))
  problems.push("compliance/page.tsx must fetch via getComplianceOverview");
if (/NEXT_PUBLIC/.test(pageText))
  problems.push("compliance/page.tsx must not read NEXT_PUBLIC_* env (no browser direct API)");
for (const forbidden of ["/ccr/run", "approve-downgrades", "/decision", "cp-law-domains"]) {
  if (pageText.includes(forbidden))
    problems.push(`compliance page is read-only; must not call write/admin surface: ${forbidden}`);
}

const cssText = readFileSync(
  join(shell, "compliance", "compliance.module.css"),
  "utf8",
);
for (const cls of ["chip", "toneDanger", "toneWarning", "toneSuccess", "toneInfo", "blockBadge"]) {
  if (!cssText.includes(`.${cls}`))
    problems.push(`compliance.module.css must define .${cls}`);
}

const apiText = readFileSync(join(frontendRoot, "lib", "api.ts"), "utf8");
for (const token of [
  "getComplianceOverview",
  "ComplianceOverview",
  "ComplianceOverviewItem",
  "/api/compliance/overview",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

const routerText = readFileSync(
  join(repoRoot, "backend", "app", "decision", "compliance_center", "router.py"),
  "utf8",
);
if (!routerText.includes('"/api/compliance/overview"'))
  problems.push('backend router must register GET "/api/compliance/overview"');
if (!/tenant_id:\s*str\s*=\s*Query\(min_length=1\)/.test(routerText))
  problems.push("overview endpoint must require tenant_id query (min_length=1)");

if (problems.length > 0) {
  console.error(`check-compliance: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-compliance: messages, read-only wiring and overview route consistent");

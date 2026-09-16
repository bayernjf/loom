#!/usr/bin/env node
/**
 * Q99：工作台功能页切片一致性（零依赖）。
 * - workbench.* 与 intake.status.*（docs/13 §1.1 十五态）消息键齐备；
 * - 工作台页面/样式与服务端访问层函数齐备，页面必须 force-dynamic；
 * - 五张 V2 指标卡（D5 原文：今日生成/发布/互动/趋势/健康度）只渲染禁用态；
 * - 后端 /overview 路由必须注册在 /{intake_id} 之前，否则被路径参数吞掉。
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
  "workbench.productOverview",
  "workbench.totalProducts",
  "workbench.statusBreakdown",
  "workbench.empty",
  "workbench.unconfigured",
  "workbench.quickActions",
  "workbench.newProduct",
  "workbench.viewAll",
  "workbench.metricsNote",
  "workbench.metrics.generated",
  "workbench.metrics.published",
  "workbench.metrics.interactions",
  "workbench.metrics.trends",
  "workbench.metrics.health",
  ...[
    "draft",
    "ai_recognizing",
    "pending_confirm",
    "pending_params",
    "pending_quota",
    "submitted",
    "in_review",
    "need_more_info",
    "approved",
    "modeling",
    "stored",
    "store_failed",
    "rejected",
    "archived",
    "category_creating",
  ].map((code) => `intake.status.${code}`),
];

const requiredFiles = [
  ["app/[locale]/(shell)/workbench/page.tsx"],
  ["app/[locale]/(shell)/workbench/workbench.module.css"],
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

const pageText = readFileSync(join(shell, "workbench", "page.tsx"), "utf8");
if (!/export const dynamic = "force-dynamic"/.test(pageText))
  problems.push("workbench/page.tsx must be force-dynamic (server-only env)");
if (!/\bgetIntakeOverview\b/.test(pageText))
  problems.push("workbench/page.tsx must fetch via getIntakeOverview");
for (const metric of ["generated", "published", "interactions", "trends", "health"]) {
  if (!pageText.includes(`"${metric}"`))
    problems.push(`workbench/page.tsx must render the V2-disabled metric card: ${metric}`);
}

const cssText = readFileSync(join(shell, "workbench", "workbench.module.css"), "utf8");
for (const cls of ["metricCard", "v2Badge", "metricNote"]) {
  if (!cssText.includes(`.${cls}`))
    problems.push(`workbench.module.css must define .${cls}`);
}

const apiText = readFileSync(join(frontendRoot, "lib", "api.ts"), "utf8");
for (const token of ["getIntakeOverview", "IntakeOverview", "/api/intakes/overview"]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

const routerText = readFileSync(
  join(repoRoot, "backend", "app", "product", "product_intake", "router.py"),
  "utf8",
);
const overviewAt = routerText.indexOf('"/overview"');
const detailAt = routerText.indexOf('"/{intake_id}"');
if (overviewAt === -1) {
  problems.push('backend router must register GET "/overview"');
} else if (detailAt !== -1 && overviewAt > detailAt) {
  problems.push('"/overview" route must be registered before "/{intake_id}"');
}

if (problems.length > 0) {
  console.error(`check-workbench: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-workbench: messages, overview wiring and route order consistent");

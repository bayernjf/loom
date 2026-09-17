#!/usr/bin/env node
/**
 * Q114：settings 只读账户面板切片一致性（零依赖）。
 * - settings.* 消息键齐备；
 * - 页面/样式/服务端访问层函数齐备，页面必须 force-dynamic；
 * - V2 徽标项（平台授权/通知/帮助/团队/账单）只渲染占位，不造假数据。
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(here, "..");
const shell = join(frontendRoot, "app", "[locale]", "(shell)");

const messages = JSON.parse(
  readFileSync(join(frontendRoot, "messages", "zh-CN.json"), "utf8"),
);

const requiredKeys = [
  "settings.intro",
  "settings.unconfigured",
  "settings.accountTitle",
  "settings.accountNote",
  "settings.fieldTenantId",
  "settings.fieldTenantName",
  "settings.fieldPlan",
  "settings.fieldStatus",
  "settings.fieldQuota",
  "settings.nameEmpty",
  "settings.quotaEmpty",
  "settings.languageTitle",
  "settings.languageValue",
  "settings.languageNote",
  "settings.moreTitle",
  "settings.moreNote",
  "settings.itemPlatformAuth",
  "settings.itemNotifications",
  "settings.itemHelp",
  "settings.itemTeam",
  "settings.itemBilling",
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

for (const rel of [
  "app/[locale]/(shell)/settings/page.tsx",
  "app/[locale]/(shell)/settings/settings.module.css",
]) {
  if (!existsSync(join(frontendRoot, rel))) problems.push(`missing file: ${rel}`);
}

const pageText = readFileSync(join(shell, "settings", "page.tsx"), "utf8");
if (!/export const dynamic = "force-dynamic"/.test(pageText))
  problems.push("settings/page.tsx must be force-dynamic (server-only env)");
if (!/\bgetCurrentTenant\b/.test(pageText))
  problems.push("settings/page.tsx must fetch via getCurrentTenant");
for (const item of ["itemPlatformAuth", "itemNotifications", "itemHelp", "itemTeam", "itemBilling"]) {
  if (!pageText.includes(`"${item}"`))
    problems.push(`settings/page.tsx must render the V2-badged item: ${item}`);
}

const cssText = readFileSync(join(shell, "settings", "settings.module.css"), "utf8");
for (const cls of ["card", "v2Badge", "accountList", "moreList"]) {
  if (!cssText.includes(`.${cls}`))
    problems.push(`settings.module.css must define .${cls}`);
}

const apiText = readFileSync(join(frontendRoot, "lib", "api.ts"), "utf8");
for (const token of ["getCurrentTenant", "CustomerTenantView", "/api/tenants/"]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must contain ${token}`);
}

if (problems.length > 0) {
  console.error(`check-settings: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-settings: messages, page wiring and V2 badges consistent");

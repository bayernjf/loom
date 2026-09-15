#!/usr/bin/env node
/**
 * Q98：产品中心切片一致性（零依赖）。
 * - products.* 消息键齐备；
 * - 列表/新建/详情/两个占位页与服务端访问层文件齐备；
 * - lib/api.ts 只允许服务端引用：禁止 NEXT_PUBLIC（env 不进浏览器包）；
 * - Server Action 必须 "use server"，表单组件必须 "use client"。
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const shell = join(root, "app", "[locale]", "(shell)");

const messages = JSON.parse(
  readFileSync(join(root, "messages", "zh-CN.json"), "utf8"),
);

const requiredKeys = [
  "products.myProducts",
  "products.productTemplates",
  "products.library",
  "products.newProduct",
  "products.columnName",
  "products.columnStatus",
  "products.empty",
  "products.unconfigured",
  "products.new.title",
  "products.new.nameLabel",
  "products.new.profileKeyNote",
  "products.new.submit",
  "products.detail.title",
  "products.detail.fieldId",
  "products.detail.fieldStatus",
  "products.detail.fieldProfile",
  "error.403",
  "error.404",
  "error.409",
  "error.422",
  "error.unknown",
];

const requiredFiles = [
  ["lib/api.ts"],
  [".env.example"],
  ["app/[locale]/(shell)/products/page.tsx"],
  ["app/[locale]/(shell)/products/actions.ts"],
  ["app/[locale]/(shell)/products/new-product-form.tsx"],
  ["app/[locale]/(shell)/products/new/page.tsx"],
  ["app/[locale]/(shell)/products/[intakeId]/page.tsx"],
  ["app/[locale]/(shell)/products/templates/page.tsx"],
  ["app/[locale]/(shell)/products/library/page.tsx"],
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
  if (!existsSync(join(root, rel))) problems.push(`missing file: ${rel}`);
}

const apiText = readFileSync(join(root, "lib", "api.ts"), "utf8");
if (/process\.env\.NEXT_PUBLIC/.test(apiText))
  problems.push("lib/api.ts must not read NEXT_PUBLIC_* env (would leak into browser bundle)");
for (const token of ["CURRENT_TENANT_ID", "PRODUCT_NAME_PROFILE_KEY", "listIntakes", "createIntake"]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must export/use ${token}`);
}

const actionsText = readFileSync(
  join(shell, "products", "actions.ts"), "utf8",
);
if (!actionsText.startsWith('"use server"'))
  problems.push('products/actions.ts must start with "use server"');

const formText = readFileSync(
  join(shell, "products", "new-product-form.tsx"), "utf8",
);
if (!formText.startsWith('"use client"'))
  problems.push("new-product-form.tsx must start with \"use client\"");

if (problems.length > 0) {
  console.error(`check-products: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-products: messages, files and server-only API discipline consistent");

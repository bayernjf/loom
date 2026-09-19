#!/usr/bin/env node
/**
 * Q98/Q106：产品中心切片一致性（零依赖）。
 * - products.* 消息键齐备；
 * - 列表/新建/详情/两个占位页、Q106 操作岛/草稿编辑岛/事件白名单与服务端访问层文件齐备；
 * - lib/api.ts 只允许服务端引用：禁止 NEXT_PUBLIC（env 不进浏览器包）；
 * - Server Action 必须 "use server"，client 岛必须 "use client" 且禁引 @/lib/api；
 * - Q106：客户事件白名单只含 4 个客户事件；段1 后端四路由与状态机事件不得漂移。
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
  "products.editProfileTitle",
  "products.actionsTitle",
  "products.neutralAnalyzing",
  "products.actorUnconfigured",
  "products.saveProfile",
  "products.profileSaved",
  "products.actionPending",
  "products.actionSuccess",
  "products.noCustomerActions",
  "products.missingFields",
  "products.eventLabels.submit",
  "products.eventLabels.params_completed",
  "products.eventLabels.quota_confirmed",
  "products.eventLabels.resubmit",
  "products.spaceTitle",
  "products.space.fieldId",
  "products.space.fieldLifecycle",
  "products.space.snapshot",
  "products.targetLanguages.title",
  "products.targetLanguages.note",
  "products.targetLanguages.save",
  "products.targetLanguages.saved",
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
  ["app/[locale]/(shell)/products/intake-codes.ts"],
  ["app/[locale]/(shell)/products/intake-actions.tsx"],
  ["app/[locale]/(shell)/products/draft-profile-form.tsx"],
  ["app/[locale]/(shell)/products/target-languages-form.tsx"],
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

// 422 回显句式必须带 {fids} 占位（fid 原样码拼接在 client 岛完成）。
if (!messages.products?.missingFields?.includes("{fids}"))
  problems.push("products.missingFields must contain the {fids} placeholder");

for (const [rel] of requiredFiles) {
  if (!existsSync(join(root, rel))) problems.push(`missing file: ${rel}`);
}

const apiText = readFileSync(join(root, "lib", "api.ts"), "utf8");
if (/process\.env\.NEXT_PUBLIC/.test(apiText))
  problems.push("lib/api.ts must not read NEXT_PUBLIC_* env (would leak into browser bundle)");
for (const token of [
  "CURRENT_TENANT_ID",
  "CURRENT_ACTOR_ID",
  "PRODUCT_NAME_PROFILE_KEY",
  "listIntakes",
  "createIntake",
  "getAllowedEvents",
  "transitionIntake",
  "patchIntakeProfile",
  "getProductSpace",
  "setIntakeTargetLanguages",
  "getContentLanguages",
  "ContentLanguageView",
  "target_languages",
  "/allowed-events",
  "/transitions",
  "/profile",
  "/product-space",
  "/target-languages",
  "/api/content/languages",
]) {
  if (!apiText.includes(token)) problems.push(`lib/api.ts must export/use ${token}`);
}
// 客户写操作身份必须带 roles: []（客户事件无角色要求），且取自不带 NEXT_PUBLIC 的 env。
if (!apiText.includes("LOOM_ACTOR_ID"))
  problems.push("lib/api.ts must derive the customer actor from LOOM_ACTOR_ID");

const envText = readFileSync(join(root, ".env.example"), "utf8");
if (!envText.includes("LOOM_ACTOR_ID"))
  problems.push(".env.example must document LOOM_ACTOR_ID");
if (/^\s*NEXT_PUBLIC[A-Z0-9_]*\s*=/m.test(envText))
  problems.push(".env.example must not expose server envs via NEXT_PUBLIC");

const actionsText = readFileSync(
  join(shell, "products", "actions.ts"), "utf8",
);
if (!actionsText.startsWith('"use server"'))
  problems.push('products/actions.ts must start with "use server"');
for (const token of [
  "transitionIntakeAction",
  "updateDraftProfileAction",
  "setTargetLanguagesAction",
  "isCustomerIntakeEvent",
  "CURRENT_ACTOR_ID",
  "missing_fids",
  "unconfigured",
]) {
  if (!actionsText.includes(token))
    problems.push(`products/actions.ts must use ${token}`);
}

const formText = readFileSync(
  join(shell, "products", "new-product-form.tsx"), "utf8",
);
if (!formText.startsWith('"use client"'))
  problems.push("new-product-form.tsx must start with \"use client\"");

// Q106：client 岛纪律——禁直接访问服务端层/裸 URL，必须经 Server Action 并在成功后 router.refresh。
for (const rel of [
  "products/intake-actions.tsx",
  "products/draft-profile-form.tsx",
  "products/target-languages-form.tsx",
]) {
  const text = readFileSync(join(shell, rel), "utf8");
  if (!text.startsWith('"use client"')) problems.push(`${rel} must start with "use client"`);
  if (text.includes("@/lib/api")) problems.push(`${rel} must not import @/lib/api (server-only)`);
  if (/\bfetch\s*\(/.test(text) || /https?:\/\//.test(text))
    problems.push(`${rel} must not call fetch/embed URLs directly; use server actions`);
  if (!text.includes("router.refresh"))
    problems.push(`${rel} must call router.refresh after a successful action`);
}

// Q106：客户事件白名单精确为 4 个客户事件；运营/系统/触发方待补事件不得外放。
const codesText = readFileSync(join(shell, "products", "intake-codes.ts"), "utf8");
const whitelistMatch = codesText.match(/CUSTOMER_INTAKE_EVENTS\s*=\s*\[([\s\S]*?)\]/);
if (!whitelistMatch) {
  problems.push("intake-codes.ts must define CUSTOMER_INTAKE_EVENTS");
} else {
  const events = [...whitelistMatch[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  const expected = ["submit", "params_completed", "quota_confirmed", "resubmit"];
  if (JSON.stringify(events) !== JSON.stringify(expected))
    problems.push(`CUSTOMER_INTAKE_EVENTS must be exactly ${expected.join(",")} (got ${events.join(",")})`);
  for (const banned of ["ops_confirm", "to_cold_start", "reject", "send_review", "auto_confirm", "b2_"]) {
    if (codesText.includes(`"${banned}`))
      problems.push(`customer event whitelist must not expose ${banned}`);
  }
}

// Q99/Q106：详情/列表状态位不得回退为裸英文码；详情页必须接 allowed-events、两个岛与产品空间。
for (const rel of ["products/page.tsx", "products/[intakeId]/page.tsx"]) {
  const text = readFileSync(join(shell, rel), "utf8");
  if (/\{\s*intake\.status\s*\}/.test(text))
    problems.push(`${rel} must render status via intake.status.* messages, not the raw code`);
  if (!text.includes('getTranslations("intake.status")'))
    problems.push(`${rel} must load the intake.status message namespace`);
}
const detailText = readFileSync(
  join(shell, "products", "[intakeId]", "page.tsx"), "utf8",
);
for (const token of [
  "getAllowedEvents",
  "getProductSpace",
  "getContentLanguages",
  "IntakeActions",
  "DraftProfileForm",
  "TargetLanguagesForm",
  "CURRENT_ACTOR_ID",
  '"category_creating"',
  "force-dynamic",
]) {
  if (!detailText.includes(token))
    problems.push(`products/[intakeId]/page.tsx must use ${token}`);
}
// 草稿编辑岛只允许在 draft 态渲染（其他态后端 409，UI 也不得外放）。
if (!detailText.includes('intake.status === "draft"'))
  problems.push("detail page must gate DraftProfileForm on the draft status");

// Q106 后端防漂移守卫：段1 四路由与状态机客户事件必须保持存在（本切片后端零改动）。
const routerText = readFileSync(
  join(backend, "app", "product", "product_intake", "router.py"), "utf8",
);
for (const route of [
  "/allowed-events",
  "/transitions",
  "/profile",
  "/product-space",
  "/target-languages",
]) {
  if (!routerText.includes(route))
    problems.push(`backend product_intake router must keep the ${route} route`);
}
const smText = readFileSync(
  join(backend, "app", "product", "product_intake", "statemachine.py"), "utf8",
);
for (const event of ["submit", "params_completed", "quota_confirmed", "resubmit"]) {
  if (!smText.includes(`"${event}"`))
    problems.push(`statemachine must keep the "${event}" customer event`);
}

if (problems.length > 0) {
  console.error(`check-products: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log("check-products: messages, files, customer action whitelist and backend routes consistent");

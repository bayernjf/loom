#!/usr/bin/env node
/**
 * Q97：导航注册表 nav.ts 与消息表、页面目录三方一致性。
 * 零依赖：漏消息 key、缺页面文件、href 重复或数量漂移均 exit 1。
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

const navText = readFileSync(join(root, "app", "[locale]", "nav.ts"), "utf8");
const items = [...navText.matchAll(
  /\{\s*href:\s*"([^"]+)"\s*,\s*labelKey:\s*"([^"]+)"\s*,\s*phase:\s*"(v1|v2)"\s*\}/g,
)].map((m) => ({ href: m[1], labelKey: m[2], phase: m[3] }));

const messages = JSON.parse(
  readFileSync(join(root, "messages", "zh-CN.json"), "utf8"),
);

const problems = [];

if (items.length !== 8) problems.push(`nav.ts must register the 8 D5 menus, found ${items.length}`);

const seen = new Set();
for (const item of items) {
  if (seen.has(item.href)) problems.push(`duplicate href: ${item.href}`);
  seen.add(item.href);

  const [namespace, key] = item.labelKey.split(".");
  if (!messages[namespace]?.[key])
    problems.push(`missing message key: ${item.labelKey} (href ${item.href})`);

  const pageFile = join(root, "app", "[locale]", "(shell)", item.href, "page.tsx");
  if (!existsSync(pageFile)) problems.push(`missing page file: ${item.href}/page.tsx`);
}

for (const key of ["shell.primaryNav", "shell.v2Badge", "shell.placeholderV1", "shell.placeholderV2"]) {
  const [namespace, name] = key.split(".");
  if (!messages[namespace]?.[name]) problems.push(`missing message key: ${key}`);
}

if (problems.length > 0) {
  console.error(`check-nav: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log(`check-nav: ${items.length} nav items consistent with messages and page files`);

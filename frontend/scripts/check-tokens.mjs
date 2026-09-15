#!/usr/bin/env node
/**
 * Q96（docs/18 §3.5）：tokens.css 与 tokens.ts 必须逐值一致。
 * 零依赖：正则解析 CSS 自定义属性声明与 TS 元组，连续空白归一化后双向比对。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

const collapse = (value) => value.replace(/\s+/g, " ").trim();

const cssText = readFileSync(join(root, "app", "tokens.css"), "utf8");
const cssTokens = new Map();
for (const match of cssText.matchAll(/^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/gm)) {
  cssTokens.set(match[1], collapse(match[2]));
}

const tsText = readFileSync(join(root, "app", "tokens.ts"), "utf8");
const tsTokens = new Map();
const tuplePattern = /\[\s*"(--[a-z0-9-]+)"\s*,\s*(['"])((?:\\.|(?!\2)[\s\S])*?)\2\s*,?\s*\]/g;
for (const match of tsText.matchAll(tuplePattern)) {
  const name = match[1];
  const quote = match[2];
  const raw = match[3];
  const value = raw.replace(new RegExp(`\\\\${quote}`, "g"), quote).replace(/\\\\/g, "\\");
  tsTokens.set(name, collapse(value));
}

const problems = [];
for (const [name, value] of cssTokens) {
  if (!tsTokens.has(name)) problems.push(`missing in tokens.ts: ${name}`);
  else if (tsTokens.get(name) !== value)
    problems.push(`value mismatch for ${name}:\n  css: ${value}\n  ts:  ${tsTokens.get(name)}`);
}
for (const name of tsTokens.keys()) {
  if (!cssTokens.has(name)) problems.push(`missing in tokens.css: ${name}`);
}

if (problems.length > 0) {
  console.error(`check-tokens: ${problems.length} problem(s)\n${problems.join("\n")}`);
  process.exit(1);
}
console.log(`check-tokens: ${cssTokens.size} tokens match between tokens.css and tokens.ts`);

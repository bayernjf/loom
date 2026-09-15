/*
 * tokens.css 同值镜像（Q96，docs/18 §3.5）：供图表/Canvas 等无法消费
 * CSS 变量的 JS 场景使用。新增/改值必须同步 tokens.css——
 * scripts/check-tokens.mjs 对两侧做全量逐值一致性校验。
 */
export type TokenEntry = readonly [name: string, value: string];

export const tokenValues: readonly TokenEntry[] = [
  // Primitive：文本/中性
  ["--color-text-primary", "rgba(0, 0, 0, 0.88)"],
  ["--color-text-secondary", "rgba(0, 0, 0, 0.65)"],
  ["--color-text-tertiary", "rgba(0, 0, 0, 0.45)"],
  ["--color-text-disabled", "rgba(0, 0, 0, 0.25)"],
  ["--color-text-on-brand", "#ffffff"],
  // Primitive：surfaces
  ["--color-surface-1", "#ffffff"],
  ["--color-surface-2", "#fafafa"],
  ["--color-surface-3", "#f5f5f5"],
  // Primitive：边框
  ["--color-border-subtle", "#f0f0f0"],
  ["--color-border-strong", "#d9d9d9"],
  // Primitive：品牌
  ["--color-brand-1", "#e6f4ff"],
  ["--color-brand-5", "#4096ff"],
  ["--color-brand-6", "#1677ff"],
  ["--color-brand-7", "#0958d9"],
  // Primitive：状态四态
  ["--color-success", "#52c41a"],
  ["--color-success-strong", "#389e0d"],
  ["--color-success-bg", "#f6ffed"],
  ["--color-warning", "#faad14"],
  ["--color-warning-strong", "#d48806"],
  ["--color-warning-bg", "#fffbe6"],
  ["--color-danger", "#ff4d4f"],
  ["--color-danger-strong", "#cf1322"],
  ["--color-danger-bg", "#fff2f0"],
  ["--color-info", "#1677ff"],
  ["--color-info-strong", "#0958d9"],
  ["--color-info-bg", "#e6f4ff"],
  // 字体
  [
    "--font-family-sans",
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  ],
  [
    "--font-family-mono",
    "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  ],
  ["--font-size-xs", "12px"],
  ["--font-size-sm", "13px"],
  ["--font-size-md", "14px"],
  ["--font-size-lg", "16px"],
  ["--font-size-xl", "18px"],
  ["--font-size-2xl", "20px"],
  ["--font-size-3xl", "24px"],
  ["--font-size-4xl", "30px"],
  ["--font-weight-normal", "400"],
  ["--font-weight-medium", "500"],
  ["--font-weight-semibold", "600"],
  ["--line-height-latin", "1.5"],
  ["--line-height-cjk", "1.7"],
  // 间距
  ["--space-1", "4px"],
  ["--space-2", "8px"],
  ["--space-3", "12px"],
  ["--space-4", "16px"],
  ["--space-5", "24px"],
  ["--space-6", "32px"],
  ["--space-7", "48px"],
  ["--space-8", "64px"],
  // 圆角
  ["--radius-1", "4px"],
  ["--radius-2", "8px"],
  ["--radius-3", "12px"],
  ["--radius-4", "16px"],
  // 阴影
  ["--shadow-1", "0 1px 2px 0 rgba(0, 0, 0, 0.06)"],
  [
    "--shadow-2",
    "0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)",
  ],
  [
    "--shadow-3",
    "0 9px 28px 8px rgba(0, 0, 0, 0.05), 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)",
  ],
  // z 层级
  ["--z-dropdown", "1000"],
  ["--z-sticky", "1020"],
  ["--z-fixed", "1030"],
  ["--z-modal-popover", "1040"],
  ["--z-toast", "1050"],
  // 断点
  ["--bp-sm", "640px"],
  ["--bp-md", "768px"],
  ["--bp-lg", "1024px"],
  ["--bp-xl", "1280px"],
  // 动效
  ["--motion-duration-fast", "100ms"],
  ["--motion-duration-base", "200ms"],
  ["--motion-ease-standard", "ease-in-out"],
  // 布局
  ["--layout-content-max", "1280px"],
  ["--sidebar-width", "240px"],
  // Semantic
  ["--color-bg-page", "var(--color-surface-3)"],
  ["--color-bg-card", "var(--color-surface-1)"],
  ["--color-border", "var(--color-border-strong)"],
  ["--color-brand", "var(--color-brand-6)"],
  ["--color-brand-hover", "var(--color-brand-5)"],
  ["--color-brand-active", "var(--color-brand-7)"],
  ["--color-brand-bg", "var(--color-brand-1)"],
  ["--color-state-success", "var(--color-success)"],
  ["--color-state-warning", "var(--color-warning)"],
  ["--color-state-danger", "var(--color-danger)"],
  ["--color-state-info", "var(--color-info)"],
  ["--color-state-success-text", "var(--color-success-strong)"],
  ["--color-state-warning-text", "var(--color-warning-strong)"],
  ["--color-state-danger-text", "var(--color-danger-strong)"],
  ["--color-state-info-text", "var(--color-info-strong)"],
] as const;

export const tokens: Readonly<Record<string, string>> = Object.fromEntries(
  tokenValues,
);

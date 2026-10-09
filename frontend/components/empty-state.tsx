// Loom 统一空态（Q331 门面收口）：淡织纹 mark + 标题 + 可选提示。
// 颜色一律走设计 Token，无硬编码；用于替换各页列表空态的 `styles.notice` 灰卡片。
"use client";

import styles from "./empty-state.module.css";

export function EmptyState({
  title,
  hint,
  action,
  className,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`${styles.root} ${className ?? ""}`}
      role="status"
      data-testid="empty-state"
    >
      <svg
        className={styles.mark}
        viewBox="0 0 32 32"
        width="36"
        height="36"
        aria-hidden="true"
        focusable="false"
      >
        <rect
          x="1.5"
          y="1.5"
          width="29"
          height="29"
          rx="7.5"
          fill="var(--color-brand-bg)"
        />
        <rect
          x="7.5"
          y="7.5"
          width="17"
          height="17"
          rx="2"
          fill="none"
          stroke="var(--color-brand-active)"
          strokeWidth="1.6"
        />
        <path
          d="M7.5 16h17M16 7.5v17"
          stroke="var(--color-brand-active)"
          strokeWidth="1.2"
          opacity="0.55"
        />
      </svg>
      <p className={styles.title}>{title}</p>
      {hint ? <p className={styles.hint}>{hint}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}

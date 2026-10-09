// Loom 统一错误态（UX 收口）：可恢复的错误提示 = 标识 + 标题 + 错误码 + 兜底指引 + 重试。
// 重试为整页刷新（SSR 页数据源在服务端，刷新即重取）；颜色一律走设计 Token。
"use client";

import styles from "./error-state.module.css";

export function ErrorState({
  title,
  code,
  hint,
  retryLabel,
  className,
}: {
  title: string;
  code?: string;
  hint?: string;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div
      className={`${styles.root} ${className ?? ""}`}
      role="alert"
      data-testid="error-state"
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
          fill="var(--color-state-danger-bg)"
        />
        <path
          d="M11 11l10 10M21 11L11 21"
          stroke="var(--color-state-danger-text)"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
      </svg>
      <p className={styles.title}>{title}</p>
      {code ? <p className={styles.code}>{code}</p> : null}
      {hint ? <p className={styles.hint}>{hint}</p> : null}
      <button
        type="button"
        className={styles.retry}
        onClick={() => window.location.reload()}
      >
        {retryLabel ?? "重试"}
      </button>
    </div>
  );
}

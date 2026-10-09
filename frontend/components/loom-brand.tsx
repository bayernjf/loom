// Loom 品牌标识（Q331 品牌化）：织纹 mark + 名称/标语。
// 管理端侧边栏、客户侧侧边栏与登录页共用；颜色一律走设计 Token
// （--color-brand*），无硬编码色值。布局由宿主 CSS module 的 className 控制。
"use client";

export function LoomMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-hidden="true"
      focusable="false"
    >
      {/* 织纹底：圆角方块 + 经纬线（loom 织机意象） */}
      <rect
        x="1.5"
        y="1.5"
        width="29"
        height="29"
        rx="7.5"
        fill="var(--color-brand)"
      />
      <rect
        x="7.5"
        y="7.5"
        width="17"
        height="17"
        rx="2"
        fill="none"
        stroke="rgba(255,255,255,0.95)"
        strokeWidth="1.6"
      />
      <path
        d="M7.5 16h17M16 7.5v17"
        stroke="rgba(255,255,255,0.72)"
        strokeWidth="1.2"
      />
    </svg>
  );
}

export function LoomBrand({
  name,
  tagline,
  size = 26,
  className,
}: {
  name: string;
  tagline?: string;
  size?: number;
  className?: string;
}) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        minWidth: 0,
      }}
    >
      <LoomMark size={size} />
      <span
        style={{
          display: "flex",
          flexDirection: "column",
          lineHeight: 1.3,
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontWeight: 600,
            fontSize: 15,
            color: "var(--color-text-primary)",
            whiteSpace: "nowrap",
          }}
        >
          {name}
        </span>
        {tagline ? (
          <span
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {tagline}
          </span>
        ) : null}
      </span>
    </div>
  );
}

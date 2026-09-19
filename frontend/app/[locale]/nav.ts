export type NavPhase = "v1" | "v2";

export interface NavItem {
  href: string;
  labelKey: string;
  phase: NavPhase;
}

// Q97 接缝①：D5 八菜单全显；核心能力挂 V2 链路段（段8/12/13，Q73）的项标 v2 占位。
// Q122 起第 3 菜单「内容生产与发布」落 V1（成品只读 + 客户审阅 + 人工改稿；生成仍 operations）。
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/workbench", labelKey: "nav.workbench", phase: "v1" },
  { href: "/products", labelKey: "nav.products", phase: "v1" },
  { href: "/content", labelKey: "nav.content", phase: "v1" },
  { href: "/templates", labelKey: "nav.templates", phase: "v2" },
  { href: "/analytics", labelKey: "nav.analytics", phase: "v2" },
  { href: "/social-accounts", labelKey: "nav.socialAccounts", phase: "v2" },
  { href: "/compliance", labelKey: "nav.compliance", phase: "v1" },
  { href: "/settings", labelKey: "nav.settings", phase: "v1" },
] as const;

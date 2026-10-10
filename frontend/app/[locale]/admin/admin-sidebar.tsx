"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";

import { LoomBrand } from "@/components/loom-brand";
import styles from "./admin.module.css";

// Q332（UX 收口）：管理端导航按业务域分组——运营／治理／数据与成本；组内顺序保持原平铺序。
const ADMIN_NAV_GROUPS = [
  {
    labelKey: "admin.navGroupOps",
    items: [
      { href: "/admin/intakes", labelKey: "admin.opsIntakesNav" },
      { href: "/admin/review-workload", labelKey: "admin.reviewWorkloadNav" },
      { href: "/admin/review-queue", labelKey: "admin.reviewQueueNav" },
      { href: "/admin/sla-todos", labelKey: "admin.slaTodosNav" },
      { href: "/admin/content", labelKey: "admin.contentOpsNav" },
      { href: "/admin/fcw", labelKey: "admin.fcwNav" },
      { href: "/admin/fcw/assemble", labelKey: "admin.fcwAssembleNav" },
      { href: "/admin/fcw/review", labelKey: "admin.fcwReviewNav" },
    ],
  },
  {
    labelKey: "admin.navGroupGovernance",
    items: [
      { href: "/admin/tenants", labelKey: "admin.tenantsNav" },
      { href: "/admin/agent-keys", labelKey: "admin.agentKeysNav" },
      { href: "/admin/staff-keys", labelKey: "admin.staffKeysNav" },
      { href: "/admin/dictionaries", labelKey: "admin.dictionariesNav" },
    ],
  },
  {
    labelKey: "admin.navGroupData",
    items: [
      { href: "/admin/token-cost", labelKey: "admin.tokenCostNav" },
      { href: "/admin/effects", labelKey: "admin.effectsNav" },
      { href: "/admin/exports", labelKey: "admin.exportsNav" },
    ],
  },
] as const;

export function AdminSidebar() {
  const t = useTranslations();
  const pathname = usePathname();

  return (
    <nav className={styles.sidebar} aria-label={t("admin.navLabel")}>
      <LoomBrand
        name={t("admin.appName")}
        tagline={t("common.appTagline")}
        className={styles.brand}
      />
      {ADMIN_NAV_GROUPS.map((group) => (
        <div key={group.labelKey} className={styles.navGroup}>
          <span className={styles.navGroupLabel}>{t(group.labelKey)}</span>
          {group.items.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={active ? styles.navItemActive : styles.navItem}
              >
                {t(item.labelKey)}
              </Link>
            );
          })}
        </div>
      ))}
      <Link href="/workbench" className={styles.backLink}>
        {t("admin.back")}
      </Link>
    </nav>
  );
}

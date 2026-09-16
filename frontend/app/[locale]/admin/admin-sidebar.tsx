"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";

import styles from "./admin.module.css";

const ADMIN_NAV_ITEMS = [
  { href: "/admin/token-cost", labelKey: "admin.tokenCostNav" },
  { href: "/admin/review-workload", labelKey: "admin.reviewWorkloadNav" },
] as const;

export function AdminSidebar() {
  const t = useTranslations();
  const pathname = usePathname();

  return (
    <nav className={styles.sidebar} aria-label={t("admin.navLabel")}>
      {ADMIN_NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
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
      <Link href="/workbench" className={styles.backLink}>
        {t("admin.back")}
      </Link>
    </nav>
  );
}

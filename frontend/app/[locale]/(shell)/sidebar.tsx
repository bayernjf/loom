"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";

import { NAV_ITEMS } from "../nav";
import styles from "./shell.module.css";

export function Sidebar() {
  const t = useTranslations();
  const pathname = usePathname();

  return (
    <nav className={styles.sidebar} aria-label={t("shell.primaryNav")}>
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={active ? styles.navItemActive : styles.navItem}
          >
            <span>{t(item.labelKey)}</span>
            {item.phase === "v2" && (
              <span className={styles.v2Badge}>{t("shell.v2Badge")}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

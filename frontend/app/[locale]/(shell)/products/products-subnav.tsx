"use client";

import { useTranslations } from "next-intl";

import { Link, usePathname } from "@/i18n/navigation";
import styles from "./products.module.css";

export function ProductsSubnav() {
  const t = useTranslations("products");
  const pathname = usePathname();
  const items = [
    { href: "/products", label: t("myProducts"), exact: true },
    { href: "/products/templates", label: t("productTemplates"), exact: true },
    { href: "/products/library", label: t("library"), exact: true },
  ];

  return (
    <nav className={styles.subnav} aria-label={t("myProducts")}>
      {items.map((item) => {
        const active = item.exact
          ? pathname === item.href
          : pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={active ? styles.subnavLinkActive : styles.subnavLink}
            {...(active ? { "aria-current": "page" } : {})}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

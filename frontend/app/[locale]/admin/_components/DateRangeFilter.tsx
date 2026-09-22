import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import styles from "../admin.module.css";

/**
 * Q164：两驾驶舱（token-cost / review-workload）共享的日期范围筛选器。
 *
 * 纯服务端组件：<form method="get"> 把 date_from / date_to 写入 URL searchParams，
 * 由 RSC 页面读取后透传后端（半开区间 [date_from, date_to)，UTC date）。
 * 不引入客户端 state；非法区间（from > to）由后端 422 裁决，页面统一展示。
 *
 * basePath 形如 "/admin/token-cost"，用于「重置」回到无查询参数的默认窗口。
 */
export default async function DateRangeFilter({
  basePath,
  from,
  to,
  invalid = false,
}: {
  basePath: string;
  from: string;
  to: string;
  invalid?: boolean;
}) {
  const t = await getTranslations("admin.dateFilter");

  return (
    <form method="get" className={styles.filters} data-date-range-filter>
      <div className={styles.filterFields}>
        <label className={styles.filterField}>
          <span>{t("from")}</span>
          <input
            type="date"
            name="date_from"
            defaultValue={from}
            placeholder={t("placeholderFrom")}
          />
        </label>
        <label className={styles.filterField}>
          <span>{t("to")}</span>
          <input
            type="date"
            name="date_to"
            defaultValue={to}
            placeholder={t("placeholderTo")}
          />
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("apply")}
        </button>
        <Link href={basePath} className={styles.secondaryButton}>
          {t("reset")}
        </Link>
      </div>
      {invalid ? <p className={styles.notice}>{t("invalidRange")}</p> : null}
    </form>
  );
}

/** RSC searchParams 取单值（兼容 string | string[] | undefined）。 */
export function asSearchParam(
  value: string | string[] | undefined,
): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

/** 缺省窗口左端：UTC 今天往前 30 天（与后端默认近 30 天对齐）。 */
export function defaultFromIso(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 30);
  return d.toISOString().slice(0, 10);
}

/** 缺省窗口右端：UTC 今天（半开区间 [from, to)，to 当天不含）。 */
export function defaultToIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** 宽松 ISO date 形态校验（YYYY-MM-DD）；非法交后端 422 裁决。 */
export function isIsoDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

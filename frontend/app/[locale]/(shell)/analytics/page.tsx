import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";

import {
  ApiError,
  CURRENT_TENANT_ID,
  getEffectAnalytics,
  type EffectAnalytics,
} from "@/lib/api";
import styles from "./analytics.module.css";

export const dynamic = "force-dynamic";

// Q166：客户效果数据分析（effect_records 只读聚合；无写口、无 client 岛）。
const COUNTERS = [
  "plays",
  "likes",
  "comments",
  "shares",
  "inquiries",
  "conversions",
] as const;

type SearchParams = Record<string, string | string[] | undefined>;

function oneParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function isIsoDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
}

function day(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

function shortId(value: string | null): string {
  return value ? value.slice(0, 8) : "—";
}

function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("analytics");
  const raw = await searchParams;
  const rawFrom = oneParam(raw.date_from);
  const rawTo = oneParam(raw.date_to);
  const dateFrom = rawFrom && isIsoDate(rawFrom) ? rawFrom : undefined;
  const dateTo = rawTo && isIsoDate(rawTo) ? rawTo : undefined;
  const invalidRange =
    dateFrom !== undefined && dateTo !== undefined && dateFrom > dateTo;

  if (!CURRENT_TENANT_ID) {
    return (
      <main className={styles.page} data-testid="analytics-overview">
        <header className={styles.pageHeader}>
          <h1 className={styles.title}>{t("title")}</h1>
        </header>
        <p className={styles.notice}>{t("unconfigured")}</p>
      </main>
    );
  }

  let data: EffectAnalytics | null = null;
  let failed = false;
  if (!invalidRange) {
    try {
      data = await getEffectAnalytics(CURRENT_TENANT_ID, {
        dateFrom,
        dateTo,
      });
    } catch (err) {
      if (err instanceof ApiError && [403, 404, 409, 422].includes(err.status)) {
        failed = true;
      } else {
        throw err;
      }
    }
  }

  return (
    <main className={styles.page} data-testid="analytics-overview">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <form method="get" className={styles.filters} data-testid="analytics-filter">
        <label className={styles.filterField}>
          <span>{t("dateFrom")}</span>
          <input type="date" name="date_from" defaultValue={dateFrom ?? ""} />
        </label>
        <label className={styles.filterField}>
          <span>{t("dateTo")}</span>
          <input type="date" name="date_to" defaultValue={dateTo ?? ""} />
        </label>
        <button type="submit" className={styles.applyButton}>
          {t("apply")}
        </button>
        <Link href="/analytics" className={styles.resetLink}>
          {t("reset")}
        </Link>
      </form>

      {invalidRange && <p className={styles.error}>{t("invalidRange")}</p>}
      {failed && <p className={styles.error}>{t("loadFailed")}</p>}

      {data && data.records_total === 0 && (
        <p className={styles.notice}>{t("empty")}</p>
      )}

      {data && data.records_total > 0 && (
        <>
          <section className={styles.kpiGrid} data-testid="analytics-kpis">
            <div className={styles.kpiCard}>
              <span className={styles.kpiLabel}>{t("kpiRecords")}</span>
              <span className={styles.kpiValue}>{data.records_total}</span>
            </div>
            <div className={styles.kpiCard}>
              <span className={styles.kpiLabel}>{t("kpiContents")}</span>
              <span className={styles.kpiValue}>{data.contents_covered}</span>
            </div>
            <div className={styles.kpiCard}>
              <span className={styles.kpiLabel}>{t("kpiReadRate")}</span>
              <span className={styles.kpiValue}>{percent(data.read_rate_avg)}</span>
              <span className={styles.kpiHint}>
                {t("readRateSamples", { count: data.read_rate_samples })}
              </span>
            </div>
            <div className={styles.kpiCard}>
              <span className={styles.kpiLabel}>{t("kpiRange")}</span>
              <span className={styles.kpiValueSmall}>
                {day(data.captured_from)} ~ {day(data.captured_to)}
              </span>
            </div>
          </section>

          <section className={styles.metricGrid}>
            {COUNTERS.map((key) => (
              <div key={key} className={styles.metricCard}>
                <span className={styles.metricLabel}>{t(`metric.${key}`)}</span>
                <span className={styles.metricValue}>
                  {data?.metrics_totals[key] ?? 0}
                </span>
              </div>
            ))}
          </section>

          {data.truncated && (
            <p className={styles.warning}>{t("truncated", { limit: data.scan_limit })}</p>
          )}

          <section className={styles.tableSection} data-testid="analytics-by-content">
            <h2 className={styles.sectionTitle}>{t("byContentTitle")}</h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>{t("colContent")}</th>
                    <th className={styles.num}>{t("colRecords")}</th>
                    {COUNTERS.map((key) => (
                      <th key={key} className={styles.num}>
                        {t(`metric.${key}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.by_content.map((row) => (
                    <tr key={row.content_id ?? "none"}>
                      <td>
                        {row.content_id ? (
                          <Link
                            href={`/content/${row.content_id}`}
                            className={styles.contentLink}
                          >
                            {shortId(row.content_id)}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className={styles.num}>{row.records}</td>
                      {COUNTERS.map((key) => (
                        <td key={key} className={styles.num}>
                          {row.metrics[key] ?? 0}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}

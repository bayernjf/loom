import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { Link } from "@/i18n/navigation";
import { ApiError, CURRENT_TENANT_ID, getIntakeOverview } from "@/lib/api";
import styles from "./workbench.module.css";

export const dynamic = "force-dynamic";

// docs/13 §1.1 的 15 态顺序（与后端 statemachine.STATE_LABELS 一致）；仅渲染计数 > 0 的状态。
const STATUS_ORDER = [
  "draft",
  "ai_recognizing",
  "pending_confirm",
  "pending_params",
  "pending_quota",
  "submitted",
  "in_review",
  "need_more_info",
  "approved",
  "modeling",
  "stored",
  "store_failed",
  "rejected",
  "archived",
  "category_creating",
] as const;

// D5 原文五指标（docs/09 D5 表：今日生成/发布/互动/趋势/健康度）；数据源在段 12/13，V1 禁用挂账。
const FUTURE_METRICS = ["generated", "published", "interactions", "trends", "health"] as const;

const KNOWN_ERROR_STATUSES = new Set([403, 404, 409, 422]);

export default async function WorkbenchPage() {
  const t = await getTranslations("workbench");
  const tNav = await getTranslations("nav");
  const tStatus = await getTranslations("intake.status");
  const tError = await getTranslations("error");

  let body: ReactNode;

  if (!CURRENT_TENANT_ID) {
    body = <p className={styles.notice}>{t("unconfigured")}</p>;
  } else {
    try {
      const overview = await getIntakeOverview(CURRENT_TENANT_ID);
      const presentStatuses = STATUS_ORDER.filter((code) => (overview.by_status[code] ?? 0) > 0);
      body = (
        <>
          <section className={styles.card} aria-labelledby="product-overview">
            <div className={styles.cardHeader}>
              <h2 id="product-overview" className={styles.cardTitle}>
                {t("productOverview")}
              </h2>
              <Link href="/products" className={styles.textLink}>
                {t("viewAll")}
              </Link>
            </div>
            <p className={styles.totalLine}>
              <span className={styles.totalValue}>{overview.total}</span>
              <span className={styles.totalLabel}>{t("totalProducts")}</span>
            </p>
            {overview.total === 0 ? (
              <p className={styles.empty}>{t("empty")}</p>
            ) : (
              <>
                <p className={styles.statusListTitle}>{t("statusBreakdown")}</p>
                <dl className={styles.statusList}>
                  {presentStatuses.map((code) => (
                    <div key={code} className={styles.statusRow}>
                      <dd className={styles.statusName}>{tStatus(code)}</dd>
                      <dd className={styles.statusCount}>{overview.by_status[code]}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </section>

          <section className={styles.card} aria-labelledby="quick-actions">
            <h2 id="quick-actions" className={styles.cardTitle}>
              {t("quickActions")}
            </h2>
            <div className={styles.actionRow}>
              <Link href="/products/new" className={styles.primaryButton}>
                {t("newProduct")}
              </Link>
              <Link href="/products" className={styles.secondaryButton}>
                {t("viewAll")}
              </Link>
            </div>
          </section>
        </>
      );
    } catch (err) {
      const key = err instanceof ApiError && KNOWN_ERROR_STATUSES.has(err.status)
        ? String(err.status)
        : "unknown";
      body = <p className={styles.notice}>{tError(key)}</p>;
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{tNav("workbench")}</h1>
      </header>

      {body}

      <ul className={styles.metricGrid}>
        {FUTURE_METRICS.map((metric) => (
          <li key={metric} className={styles.metricCard} aria-disabled="true">
            <div className={styles.metricHeader}>
              <span className={styles.metricName}>{t(`metrics.${metric}`)}</span>
              <span className={styles.v2Badge}>V2</span>
            </div>
            <p className={styles.metricNote}>{t("metricsNote")}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

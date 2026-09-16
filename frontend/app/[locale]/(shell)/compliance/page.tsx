import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import {
  ApiError,
  CURRENT_TENANT_ID,
  getComplianceOverview,
  type CcrMarket,
  type ComplianceOverviewItem,
} from "@/lib/api";
import styles from "./compliance.module.css";

export const dynamic = "force-dynamic";

const KNOWN_ERROR_STATUSES = new Set([403, 404, 409, 422]);

// CCR 四态（ccr_rules.REPORT_*）与法审三态的 chip 配色；枚举码不翻译，文案走 compliance.ccr/law。
const CCR_TONE: Record<string, string> = {
  blocked: styles.toneDanger,
  downgrade_pending: styles.toneWarning,
  approved: styles.toneInfo,
  clean: styles.toneSuccess,
};

const LAW_TONE: Record<string, string> = {
  pending: styles.toneWarning,
  approved: styles.toneSuccess,
  rejected: styles.toneDanger,
};

function formatDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

function MarketDetail({
  market,
  t,
  tCcr,
}: {
  market: CcrMarket;
  t: (key: string, vars?: Record<string, string>) => string;
  tCcr: (key: string) => string;
}) {
  const label = market.country
    ? t("market", { country: market.country })
    : t("marketBase");
  return (
    <li className={styles.marketItem}>
      <div className={styles.marketHeader}>
        <span className={styles.marketName}>{label}</span>
        <span className={`${styles.chip} ${CCR_TONE[market.status] ?? ""}`}>
          {tCcr(market.status)}
        </span>
        <span className={styles.marketDate}>{formatDate(market.created_at)}</span>
      </div>
      {market.bans.length > 0 && (
        <p className={styles.hitLine}>
          <span className={styles.banLabel}>{t("bans")}：</span>
          {market.bans.map((hit) => hit.word).join("、")}
        </p>
      )}
      {market.downgrades.length > 0 && (
        <ul className={styles.downgradeList}>
          {market.downgrades.map((hit) => (
            <li key={`${hit.word}-${hit.downgrade_target}`}>
              {t("downgradeArrow", { word: hit.word, target: hit.downgrade_target })}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function ProductRow({
  item,
  t,
  tCcr,
  tLaw,
}: {
  item: ComplianceOverviewItem;
  t: (key: string, vars?: Record<string, string>) => string;
  tCcr: (key: string) => string;
  tLaw: (key: string) => string;
}) {
  const name = item.product_name ?? item.product_space_id.slice(0, 8);
  return (
    <li className={styles.item}>
      <details>
        <summary className={styles.summary}>
          <span className={styles.productName}>{name}</span>
          <span className={styles.version}>{t("version")}：{item.version}</span>
          {item.ccr ? (
            <span className={`${styles.chip} ${CCR_TONE[item.ccr.worst_status] ?? ""}`}>
              {tCcr(item.ccr.worst_status)}
            </span>
          ) : (
            <span className={styles.mutedChip}>{t("noReport")}</span>
          )}
          {item.law_review ? (
            <span className={`${styles.chip} ${LAW_TONE[item.law_review.status] ?? ""}`}>
              {tLaw(item.law_review.status)}
            </span>
          ) : (
            <span className={styles.mutedChip}>{t("noLawReview")}</span>
          )}
          {item.ccr?.block_required && <span className={styles.blockBadge}>{t("blockRequired")}</span>}
        </summary>

        <div className={styles.detail}>
          <h3 className={styles.detailHeading}>{t("detailTitle")}</h3>
          {item.ccr ? (
            <section className={styles.detailSection}>
              <p className={styles.detailMeta}>
                {t("latestAt")}：{formatDate(item.ccr.latest_at)}
              </p>
              <ul className={styles.marketList}>
                {item.ccr.markets.map((market) => (
                  <MarketDetail
                    key={market.country ?? "__base__"}
                    market={market}
                    t={t}
                    tCcr={tCcr}
                  />
                ))}
              </ul>
            </section>
          ) : (
            <p className={styles.detailMeta}>{t("noReport")}</p>
          )}

          <section className={styles.detailSection}>
            <h4 className={styles.subHeading}>{t("lawTitle")}</h4>
            {item.law_review ? (
              <dl className={styles.lawList}>
                <dt>{t("lawDomain")}</dt>
                <dd>{item.law_review.domain}</dd>
                <dt>{t("lawStatusLabel")}</dt>
                <dd>{tLaw(item.law_review.status)}</dd>
                {item.law_review.conclusion && (
                  <>
                    <dt>{t("lawConclusion")}</dt>
                    <dd>{item.law_review.conclusion}</dd>
                  </>
                )}
                <dt>{t("decidedAt")}</dt>
                <dd>{formatDate(item.law_review.decided_at)}</dd>
              </dl>
            ) : (
              <p className={styles.detailMeta}>{t("noLawReview")}</p>
            )}
          </section>
        </div>
      </details>
    </li>
  );
}

export default async function CompliancePage() {
  const t = await getTranslations("compliance");
  const tNav = await getTranslations("nav");
  const tCcr = await getTranslations("compliance.ccr");
  const tLawNamespace = await getTranslations("compliance.law");
  const tError = await getTranslations("error");

  const tc = (key: string, vars?: Record<string, string>) => t(key, vars);

  let body: ReactNode;

  if (!CURRENT_TENANT_ID) {
    body = <p className={styles.notice}>{t("unconfigured")}</p>;
  } else {
    try {
      const overview = await getComplianceOverview(CURRENT_TENANT_ID);
      body =
        overview.items.length === 0 ? (
          <p className={styles.notice}>{t("empty")}</p>
        ) : (
          <ul className={styles.itemList}>
            {overview.items.map((item) => (
              <ProductRow
                key={item.pws_id}
                item={item}
                t={tc}
                tCcr={tCcr}
                tLaw={tLawNamespace}
              />
            ))}
          </ul>
        );
    } catch (err) {
      const key =
        err instanceof ApiError && KNOWN_ERROR_STATUSES.has(err.status)
          ? String(err.status)
          : "unknown";
      body = <p className={styles.notice}>{tError(key)}</p>;
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{tNav("compliance")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      {body}
    </div>
  );
}

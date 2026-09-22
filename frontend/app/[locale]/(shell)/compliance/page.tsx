import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import {
  ApiError,
  CURRENT_TENANT_ID,
  getComplianceOverview,
  getComplianceWordlist,
  getCcrDetail,
  getCcrHistory,
  getTenantLawReviews,
  type CcrDetail,
  type CcrHistoryItem,
  type CcrMarket,
  type ComplianceOverviewItem,
  type LawReviewSlaItem,
  type WordlistEntryView,
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

function shortId(id: string): string {
  return id.slice(0, 8);
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

// Q162①：历史清洗报告行（时间倒序，点击展开 hits 明细）。
function HistoryRow({
  item,
  detail,
  tH,
  tCcr,
}: {
  item: CcrHistoryItem;
  detail: CcrDetail | null;
  tH: (key: string, vars?: Record<string, string>) => string;
  tCcr: (key: string) => string;
}) {
  const market = item.country ? item.country : tH("baseMarket");
  const bans = detail?.hits?.bans ?? [];
  const downgrades = detail?.hits?.downgrades ?? [];
  return (
    <li className={styles.histRow}>
      <details>
        <summary className={styles.histSummary}>
          <span className={styles.histPws}>{shortId(item.pws_id)}</span>
          <span>{market}</span>
          <span className={`${styles.chip} ${CCR_TONE[item.status] ?? ""}`}>
            {tCcr(item.status)}
          </span>
          {item.block_required && (
            <span className={styles.blockBadge}>{tH("blockYes")}</span>
          )}
          <span className={styles.marketDate}>{formatDate(item.created_at)}</span>
        </summary>
        <div className={styles.histMeta}>
          <span>{tH("hitsTitle")}：</span>
          {bans.length > 0 && (
            <span>
              {tH("bansLabel")}：{bans.map((h) => h.word).join("、")}
            </span>
          )}
          {downgrades.length > 0 && (
            <span>
              {tH("downgradesLabel")}：
              {downgrades.map((h) => h.word).join("、")}
            </span>
          )}
          {bans.length === 0 && downgrades.length === 0 && <span>—</span>}
        </div>
      </details>
    </li>
  );
}

// Q162②：法审 SLA 卡片（倒计时服务端派生，不做客户端 tick）。
function LawCard({
  row,
  tLawSla,
  tLaw,
}: {
  row: LawReviewSlaItem;
  tLawSla: (key: string, vars?: Record<string, string>) => string;
  tLaw: (key: string) => string;
}) {
  let countdown: ReactNode;
  if (row.sla_state === "overdue") {
    const hours = row.sla_remaining_seconds
      ? Math.ceil(row.sla_remaining_seconds / 3600)
      : 0;
    countdown = (
      <span className={styles.lawCountdownOverdue}>
        {tLawSla("overdueFormat", { hours: String(hours) })}
      </span>
    );
  } else if (row.sla_state === "normal" && row.sla_remaining_seconds != null) {
    const hours = Math.ceil(row.sla_remaining_seconds / 3600);
    countdown = (
      <span className={styles.lawCountdown}>
        {tLawSla("remainingFormat", { hours: String(hours) })}
      </span>
    );
  } else {
    countdown = <span className={styles.lawDecided}>{tLawSla("resolved")}</span>;
  }
  return (
    <li className={styles.lawCard}>
      <span className={styles.lawDomain}>{row.domain}</span>
      <span className={`${styles.chip} ${LAW_TONE[row.status] ?? ""}`}>
        {tLaw(row.status)}
      </span>
      {countdown}
      {row.conclusion && <span className={styles.lawDecided}>{row.conclusion}</span>}
      {row.sla_state === "resolved" && row.decided_at && (
        <span className={styles.lawDecided}>
          {tLawSla("decidedAt")}：{formatDate(row.decided_at)}
        </span>
      )}
    </li>
  );
}

// Q162③：词库行（只读表格）。
function WordlistRow({
  entry,
  tWl,
}: {
  entry: WordlistEntryView;
  tWl: (key: string) => string;
}) {
  const country = entry.country ?? tWl("allMarkets");
  const action =
    entry.action === "ban"
      ? tWl("actionBan")
      : entry.action === "downgrade"
        ? tWl("actionDowngrade")
        : entry.action;
  const layer =
    entry.layer === "country"
      ? tWl("layerCountry")
      : entry.layer === "platform"
        ? tWl("layerPlatform")
        : tWl("layerBase");
  const effective =
    entry.effective_from || entry.effective_until
      ? `${formatDate(entry.effective_from)} ~ ${formatDate(entry.effective_until)}`
      : "—";
  return (
    <tr>
      <td className={styles.wlWord}>{entry.word}</td>
      <td>{entry.level}</td>
      <td>{action}</td>
      <td>{country}</td>
      <td>{layer}</td>
      <td>{effective}</td>
    </tr>
  );
}

export default async function CompliancePage() {
  const t = await getTranslations("compliance");
  const tNav = await getTranslations("nav");
  const tCcr = await getTranslations("compliance.ccr");
  const tLawNamespace = await getTranslations("compliance.law");
  const tHistory = await getTranslations("compliance.history");
  const tLawSla = await getTranslations("compliance.lawSla");
  const tWordlist = await getTranslations("compliance.wordlist");
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

  // Q162 三子岛（best-effort，任一失败不拖垮整页）。
  let historySection: ReactNode = null;
  let lawSection: ReactNode = null;
  let wordlistSection: ReactNode = null;

  if (CURRENT_TENANT_ID) {
    // ① 清洗报告历史（取最近 20 条，逐行补 hits 明细）。
    try {
      const hist = await getCcrHistory(CURRENT_TENANT_ID, { limit: 20 });
      if (hist.items.length === 0) {
        historySection = (
          <section className={styles.subSection} data-testid="ccr-history">
            <header className={styles.subHeader}>
              <h2 className={styles.subTitle}>{tHistory("title")}</h2>
              <p className={styles.subNote}>{tHistory("note")}</p>
            </header>
            <p className={styles.notice}>{tHistory("empty")}</p>
          </section>
        );
      } else {
        const details = await Promise.all(
          hist.items.map((it) =>
            getCcrDetail(it.ccr_id, CURRENT_TENANT_ID).catch(() => null),
          ),
        );
        historySection = (
          <section className={styles.subSection} data-testid="ccr-history">
            <header className={styles.subHeader}>
              <h2 className={styles.subTitle}>{tHistory("title")}</h2>
              <p className={styles.subNote}>{tHistory("note")}</p>
            </header>
            <ul className={styles.histList}>
              {hist.items.map((item, i) => (
                <HistoryRow
                  key={item.ccr_id}
                  item={item}
                  detail={details[i] ?? null}
                  tH={tHistory}
                  tCcr={tCcr}
                />
              ))}
            </ul>
          </section>
        );
      }
    } catch {
      historySection = (
        <section className={styles.subSection} data-testid="ccr-history">
          <header className={styles.subHeader}>
            <h2 className={styles.subTitle}>{tHistory("title")}</h2>
            <p className={styles.subNote}>{tHistory("note")}</p>
          </header>
          <p className={styles.notice}>{tHistory("empty")}</p>
        </section>
      );
    }

    // ② 法审 SLA 卡片。
    try {
      const laws = await getTenantLawReviews(CURRENT_TENANT_ID);
      lawSection = (
        <section className={styles.subSection} data-testid="law-sla">
          <header className={styles.subHeader}>
            <h2 className={styles.subTitle}>{tLawSla("title")}</h2>
            <p className={styles.subNote}>{tLawSla("note")}</p>
          </header>
          {laws.length === 0 ? (
            <p className={styles.notice}>{tLawSla("empty")}</p>
          ) : (
            <ul className={styles.lawCards}>
              {laws.map((row) => (
                <LawCard
                  key={row.law_review_id}
                  row={row}
                  tLawSla={tLawSla}
                  tLaw={tLawNamespace}
                />
              ))}
            </ul>
          )}
        </section>
      );
    } catch {
      lawSection = (
        <section className={styles.subSection} data-testid="law-sla">
          <header className={styles.subHeader}>
            <h2 className={styles.subTitle}>{tLawSla("title")}</h2>
            <p className={styles.subNote}>{tLawSla("note")}</p>
          </header>
          <p className={styles.notice}>{tLawSla("empty")}</p>
        </section>
      );
    }

    // ③ 合规规则库（只读词库）。
    try {
      const wl = await getComplianceWordlist();
      wordlistSection = (
        <section className={styles.subSection} data-testid="compliance-wordlist">
          <header className={styles.subHeader}>
            <h2 className={styles.subTitle}>{tWordlist("title")}</h2>
            <p className={styles.subNote}>{tWordlist("note")}</p>
          </header>
          {wl.length === 0 ? (
            <p className={styles.notice}>{tWordlist("empty")}</p>
          ) : (
            <table className={styles.wlTable}>
              <thead>
                <tr>
                  <th>{tWordlist("columnWord")}</th>
                  <th>{tWordlist("columnLevel")}</th>
                  <th>{tWordlist("columnAction")}</th>
                  <th>{tWordlist("columnCountry")}</th>
                  <th>{tWordlist("columnLayer")}</th>
                  <th>{tWordlist("columnEffective")}</th>
                </tr>
              </thead>
              <tbody>
                {wl.map((entry) => (
                  <WordlistRow key={entry.word + (entry.country ?? "")} entry={entry} tWl={tWordlist} />
                ))}
              </tbody>
            </table>
          )}
        </section>
      );
    } catch {
      wordlistSection = (
        <section className={styles.subSection} data-testid="compliance-wordlist">
          <header className={styles.subHeader}>
            <h2 className={styles.subTitle}>{tWordlist("title")}</h2>
            <p className={styles.subNote}>{tWordlist("note")}</p>
          </header>
          <p className={styles.notice}>{tWordlist("empty")}</p>
        </section>
      );
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{tNav("compliance")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      {body}
      {historySection}
      {lawSection}
      {wordlistSection}
    </div>
  );
}

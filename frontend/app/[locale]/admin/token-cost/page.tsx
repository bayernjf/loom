import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getTokenCostDashboard,
  type FailedSkillRow,
  type TokenCostDailyRow,
  type TokenCostSkillRow,
} from "@/lib/api";
import styles from "../admin.module.css";
import DateRangeFilter, {
  asSearchParam,
  defaultFromIso,
  defaultToIso,
  isIsoDate,
} from "../_components/DateRangeFilter";

export const dynamic = "force-dynamic";

const KNOWN_ERROR_STATUSES = new Set([403, 404, 422]);

type SearchParams = Record<string, string | string[] | undefined>;

function day(iso: string): string {
  return iso.slice(0, 10);
}

function num(value: number): string {
  return String(value);
}

function currencyCell(code: string | null): string {
  return code ?? "—";
}

function DailyTable({
  rows,
  t,
}: {
  rows: TokenCostDailyRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) {
    return <p className={styles.notice}>{t("noDaily")}</p>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("date")}</th>
            <th>{t("model")}</th>
            <th>{t("currency")}</th>
            <th className={styles.num}>{t("runs")}</th>
            <th className={styles.num}>{t("inputTokensCol")}</th>
            <th className={styles.num}>{t("outputTokensCol")}</th>
            <th className={styles.num}>{t("cost")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.date}-${row.model_id}-${row.currency_code ?? "_"}`}>
              <td>{day(row.date)}</td>
              <td>{row.model_id}</td>
              <td>{currencyCell(row.currency_code)}</td>
              <td className={styles.num}>{num(row.runs)}</td>
              <td className={styles.num}>{num(row.input_tokens)}</td>
              <td className={styles.num}>{num(row.output_tokens)}</td>
              <td className={styles.num}>{num(row.total_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SkillTable({
  rows,
  t,
}: {
  rows: TokenCostSkillRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) {
    return <p className={styles.notice}>{t("noDaily")}</p>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("skill")}</th>
            <th>{t("currency")}</th>
            <th className={styles.num}>{t("runs")}</th>
            <th className={styles.num}>{t("inputTokensCol")}</th>
            <th className={styles.num}>{t("outputTokensCol")}</th>
            <th className={styles.num}>{t("cost")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.skill_id}-${row.currency_code ?? "_"}`}>
              <td>{row.skill_id}</td>
              <td>{currencyCell(row.currency_code)}</td>
              <td className={styles.num}>{num(row.runs)}</td>
              <td className={styles.num}>{num(row.input_tokens)}</td>
              <td className={styles.num}>{num(row.output_tokens)}</td>
              <td className={styles.num}>{num(row.total_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FailedTable({
  rows,
  t,
}: {
  rows: FailedSkillRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) {
    return <p className={styles.notice}>{t("noDaily")}</p>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("skill")}</th>
            <th className={styles.num}>{t("failedRunsCol")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.skill_id}>
              <td>{row.skill_id}</td>
              <td className={styles.num}>{num(row.failed_runs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function TokenCostPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const t = await getTranslations("admin.tokenCost");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  const rawFrom = asSearchParam(sp.date_from);
  const rawTo = asSearchParam(sp.date_to);
  const from = isIsoDate(rawFrom) ? rawFrom : defaultFromIso();
  const to = isIsoDate(rawTo) ? rawTo : defaultToIso();
  const invalid = from > to;

  let body: ReactNode;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    body = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
  } else {
    try {
      const dashboard = await getTokenCostDashboard({ dateFrom: from, dateTo: to });
      body = (
        <>
          <p className={styles.windowLine}>
            {tAdmin("window", {
              from: day(dashboard.window.from),
              to: day(dashboard.window.to),
            })}
          </p>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("totals")}</h2>
            <div className={styles.totalsGrid}>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("totalRuns")}</span>
                <span className={styles.totalValue}>{num(dashboard.totals.runs)}</span>
              </div>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("inputTokens")}</span>
                <span className={styles.totalValue}>{num(dashboard.totals.input_tokens)}</span>
              </div>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("outputTokens")}</span>
                <span className={styles.totalValue}>{num(dashboard.totals.output_tokens)}</span>
              </div>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("failedRuns")}</span>
                <span className={styles.totalValue}>{num(dashboard.totals.failed_runs)}</span>
              </div>
            </div>
          </section>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("dailyTitle")}</h2>
            <DailyTable rows={dashboard.daily} t={t} />
          </section>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("bySkillTitle")}</h2>
            <SkillTable rows={dashboard.by_skill} t={t} />
          </section>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("failedTitle")}</h2>
            <FailedTable rows={dashboard.failed_by_skill} t={t} />
          </section>
        </>
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
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      <section className={styles.section}>
        <DateRangeFilter
          basePath="/admin/token-cost"
          from={from}
          to={to}
          invalid={invalid}
        />
      </section>
      {body}
    </div>
  );
}

import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getReviewWorkloadDashboard,
  type CandidateBacklogRow,
  type DecidedCountRow,
  type ResolvedCountRow,
  type TodoBacklogRow,
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

function snapshotTime(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

// 纯机械换算（天 ≥ 1 取整天，否则小时 ≥ 1 取整小时，否则分钟），不做业务语义。
function formatWait(seconds: number): string {
  if (seconds >= 86400) return `${Math.floor(seconds / 86400)} 天`;
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)} 小时`;
  return `${Math.floor(seconds / 60)} 分钟`;
}

function CandidateTable({
  rows,
  t,
}: {
  rows: CandidateBacklogRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) return <p className={styles.notice}>{t("empty")}</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("targetType")}</th>
            <th className={styles.num}>{t("pending")}</th>
            <th>{t("oldestWait")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.target_type}>
              <td>{row.target_type}</td>
              <td className={styles.num}>{num(row.pending)}</td>
              <td>
                {row.oldest_wait_seconds === null
                  ? "—"
                  : formatWait(row.oldest_wait_seconds)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TodoTable({
  rows,
  t,
}: {
  rows: TodoBacklogRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) return <p className={styles.notice}>{t("empty")}</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("todoType")}</th>
            <th className={styles.num}>{t("open")}</th>
            <th className={styles.num}>{t("overdue")}</th>
            <th className={styles.num}>{t("escalated")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.todo_type}>
              <td>{row.todo_type}</td>
              <td className={styles.num}>{num(row.open)}</td>
              <td className={styles.num}>{num(row.overdue)}</td>
              <td className={styles.num}>{num(row.escalated)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DecidedTable({
  rows,
  t,
}: {
  rows: DecidedCountRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) return <p className={styles.notice}>{t("empty")}</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("state")}</th>
            <th className={styles.num}>{t("count")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.state}>
              <td>{row.state}</td>
              <td className={styles.num}>{num(row.count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResolvedTable({
  rows,
  t,
}: {
  rows: ResolvedCountRow[];
  t: (key: string) => string;
}) {
  if (rows.length === 0) return <p className={styles.notice}>{t("empty")}</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("todoType")}</th>
            <th className={styles.num}>{t("count")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.todo_type}>
              <td>{row.todo_type}</td>
              <td className={styles.num}>{num(row.count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function ReviewWorkloadPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const t = await getTranslations("admin.workload");
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
      const dashboard = await getReviewWorkloadDashboard({ dateFrom: from, dateTo: to });
      const { backlog, window_output: output } = dashboard;
      body = (
        <>
          <p className={styles.windowLine}>
            {tAdmin("window", {
              from: day(dashboard.window.from),
              to: day(dashboard.window.to),
            })}
          </p>
          <p className={styles.windowLine}>{t("snapshotAt", { at: snapshotTime(dashboard.snapshot_at) })}</p>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("totals")}</h2>
            <div className={styles.totalsGrid}>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("pendingCandidates")}</span>
                <span className={styles.totalValue}>{num(backlog.totals.pending_candidates)}</span>
              </div>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("openTodos")}</span>
                <span className={styles.totalValue}>{num(backlog.totals.open_todos)}</span>
              </div>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("overdueTodos")}</span>
                <span className={styles.totalValue}>{num(backlog.totals.overdue_todos)}</span>
              </div>
              <div className={styles.totalCard}>
                <span className={styles.totalLabel}>{t("escalatedTodos")}</span>
                <span className={styles.totalValue}>{num(backlog.totals.escalated_todos)}</span>
              </div>
            </div>
          </section>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("candidateBacklog")}</h2>
            <CandidateTable rows={backlog.candidates} t={t} />
          </section>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("todoBacklog")}</h2>
            <TodoTable rows={backlog.todos} t={t} />
          </section>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("output")}</h2>
            <h3 className={styles.sectionTitle}>{t("candidatesDecided")}</h3>
            <DecidedTable rows={output.candidates_decided} t={t} />
            <h3 className={styles.sectionTitle}>{t("todosResolved")}</h3>
            <ResolvedTable rows={output.todos_resolved} t={t} />
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
          basePath="/admin/review-workload"
          from={from}
          to={to}
          invalid={invalid}
        />
      </section>
      {body}
    </div>
  );
}

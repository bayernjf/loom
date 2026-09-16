import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getOpsIntakeQueue,
  type OpsIntakeList,
} from "@/lib/api";
import { INTAKE_STATUS_FILTERS } from "./ops-intake-codes";
import styles from "../admin.module.css";

export const dynamic = "force-dynamic";

const PAGE_LIMIT = 50;
const KNOWN_ERROR_STATUSES = new Set([403, 404, 422]);

type SearchParams = Record<string, string | string[] | undefined>;
type Translator = Awaited<ReturnType<typeof getTranslations>>;

function asString(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function buildQueryString(params: Record<string, string>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) search.set(key, value);
  return search.toString();
}

function timeText(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

function StatusFilters({
  status,
  t,
  tStatus,
}: {
  status: string;
  t: Translator;
  tStatus: Translator;
}) {
  return (
    <form method="get" className={styles.filters}>
      <div className={styles.filterFields}>
        <label className={styles.filterField}>
          <span>{t("filterStatus")}</span>
          <select name="status" defaultValue={status}>
            <option value="">{t("filterAll")}</option>
            {INTAKE_STATUS_FILTERS.map((value) => (
              <option key={value} value={value}>
                {tStatus(value)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("apply")}
        </button>
        <Link href="/admin/intakes" className={styles.secondaryButton}>
          {t("reset")}
        </Link>
      </div>
    </form>
  );
}

function IntakeTable({
  queue,
  t,
  tStatus,
}: {
  queue: OpsIntakeList;
  t: Translator;
  tStatus: Translator;
}) {
  if (queue.items.length === 0) {
    return <p className={styles.notice}>{t("empty")}</p>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("colIntake")}</th>
            <th>{t("colTenant")}</th>
            <th>{t("colStatus")}</th>
            <th>{t("colCreated")}</th>
          </tr>
        </thead>
        <tbody>
          {queue.items.map((intake) => (
            <tr key={intake.intake_id}>
              <td>
                <Link
                  href={`/admin/intakes/${encodeURIComponent(intake.intake_id)}`}
                >
                  {intake.intake_id}
                </Link>
              </td>
              <td>{intake.tenant_id}</td>
              <td>
                <span className={styles.planChip}>{tStatus(intake.status)}</span>
              </td>
              <td>{timeText(intake.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pager({
  queue,
  offset,
  status,
  t,
}: {
  queue: OpsIntakeList;
  offset: number;
  status: string;
  t: Translator;
}) {
  const from = queue.total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + queue.limit, queue.total);
  const queryParams: Record<string, string> = {};
  if (status) queryParams.status = status;
  const prevOffset = Math.max(0, offset - queue.limit);
  const nextOffset = offset + queue.limit;
  const prevHref =
    offset > 0
      ? `/admin/intakes?${buildQueryString({ ...queryParams, offset: String(prevOffset) })}`
      : null;
  const nextHref =
    nextOffset < queue.total
      ? `/admin/intakes?${buildQueryString({ ...queryParams, offset: String(nextOffset) })}`
      : null;
  return (
    <div className={styles.pager}>
      <span>
        {t("pageInfo", { from: String(from), to: String(to), total: String(queue.total) })}
      </span>
      {prevHref ? (
        <Link href={prevHref} className={styles.secondaryButton}>
          {t("prev")}
        </Link>
      ) : (
        <span className={styles.pagerDisabled}>{t("prev")}</span>
      )}
      {nextHref ? (
        <Link href={nextHref} className={styles.secondaryButton}>
          {t("next")}
        </Link>
      ) : (
        <span className={styles.pagerDisabled}>{t("next")}</span>
      )}
    </div>
  );
}

export default async function AdminIntakesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const t = await getTranslations("admin.opsIntakes");
  const tStatus = await getTranslations("intake.status");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  const rawStatus = asString(sp.status);
  const status = (INTAKE_STATUS_FILTERS as readonly string[]).includes(rawStatus)
    ? rawStatus
    : "";
  const offset = Math.max(0, Number.parseInt(asString(sp.offset), 10) || 0);

  let body: ReactNode;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    body = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
  } else {
    try {
      const queue = await getOpsIntakeQueue({
        status: status || undefined,
        limit: PAGE_LIMIT,
        offset,
      });
      body = (
        <>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("filters")}</h2>
            <StatusFilters status={status} t={t} tStatus={tStatus} />
          </section>
          <section className={styles.section}>
            <IntakeTable queue={queue} t={t} tStatus={tStatus} />
            <Pager queue={queue} offset={offset} status={status} t={t} />
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
      {body}
    </div>
  );
}

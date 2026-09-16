import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getReviewQueue,
  type ReviewQueue,
  type ReviewQueueCandidate,
} from "@/lib/api";
import { BatchBar } from "./batch-bar";
import styles from "../admin.module.css";

export const dynamic = "force-dynamic";

const TARGET_TYPES = [
  "pwc_combo",
  "field_plan",
  "c1_recognition",
  "atom_batch",
  "c7_layer4",
] as const;

const STATES = ["pending_review", "applied", "archived"] as const;
const RISK_LEVELS = ["critical", "high", "medium", "low"] as const;
const KNOWN_ERROR_STATUSES = new Set([403, 404, 422]);
const PAGE_LIMIT = 50;

type Translator = Awaited<ReturnType<typeof getTranslations>>;

type SearchParams = Record<string, string | string[] | undefined>;

function asString(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function asList(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) return value;
  if (typeof value === "string" && value !== "") return [value];
  return [];
}

function normalizeState(value: string): string {
  return (STATES as readonly string[]).includes(value) ? value : "pending_review";
}

function buildQueryString(params: Record<string, string | string[]>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, item);
    } else {
      search.set(key, value);
    }
  }
  return search.toString();
}

// 纯机械换算（天 ≥ 1 取整天，否则小时 ≥ 1 取整小时，否则分钟），不做业务语义。
function formatWait(seconds: number): string {
  if (seconds >= 86400) return `${Math.floor(seconds / 86400)} 天`;
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)} 小时`;
  return `${Math.floor(seconds / 60)} 分钟`;
}

function timeText(iso: string | null): string {
  return iso === null ? "—" : iso.slice(0, 16).replace("T", " ");
}

function confidenceText(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function riskClassName(level: string): string {
  if (level === "critical") return styles.riskCritical;
  if (level === "high") return styles.riskHigh;
  if (level === "medium") return styles.riskMedium;
  return styles.riskLow;
}

function Filters({
  state,
  targetTypes,
  riskLevel,
  wfId,
  t,
}: {
  state: string;
  targetTypes: string[];
  riskLevel: string;
  wfId: string;
  t: Translator;
}) {
  return (
    <form method="get" className={styles.filters}>
      <fieldset className={styles.filterGroup}>
        <legend>{t("targetType")}</legend>
        <div className={styles.chipRow}>
          {TARGET_TYPES.map((type) => (
            <label key={type} className={targetTypes.includes(type) ? styles.chipActive : styles.chip}>
              <input type="checkbox" name="target_type" value={type} defaultChecked={targetTypes.includes(type)} />
              {type}
            </label>
          ))}
        </div>
      </fieldset>
      <div className={styles.filterFields}>
        <label className={styles.filterField}>
          <span>{t("state")}</span>
          <select name="state" defaultValue={state}>
            {STATES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filterField}>
          <span>{t("riskLevel")}</span>
          <select name="risk_level" defaultValue={riskLevel}>
            <option value="">—</option>
            {RISK_LEVELS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filterField}>
          <span>{t("wfId")}</span>
          <input type="text" name="wf_id" defaultValue={wfId} />
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("apply")}
        </button>
        <Link href="/admin/review-queue" className={styles.secondaryButton}>
          {t("reset")}
        </Link>
      </div>
    </form>
  );
}

function CandidateTable({
  queue,
  t,
}: {
  queue: ReviewQueue;
  t: Translator;
}) {
  if (queue.candidates.length === 0) {
    return <p className={styles.notice}>{t("empty")}</p>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("colBatch")}</th>
            <th>{t("colType")}</th>
            <th>{t("colRisk")}</th>
            <th className={styles.num}>{t("colConfidence")}</th>
            <th>{t("colWait")}</th>
            <th>{t("colWf")}</th>
            <th>{t("colSkill")}</th>
            <th>{t("colCandidate")}</th>
            <th>{t("colCreated")}</th>
            <th>{t("colTenant")}</th>
            <th>{t("colPayload")}</th>
          </tr>
        </thead>
        <tbody>
          {queue.candidates.map((cand: ReviewQueueCandidate) => (
            <tr key={cand.candidate_id}>
              <td>
                <input
                  type="checkbox"
                  data-batch-candidate
                  value={cand.candidate_id}
                  disabled={!cand.batch_eligible}
                  title={cand.batch_eligible ? undefined : t("notEligible")}
                />
              </td>
              <td>{cand.target_type}</td>
              <td>
                <span className={`${styles.riskChip} ${riskClassName(cand.risk_level)}`}>
                  {cand.risk_level}
                </span>
                <span className={styles.metaLine}>{cand.risk_reason}</span>
              </td>
              <td className={styles.num}>{confidenceText(cand.confidence)}</td>
              <td>{cand.wait_seconds === null ? "—" : formatWait(cand.wait_seconds)}</td>
              <td>{cand.wf_id}</td>
              <td>{cand.skill_id}</td>
              <td>
                {cand.candidate_id}
                {cand.human_modified ? (
                  <span className={styles.metaLine}>{t("humanModified")}</span>
                ) : null}
                {cand.reviewed_by ? (
                  <span className={styles.metaLine}>
                    {t("reviewedBy")}: {cand.reviewed_by}
                  </span>
                ) : null}
              </td>
              <td>{timeText(cand.created_at)}</td>
              <td>{cand.tenant_id ?? "—"}</td>
              <td>
                <details>
                  <summary>{t("showPayload")}</summary>
                  <pre className={styles.payloadPre}>
                    {JSON.stringify(cand.payload, null, 2)}
                  </pre>
                </details>
              </td>
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
  queryParams,
  t,
}: {
  queue: ReviewQueue;
  offset: number;
  queryParams: Record<string, string | string[]>;
  t: Translator;
}) {
  const from = queue.total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + queue.limit, queue.total);
  const prevOffset = Math.max(0, offset - queue.limit);
  const nextOffset = offset + queue.limit;
  const prevHref =
    offset > 0 ? `/admin/review-queue?${buildQueryString({ ...queryParams, offset: String(prevOffset) })}` : null;
  const nextHref =
    nextOffset < queue.total
      ? `/admin/review-queue?${buildQueryString({ ...queryParams, offset: String(nextOffset) })}`
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

export default async function ReviewQueuePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const t = await getTranslations("admin.reviewQueue");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  const state = normalizeState(asString(sp.state));
  const targetTypes = asList(sp.target_type).filter((value) =>
    (TARGET_TYPES as readonly string[]).includes(value),
  );
  const rawRisk = asString(sp.risk_level);
  const riskLevel = (RISK_LEVELS as readonly string[]).includes(rawRisk) ? rawRisk : "";
  const wfId = asString(sp.wf_id);
  const offset = Math.max(0, Number.parseInt(asString(sp.offset), 10) || 0);

  const queryParams: Record<string, string | string[]> = { state };
  if (targetTypes.length > 0) queryParams.target_type = targetTypes;
  if (riskLevel) queryParams.risk_level = riskLevel;
  if (wfId) queryParams.wf_id = wfId;

  let body: ReactNode;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    body = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
  } else {
    try {
      const queue = await getReviewQueue({
        state,
        targetTypes: targetTypes.length > 0 ? targetTypes : undefined,
        riskLevel: riskLevel || undefined,
        wfId: wfId || undefined,
        limit: PAGE_LIMIT,
        offset,
      });
      body = (
        <>
          <p className={styles.windowLine}>
            {t("thresholdNote", { threshold: String(queue.batch_pass_confidence) })}
          </p>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("filters")}</h2>
            <Filters state={state} targetTypes={targetTypes} riskLevel={riskLevel} wfId={wfId} t={t} />
          </section>
          <section className={styles.section}>
            <CandidateTable queue={queue} t={t} />
            <Pager queue={queue} offset={offset} queryParams={queryParams} t={t} />
            {state === "pending_review" ? <BatchBar /> : null}
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

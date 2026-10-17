import { formatDateTimeLocal } from "@/lib/time";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { getTranslations } from "next-intl/server";

import { ApiError, listAtomCandidates } from "@/lib/api";
import type { AtomCandidateView } from "@/lib/api";
import styles from "../admin.module.css";
import { AtomRowActions } from "./atoms-island";

export const dynamic = "force-dynamic";

// Q368：段4 原子管理台（Q360 留的前端切片）。候选列表按产品空间查询，
// status/sort 可选过滤（Q16 sort=affinity 降序）。读口 RSC；裁决/补证/簇合并
// 全走 client 岛 → Server Action（写口 Q242 只认已验真 staff 令牌，
// approve/reject/risk-override/resolve 需 reviewer、AI 补证需 operations）。
type SearchParams = Record<string, string | string[] | undefined>;

function oneParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value.trim() : undefined;
}

function fmt(iso: string | null): string {
  return formatDateTimeLocal(iso);
}

const CANDIDATE_STATUSES = [
  "pending_review",
  "pending_evidence",
  "approved",
  "rejected",
  "merged",
] as const;

function statusChipClass(status: string): string {
  switch (status) {
    case "pending_review":
    case "pending_evidence":
      return styles.chipActive;
    case "approved":
    case "merged":
      return styles.chip;
    default:
      return styles.chip;
  }
}

function riskChipClass(level: string): string {
  switch (level) {
    case "critical":
      return styles.riskCritical;
    case "high":
      return styles.riskHigh;
    case "medium":
      return styles.riskMedium;
    default:
      return styles.riskChip;
  }
}

export default async function AtomsAdminPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.atoms");
  const tError = await getTranslations("error");
  const sp = await searchParams;
  const productSpaceId = oneParam(sp.product_space_id);
  const statusRaw = oneParam(sp.status);
  const status = (CANDIDATE_STATUSES as readonly string[]).includes(
    statusRaw ?? "",
  )
    ? statusRaw
    : undefined;
  const sortRaw = oneParam(sp.sort);
  const sort = sortRaw === "affinity" ? "affinity" : "created_at";

  let candidates: AtomCandidateView[] = [];
  let failed = false;
  let failedStatus = 0;
  if (productSpaceId) {
    try {
      candidates = await listAtomCandidates(productSpaceId, {
        status,
        sort,
      });
    } catch (err) {
      if (err instanceof ApiError && [403, 404, 409, 422].includes(err.status)) {
        failed = true;
        failedStatus = err.status;
      } else {
        throw err;
      }
    }
  }

  return (
    <main className={styles.page} data-testid="atoms-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <form method="get" className={styles.filters} data-testid="atoms-filter">
        <label className={styles.filterField}>
          <span>{t("productSpaceLabel")}</span>
          <input
            type="text"
            name="product_space_id"
            defaultValue={productSpaceId ?? ""}
            placeholder={t("productSpacePlaceholder")}
            required
          />
        </label>
        <label className={styles.filterField}>
          <span>{t("statusLabel")}</span>
          <select name="status" defaultValue={statusRaw ?? ""}>
            <option value="">{t("statusAll")}</option>
            {CANDIDATE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filterField}>
          <span>{t("sortLabel")}</span>
          <select name="sort" defaultValue={sortRaw ?? ""}>
            <option value="">{t("sortCreatedAt")}</option>
            <option value="affinity">{t("sortAffinity")}</option>
          </select>
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("querySubmit")}
        </button>
      </form>

      {!productSpaceId && <p className={styles.notice}>{t("needProductSpace")}</p>}
      {productSpaceId && failed && (
        <ErrorState
          title={t("loadFailed")}
          code={[403, 404, 409, 422].includes(failedStatus) ? String(failedStatus) : undefined}
          hint={tError("retryHint")}
          retryLabel={tError("retry")}
        />
      )}

      {productSpaceId && !failed && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t("candidatesTitle")}</h2>
          {candidates.length === 0 ? (
            <EmptyState title={t("empty")} />
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>{t("colContent")}</th>
                    <th>{t("colFactType")}</th>
                    <th>{t("colRisk")}</th>
                    <th className="num">{t("colAffinity")}</th>
                    <th>{t("colEvidence")}</th>
                    <th>{t("colConflicts")}</th>
                    <th>{t("colStatus")}</th>
                    <th>{t("colAction")}</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => (
                    <tr key={candidate.candidate_id}>
                      <td>
                        <span className={styles.metaLine}>
                          {candidate.candidate_id.slice(0, 8)} · {candidate.fid}
                        </span>
                        <br />
                        {candidate.content}
                        {candidate.cluster_id && (
                          <>
                            <br />
                            <span className={styles.metaLine}>
                              {t("clusterTag")} {candidate.cluster_id.slice(0, 8)}
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        {candidate.fact_type ? (
                          <span className={styles.chip}>{candidate.fact_type}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <span className={riskChipClass(candidate.risk_level)}>
                          {candidate.risk_level}
                        </span>
                        {candidate.risk_source && (
                          <span className={styles.metaLine}>
                            {" "}
                            · {candidate.risk_source}
                          </span>
                        )}
                      </td>
                      <td className="num">
                        {candidate.affinity !== null
                          ? candidate.affinity.toFixed(3)
                          : "—"}
                        {candidate.low_affinity && (
                          <span className={styles.metaLine}> ⚠</span>
                        )}
                      </td>
                      <td>
                        {candidate.evidence ? (
                          <span className={styles.metaLine}>
                            {candidate.evidence.slice(0, 40)}
                            {candidate.evidence.length > 40 ? "…" : ""}
                          </span>
                        ) : (
                          "—"
                        )}
                        {candidate.evidence_due_at && (
                          <>
                            <br />
                            <span className={styles.metaLine}>
                              {t("evidenceDue")} {fmt(candidate.evidence_due_at)}
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        {candidate.conflicts.length > 0 ? (
                          <span className={styles.chip}>
                            {candidate.conflicts.length}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <span className={statusChipClass(candidate.status)}>
                          {candidate.status}
                        </span>
                        {candidate.reject_reason && (
                          <span className={styles.metaLine}>
                            <br />
                            {candidate.reject_reason.slice(0, 24)}
                          </span>
                        )}
                      </td>
                      <td>
                        <AtomRowActions candidate={candidate} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

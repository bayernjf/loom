import { Link } from "@/i18n/navigation";
import { EmptyState } from "@/components/empty-state";
import { getTranslations } from "next-intl/server";

import { ApiError, CURRENT_ADMIN_ACTOR_ID, getReviewQueue } from "@/lib/api";
import styles from "../../admin.module.css";

export const dynamic = "force-dynamic";

// Q249 / D3.5 §3.4 甲：白名单（FCW）只读审核队列——发证前审候选（裁决 a）。
// 只读视图：固定过滤 pwc_combo 候选的待审态，复用 Q103 统一审核台的数据口
// （/api/review-workbench/candidates），本页不提供任何裁决/修改写操作，
// 裁决引导至统一审核台。target_type 枚举码原样直出、不翻译（check-admin 纪律）。

type SearchParams = Record<string, string | string[] | undefined>;

const PAGE_SIZE = 50;

function oneParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value.trim() : undefined;
}

function parseOffset(value: string | undefined): number {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : 0;
}

export default async function FcwReviewPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.fcwReview");
  const sp = await searchParams;
  const offset = parseOffset(oneParam(sp.offset));

  let queue: Awaited<ReturnType<typeof getReviewQueue>> | null = null;
  let failed = false;
  let missingRole = false;
  if (CURRENT_ADMIN_ACTOR_ID) {
    try {
      queue = await getReviewQueue({
        state: "pending_review",
        targetTypes: ["pwc_combo"],
        limit: PAGE_SIZE,
        offset,
      });
    } catch (err) {
      if (err instanceof ApiError && [403, 404, 409, 422].includes(err.status)) {
        failed = true;
        missingRole = err.status === 403;
      } else {
        throw err;
      }
    }
  }

  const candidates = queue?.candidates ?? [];
  const total = queue?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + candidates.length, total);
  const queryFor = (nextOffset: number) => {
    const q: Record<string, string> = {};
    if (nextOffset > 0) q.offset = String(nextOffset);
    return new URLSearchParams(q).toString();
  };

  return (
    <section className={styles.section}>
      <h1 className={styles.title}>{t("title")}</h1>
      <p className={styles.windowLine}>{t("intro")}</p>

      {!CURRENT_ADMIN_ACTOR_ID ? (
        <p className={styles.notice}>{t("actorUnconfigured")}</p>
      ) : failed ? (
        <p className={styles.notice}>
          {missingRole ? t("actorMissingRole") : t("loadFailed")}
        </p>
      ) : (
        <>
          <p className={styles.windowLine}>
            {t("total", { from: String(from), to: String(to), total: String(total) })}
          </p>
          {candidates.length === 0 ? (
            <EmptyState title={t("empty")} />
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colCandidate")}</th>
                  <th>{t("colType")}</th>
                  <th>{t("colState")}</th>
                  <th>{t("colRisk")}</th>
                  <th>{t("colConfidence")}</th>
                  <th>{t("colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <tr key={c.candidate_id}>
                    <td className={styles.mono}>{c.candidate_id}</td>
                    <td className={styles.mono}>{c.target_type}</td>
                    <td className={styles.mono}>{c.state}</td>
                    <td>
                      {c.risk_level}（{c.risk_rank}）
                      {c.risk_reason ? ` · ${c.risk_reason}` : ""}
                    </td>
                    <td>
                      {c.confidence === null ? "—" : String(c.confidence)}
                    </td>
                    <td>
                      <Link
                        href={`/admin/review-queue?state=pending_review&target_type=pwc_combo&wf_id=${encodeURIComponent(
                          c.wf_id,
                        )}`}
                        className={styles.link}
                      >
                        {t("goReview")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {total > PAGE_SIZE && (
            <nav className={styles.pager} aria-label={t("pager")}>
              {offset > 0 && (
                <Link
                  href={`/admin/fcw/review?${queryFor(Math.max(0, offset - PAGE_SIZE))}`}
                >
                  {t("prev")}
                </Link>
              )}
              {to < total && (
                <Link href={`/admin/fcw/review?${queryFor(offset + PAGE_SIZE)}`}>
                  {t("next")}
                </Link>
              )}
            </nav>
          )}
        </>
      )}
    </section>
  );
}

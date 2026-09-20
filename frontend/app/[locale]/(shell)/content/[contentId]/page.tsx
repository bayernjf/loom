import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import {
  ApiError,
  getContent,
  type ContentQualityIssue,
  type ContentSemanticFinding,
} from "@/lib/api";
import { BackfillIsland } from "../backfill-island";
import { BatchBackfillIsland } from "../backfill-batch-island";
import { BodyEditIsland } from "../body-edit-island";
import { DecisionIsland } from "../decision-island";
import styles from "../content.module.css";

// Q122：内容成品详情——正文 / AI 质量分（仅供参考）/ 复检结果（词库 + 语义）/
// review 态客户审阅（Q59）/ revising 态客户人工编辑（Q56-a）。
export const dynamic = "force-dynamic";

function formatDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

function formatScore(score: number | null): string {
  return score === null ? "—" : Math.round(score * 100).toString();
}

function issueKey(issue: ContentQualityIssue, index: number): string {
  return typeof issue.code === "string" ? issue.code : `issue-${index}`;
}

function SemanticFindings({
  findings,
  t,
}: {
  findings: ContentSemanticFinding[];
  t: (key: string) => string;
}) {
  if (findings.length === 0)
    return <p className={styles.flagOk}>{t("semanticClean")}</p>;
  return (
    <ul className={styles.hitList}>
      {findings.map((finding, index) => (
        <li key={`${finding.code}-${index}`}>
          <span className={styles.mono}>{finding.code}</span>
          {finding.message ? `：${finding.message}` : ""}
          {finding.excerpt ? `（${finding.excerpt}）` : ""}
        </li>
      ))}
    </ul>
  );
}

export default async function ContentDetailPage({
  params,
}: {
  params: Promise<{ contentId: string }>;
}) {
  const { contentId } = await params;
  const t = await getTranslations("content");
  const tStatus = await getTranslations("content.status");

  let content;
  try {
    content = await getContent(contentId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const hits = content.review_hits;
  const semantic = hits.semantic;

  return (
    <div>
      <h1 className={styles.title}>
        {content.final_id} · {content.language}
      </h1>

      <dl className={styles.detailList}>
        <dt>{t("fieldStatus")}</dt>
        <dd>
          <span className={styles.statusChip}>{tStatus(content.status)}</span>
        </dd>
        <dt>{t("fieldPlatform")}</dt>
        <dd>{content.platform}</dd>
        <dt>{t("fieldGoal")}</dt>
        <dd>{content.goal}</dd>
        <dt>{t("fieldLanguage")}</dt>
        <dd>{content.language}</dd>
        <dt>{t("fieldCountry")}</dt>
        <dd>{content.country ?? "—"}</dd>
        <dt>{t("fieldRegenCount")}</dt>
        <dd>{content.regenerate_count}</dd>
        <dt>{t("fieldCreatedAt")}</dt>
        <dd>{formatDate(content.created_at)}</dd>
      </dl>

      <h2 className={styles.subtitle}>{t("bodyTitle")}</h2>
      <div className={styles.bodyPre}>{content.body ?? t("bodyEmpty")}</div>

      <h2 className={styles.subtitle}>{t("qualityTitle")}</h2>
      <div className={styles.island}>
        <p>
          {t("qualityScore", { score: formatScore(content.quality_score) })}
          <span className={styles.flagOk}>（{t("qualityAdvisoryNote")}）</span>
        </p>
        {content.quality_advisory ? (
          <p className={styles.qualityAdvisory}>{t("qualityAdvisory")}</p>
        ) : null}
        {content.quality_score === null ? (
          <p className={styles.qualityMissing}>{t("qualityMissing")}</p>
        ) : null}
        {content.quality_issues && content.quality_issues.length > 0 ? (
          <ul className={styles.hitList}>
            {content.quality_issues.map((issue, index) => (
              <li key={issueKey(issue, index)}>
                <span className={styles.mono}>{issueKey(issue, index)}</span>
                {typeof issue.message === "string" ? `：${issue.message}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <h2 className={styles.subtitle}>{t("reviewTitle")}</h2>
      <div className={styles.island}>
        {hits.bans.length > 0 ? (
          <>
            <p className={styles.flagBan}>
              {t("bansTitle", { count: hits.bans.length })}
            </p>
            <ul className={styles.hitList}>
              {hits.bans.map((hit) => (
                <li key={hit.entry_id} className={styles.mono}>
                  {hit.word}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className={styles.flagOk}>{t("bansClean")}</p>
        )}
        {hits.downgrades.length > 0 ? (
          <>
            <p className={styles.flagWarn}>
              {t("downgradesTitle", { count: hits.downgrades.length })}
            </p>
            <ul className={styles.hitList}>
              {hits.downgrades.map((hit) => (
                <li key={hit.entry_id}>
                  <span className={styles.mono}>{hit.word}</span>
                  {" → "}
                  <span className={styles.mono}>{hit.downgrade_target}</span>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <h3 className={styles.subtitle}>{t("semanticTitle")}</h3>
        {semantic?.checked ? (
          <SemanticFindings findings={semantic.findings} t={t} />
        ) : (
          <p className={styles.qualityMissing}>{t("semanticUnavailable")}</p>
        )}
      </div>

      {content.status === "rejected" && content.reject_reason ? (
        <div className={styles.island}>
          <h2 className={styles.subtitle}>{t("rejectedReasonTitle")}</h2>
          <p>{content.reject_reason}</p>
        </div>
      ) : null}

      {content.status === "review" ? (
        <DecisionIsland
          contentId={content.content_id}
          blockRequired={hits.block_required}
        />
      ) : null}

      {content.status === "revising" ? (
        <BodyEditIsland
          contentId={content.content_id}
          initialBody={content.body ?? ""}
        />
      ) : null}

      {content.status === "ready_for_publish" ? (
        <div className={styles.island}>
          <h2 className={styles.subtitle}>{t("publishedLinkTitle")}</h2>
          {content.published_url ? (
            <a href={content.published_url} target="_blank" rel="noreferrer">
              {content.published_url}
            </a>
          ) : (
            <p className={styles.notice}>{t("publishedLinkMissing")}</p>
          )}
        </div>
      ) : null}

      {content.status === "discarded" && content.discard_reason ? (
        <div className={styles.island}>
          <h2 className={styles.subtitle}>{t("discardedReasonTitle")}</h2>
          <p>{content.discard_reason}</p>
        </div>
      ) : null}

      {content.status !== "discarded" ? (
        <>
          <BackfillIsland contentId={content.content_id} />
          <BatchBackfillIsland contentId={content.content_id} />
        </>
      ) : null}

      <Link href="/content" className={styles.backLink}>
        {t("backToList")}
      </Link>
    </div>
  );
}

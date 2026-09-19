import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import {
  ApiError,
  CURRENT_TENANT_ID,
  listContent,
  type ContentProductListItem,
} from "@/lib/api";
import styles from "./content.module.css";

// Q122：客户「内容生产与发布」V1 功能页——成品列表（每语言成品并列）+ 详情审阅。
// 运行时读取服务端 env，不得构建期静态固化；生成/重生成仍由 operations 触发，不在本页外放。
export const dynamic = "force-dynamic";

const STATUS_TONE: Record<string, string> = {
  review: styles.toneReview,
  ready_for_publish: styles.toneReady,
  rejected: styles.toneRejected,
  revising: styles.toneRevising,
  generating: styles.toneGenerating,
  draft: styles.toneReview,
  discarded: styles.toneDiscarded,
};

function formatScore(score: number | null): string {
  return score === null ? "—" : Math.round(score * 100).toString();
}

function ReviewFlags({
  item,
  t,
}: {
  item: ContentProductListItem;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  const hits = item.review_hits;
  const semanticFindings = hits.semantic?.checked ? hits.semantic.findings.length : 0;
  if (hits.block_required)
    return (
      <span className={styles.flagBan}>
        {t("flagBlocked", { count: hits.bans.length })}
      </span>
    );
  const warnings: string[] = [];
  if (hits.downgrades.length > 0)
    warnings.push(t("flagDowngrade", { count: hits.downgrades.length }));
  if (semanticFindings > 0)
    warnings.push(t("flagSemantic", { count: semanticFindings }));
  if (warnings.length === 0)
    return <span className={styles.flagOk}>{t("flagClean")}</span>;
  return (
    <ul className={styles.flagList}>
      {warnings.map((text) => (
        <li key={text} className={styles.flagWarn}>
          {text}
        </li>
      ))}
    </ul>
  );
}

export default async function ContentPage() {
  const t = await getTranslations("content");
  const te = await getTranslations("error");
  const tStatus = await getTranslations("content.status");

  let body: React.ReactNode;

  if (!CURRENT_TENANT_ID) {
    body = <p className={styles.notice}>{t("unconfigured")}</p>;
  } else {
    try {
      const items = await listContent(CURRENT_TENANT_ID);
      body =
        items.length === 0 ? (
          <p className={styles.notice}>{t("empty")}</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("columnWhitelist")}</th>
                <th>{t("columnPlatform")}</th>
                <th>{t("columnLanguage")}</th>
                <th>{t("columnStatus")}</th>
                <th>{t("columnQuality")}</th>
                <th>{t("columnReview")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.content_id}>
                  <td>
                    <Link
                      href={`/content/${item.content_id}`}
                      className={styles.rowLink}
                    >
                      {item.final_id}
                      <br />
                      <span className={styles.flagOk}>{item.goal}</span>
                    </Link>
                  </td>
                  <td>{item.platform}</td>
                  <td>{item.language}</td>
                  <td>
                    <span
                      className={`${styles.statusChip} ${
                        STATUS_TONE[item.status] ?? ""
                      }`}
                    >
                      {tStatus(item.status)}
                    </span>
                  </td>
                  <td>
                    <span className={styles.qualityScore}>
                      {t("qualityScore", { score: formatScore(item.quality_score) })}
                    </span>
                    {item.quality_advisory ? (
                      <span className={styles.qualityAdvisory}>
                        {t("qualityAdvisory")}
                      </span>
                    ) : null}
                    {item.quality_score === null ? (
                      <span className={styles.qualityMissing}>
                        {t("qualityMissing")}
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <ReviewFlags item={item} t={t} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        );
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      body = (
        <p className={styles.notice}>
          {te(status === 403 || status === 404 || status === 409 || status === 422
            ? String(status)
            : "unknown")}
        </p>
      );
    }
  }

  return (
    <div>
      <h1 className={styles.title}>{t("title")}</h1>
      <p className={styles.notice}>{t("pageNote")}</p>
      {body}
    </div>
  );
}

import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getNeedsAttentionQueue,
  getReadyToPublishQueue,
  type ContentProductListItem,
} from "@/lib/api";
import { DiscardIsland } from "./discard-island";
import { PublishInfoIsland } from "./publish-info-island";
import styles from "../admin.module.css";

// Q124/Q125：管理端内容运营台——待发布队列回填平台链接/ID（Q60c），
// 待处置队列（review/revising/rejected）作废骨架回池（Q56-b）。
// 读口 operations | platform_admin，写口 operations 硬闸（岛内置缺失角色提示）。
export const dynamic = "force-dynamic";

const KNOWN_ERROR_STATUSES = new Set([403, 404, 422]);

type Translator = Awaited<ReturnType<typeof getTranslations>>;

function timeText(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}

function formatScore(score: number | null): string {
  return score === null ? "—" : Math.round(score * 100).toString();
}

function ReviewFlags({
  item,
  tContent,
}: {
  item: ContentProductListItem;
  tContent: Translator;
}) {
  const hits = item.review_hits;
  if (hits.block_required)
    return (
      <span className={styles.riskCritical}>
        {tContent("flagBlocked", { count: hits.bans.length })}
      </span>
    );
  const semanticFindings = hits.semantic?.checked
    ? hits.semantic.findings.length
    : 0;
  const warnings: string[] = [];
  if (hits.downgrades.length > 0)
    warnings.push(tContent("flagDowngrade", { count: hits.downgrades.length }));
  if (semanticFindings > 0)
    warnings.push(tContent("flagSemantic", { count: semanticFindings }));
  if (warnings.length === 0)
    return <span>{tContent("flagClean")}</span>;
  return (
    <ul className={styles.detailList}>
      {warnings.map((text) => (
        <li key={text} className={styles.riskMedium}>
          {text}
        </li>
      ))}
    </ul>
  );
}

function ContentRowCells({
  item,
  tContent,
  tStatus,
  showStatus,
}: {
  item: ContentProductListItem;
  tContent: Translator;
  tStatus: Translator;
  showStatus: boolean;
}) {
  return (
    <>
      <td>
        {item.final_id}
        <br />
        <span className={styles.metaLine}>{item.goal}</span>
      </td>
      <td>{item.tenant_id}</td>
      <td>{item.platform}</td>
      <td>{item.language}</td>
      {showStatus ? (
        <td>
          <span className={styles.planChip}>{tStatus(item.status)}</span>
        </td>
      ) : null}
      <td>{tContent("qualityScore", { score: formatScore(item.quality_score) })}</td>
      <td>
        <ReviewFlags item={item} tContent={tContent} />
      </td>
      <td>{timeText(item.created_at)}</td>
    </>
  );
}

function PublishQueueSection({
  items,
  t,
  tContent,
  tStatus,
}: {
  items: ContentProductListItem[];
  t: Translator;
  tContent: Translator;
  tStatus: Translator;
}) {
  const pending = items.filter((it) => it.published_at === null);
  const published = items.filter((it) => it.published_at !== null);
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{t("publishTitle")}</h2>
      <p className={styles.intro}>{t("publishIntro")}</p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>{t("colFinal")}</th>
              <th>{t("colTenant")}</th>
              <th>{t("colPlatform")}</th>
              <th>{t("colLanguage")}</th>
              <th>{t("colQuality")}</th>
              <th>{t("colReview")}</th>
              <th>{t("colCreated")}</th>
              <th>{t("colPublish")}</th>
            </tr>
          </thead>
          <tbody>
            {pending.map((item) => (
              <tr key={item.content_id}>
                <ContentRowCells
                  item={item}
                  tContent={tContent}
                  tStatus={tStatus}
                  showStatus={false}
                />
                <td>
                  <PublishInfoIsland contentId={item.content_id} />
                </td>
              </tr>
            ))}
            {published.map((item) => (
              <tr key={item.content_id}>
                <ContentRowCells
                  item={item}
                  tContent={tContent}
                  tStatus={tStatus}
                  showStatus={false}
                />
                <td>
                  <a href={item.published_url ?? "#"} target="_blank" rel="noreferrer">
                    {item.published_url}
                  </a>
                  {item.platform_post_id ? (
                    <span className={styles.metaLine}>
                      {t("postIdLabel")}: {item.platform_post_id}
                    </span>
                  ) : null}
                  <span className={styles.metaLine}>
                    {timeText(item.published_at)}
                  </span>
                  <details>
                    <summary>{t("republishSubmit")}</summary>
                    <PublishInfoIsland
                      contentId={item.content_id}
                      defaultUrl={item.published_url}
                      defaultPostId={item.platform_post_id}
                    />
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pending.length === 0 && published.length === 0 ? (
        <p className={styles.notice}>{t("publishEmpty")}</p>
      ) : null}
    </section>
  );
}

function NeedsAttentionSection({
  items,
  t,
  tContent,
  tStatus,
}: {
  items: ContentProductListItem[];
  t: Translator;
  tContent: Translator;
  tStatus: Translator;
}) {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{t("attentionTitle")}</h2>
      <p className={styles.intro}>{t("attentionIntro")}</p>
      {items.length === 0 ? (
        <p className={styles.notice}>{t("attentionEmpty")}</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("colFinal")}</th>
                <th>{t("colTenant")}</th>
                <th>{t("colPlatform")}</th>
                <th>{t("colLanguage")}</th>
                <th>{t("colStatus")}</th>
                <th>{t("colQuality")}</th>
                <th>{t("colReview")}</th>
                <th>{t("colCreated")}</th>
                <th>{t("colDiscard")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.content_id}>
                  <ContentRowCells
                    item={item}
                    tContent={tContent}
                    tStatus={tStatus}
                    showStatus
                  />
                  <td>
                    <DiscardIsland contentId={item.content_id} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default async function AdminContentPage() {
  const t = await getTranslations("admin.contentOps");
  const tContent = await getTranslations("content");
  const tStatus = await getTranslations("content.status");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  let publishSection: ReactNode;
  let attentionSection: ReactNode;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    publishSection = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
    attentionSection = null;
  } else {
    let publishItems: ContentProductListItem[] | null = null;
    let attentionItems: ContentProductListItem[] | null = null;
    let errorStatus = 0;
    try {
      [publishItems, attentionItems] = await Promise.all([
        getReadyToPublishQueue(),
        getNeedsAttentionQueue(),
      ]);
    } catch (err) {
      errorStatus = err instanceof ApiError ? err.status : 0;
    }
    if (publishItems === null || attentionItems === null) {
      const key = KNOWN_ERROR_STATUSES.has(errorStatus)
        ? String(errorStatus)
        : "unknown";
      publishSection = <p className={styles.notice}>{tError(key)}</p>;
      attentionSection = null;
    } else {
      publishSection = (
        <PublishQueueSection
          items={publishItems}
          t={t}
          tContent={tContent}
          tStatus={tStatus}
        />
      );
      attentionSection = (
        <NeedsAttentionSection
          items={attentionItems}
          t={t}
          tContent={tContent}
          tStatus={tStatus}
        />
      );
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      {publishSection}
      {attentionSection}
    </div>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import {
  getContentDetailAction,
  getVideoWhitelistMaterialAction,
} from "./actions";
import styles from "../admin.module.css";

// Q324：video-studio 两屏（管理端内容运营台内嵌，只读）——
// 屏1 白名单信息区：final_id 的六层原料包摘要（Q177 material.json 出口，读闸）。
// 屏2 生成结果区：成品详情 body（=video_ref）与状态（段12 video 载体，Q323）。
// 两屏均不依赖视频 mode 合法取值（mode 规格【待补】，见 design-q324 §9）。
const MATERIAL_LAYERS = [
  "product",
  "platform",
  "strategy",
  "structure",
  "expression",
  "compliance",
] as const;

function layerCount(layer: Record<string, unknown> | undefined): number {
  if (!layer) return 0;
  return Object.keys(layer).length;
}

export function VideoStudioIsland({
  contentId,
  finalId,
}: {
  contentId: string;
  finalId: string;
}) {
  const t = useTranslations("admin.contentOps");
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  const [whitelist, setWhitelist] = useState<
    Awaited<ReturnType<typeof getVideoWhitelistMaterialAction>> | null
  >(null);
  const [detail, setDetail] = useState<
    Awaited<ReturnType<typeof getContentDetailAction>> | null
  >(null);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (!next) return;
    if (!whitelist) {
      startTransition(async () => {
        setWhitelist(await getVideoWhitelistMaterialAction(finalId));
      });
    }
    if (!detail) {
      startTransition(async () => {
        setDetail(await getContentDetailAction(contentId));
      });
    }
  }

  return (
    <div>
      <button type="button" className={styles.planChip} onClick={toggle}>
        {t("videoStudioToggle")}
      </button>
      {open ? (
        <div className={styles.provisionForm}>
          <section>
            <h3 className={styles.sectionTitle}>{t("whitelistTitle")}</h3>
            {whitelist === null ? (
              <p className={styles.notice}>
                {pending ? t("loading") : t("loadPending")}
              </p>
            ) : whitelist.ok ? (
              <ul className={styles.detailList}>
                {MATERIAL_LAYERS.map((layer) => (
                  <li key={layer}>
                    <span className={styles.metaLine}>
                      {t(`layerName.${layer}`)}: {layerCount(whitelist.pack.layers[layer])}
                    </span>
                  </li>
                ))}
                <li>
                  <span className={styles.metaLine}>
                    {t("whitelistFinal")}: {whitelist.pack.final_id}
                  </span>
                </li>
              </ul>
            ) : (
              <p className={styles.riskMedium}>
                {whitelist.status === 403
                  ? t("actorMissingRole")
                  : t("whitelistLoadFailed")}
              </p>
            )}
          </section>
          <section>
            <h3 className={styles.sectionTitle}>{t("resultTitle")}</h3>
            {detail === null ? (
              <p className={styles.notice}>
                {pending ? t("loading") : t("loadPending")}
              </p>
            ) : detail.ok ? (
              <ul className={styles.detailList}>
                <li>
                  <span className={styles.metaLine}>
                    {t("videoRefLabel")}: {detail.content.body ?? t("resultEmpty")}
                  </span>
                </li>
                <li>
                  <span className={styles.metaLine}>
                    {t("statusLabel")}: {detail.content.status}
                  </span>
                </li>
                <li>
                  <span className={styles.metaLine}>{t("videoNoTextReview")}</span>
                </li>
              </ul>
            ) : (
              <p className={styles.riskMedium}>
                {detail.status === 403
                  ? t("actorMissingRole")
                  : t("resultLoadFailed")}
              </p>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

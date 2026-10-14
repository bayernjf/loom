"use client";

// Q359：新建灵感条岛。layer 闭合枚举（common/product）原样作选项值；product 层
// 必须绑 product_space_id（本地先挡一次 422，与后端校验同口径）。tags 逗号分隔；
// 成功清空表单并 router.refresh() 让 RSC 按当前过滤条件重读。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  createInspirationEntryAction,
  type InspirationActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

function parseTags(raw: string): string[] {
  return raw
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function CreateEntryIsland({ tenantId }: { tenantId: string }) {
  const t = useTranslations("admin.inspirationEntries");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [layer, setLayer] = useState("common");
  const [productSpaceId, setProductSpaceId] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(failure: Extract<InspirationActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  const ready =
    content.trim().length > 0 &&
    (layer !== "product" || productSpaceId.trim().length > 0);

  function submit() {
    setFeedback(null);
    startTransition(async () => {
      const result = await createInspirationEntryAction({
        tenantId,
        layer,
        productSpaceId,
        content,
        tags: parseTags(tags),
        enabled,
      });
      if (result.ok) {
        setFeedback({ kind: "ok", text: t("created") });
        setProductSpaceId("");
        setContent("");
        setTags("");
        setEnabled(true);
        router.refresh();
      } else {
        setFeedback({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <section className={styles.section} data-testid="create-inspiration-entry">
      <h2 className={styles.sectionTitle}>{t("createTitle")}</h2>
      <div className={styles.provisionForm}>
        <label className={styles.decideField}>
          {t("layerLabel")}
          <select
            className={styles.batchReason}
            value={layer}
            onChange={(event) => setLayer(event.target.value)}
          >
            <option value="common">{t("layerOptionCommon")}</option>
            <option value="product">{t("layerOptionProduct")}</option>
          </select>
        </label>
        {layer === "product" && (
          <label className={styles.decideField}>
            {t("productSpaceCreateLabel")}
            <input
              className={styles.batchReason}
              value={productSpaceId}
              maxLength={64}
              placeholder={t("productSpaceCreatePlaceholder")}
              onChange={(event) => setProductSpaceId(event.target.value)}
            />
          </label>
        )}
        <label className={styles.decideField}>
          {t("contentLabel")}
          <textarea
            className={styles.jsonArea}
            value={content}
            maxLength={2000}
            placeholder={t("contentPlaceholder")}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
        <label className={styles.decideField}>
          {t("tagsLabel")}
          <input
            className={styles.batchReason}
            value={tags}
            maxLength={256}
            placeholder={t("tagsPlaceholder")}
            onChange={(event) => setTags(event.target.value)}
          />
        </label>
        <label className={styles.decideField}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />{" "}
          {t("enabledCreateLabel")}
        </label>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending || !ready}
          onClick={submit}
        >
          {t("createSubmit")}
        </button>
      </div>
      {feedback && (
        <p
          className={feedback.kind === "ok" ? styles.msgOk : styles.msgErr}
          role="status"
        >
          {feedback.text}
        </p>
      )}
    </section>
  );
}

"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { setPublishInfoAction, type ContentOpsResult } from "./actions";
import styles from "../admin.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function PublishInfoIsland({
  contentId,
  defaultUrl,
  defaultPostId,
}: {
  contentId: string;
  defaultUrl?: string | null;
  defaultPostId?: string | null;
}) {
  const t = useTranslations("admin.contentOps");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<ContentOpsResult | null>(null);

  function failureText(failure: Extract<ContentOpsResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function submit(formData: FormData) {
    const url = String(formData.get("url") ?? "");
    const postId = String(formData.get("platform_post_id") ?? "");
    if (!url.trim()) {
      setResult({ ok: false, status: 422, detail: null });
      return;
    }
    setResult(null);
    startTransition(async () => {
      const actionResult = await setPublishInfoAction(contentId, url, postId);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    });
  }

  return (
    <form
      className={styles.provisionForm}
      action={submit}
      aria-label={t("publishFormLabel")}
    >
      <div className={styles.provisionFields}>
        <input
          name="url"
          type="url"
          required
          defaultValue={defaultUrl ?? ""}
          placeholder={t("urlPlaceholder")}
          aria-label={t("urlLabel")}
        />
        <input
          name="platform_post_id"
          type="text"
          defaultValue={defaultPostId ?? ""}
          placeholder={t("postIdPlaceholder")}
          aria-label={t("postIdLabel")}
        />
      </div>
      <button type="submit" className={styles.primaryButton} disabled={pending}>
        {defaultUrl ? t("republishSubmit") : t("publishSubmit")}
      </button>
      {result ? (
        <p className={result.ok ? styles.msgOk : styles.msgErr} role="status">
          {result.ok ? t("publishSuccess") : failureText(result)}
        </p>
      ) : null}
    </form>
  );
}

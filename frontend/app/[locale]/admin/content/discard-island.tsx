"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { discardContentAction, type ContentOpsResult } from "./actions";
import styles from "../admin.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function DiscardIsland({ contentId }: { contentId: string }) {
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
    const reason = String(formData.get("reason") ?? "");
    if (!reason.trim()) {
      setResult({ ok: false, status: 422, detail: null });
      return;
    }
    if (!window.confirm(t("discardConfirm"))) return;
    setResult(null);
    startTransition(async () => {
      const actionResult = await discardContentAction(contentId, reason);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    });
  }

  return (
    <form
      className={styles.provisionForm}
      action={submit}
      aria-label={t("discardFormLabel")}
    >
      <div className={styles.provisionFields}>
        <input
          name="reason"
          type="text"
          required
          maxLength={500}
          placeholder={t("reasonPlaceholder")}
          aria-label={t("reasonLabel")}
        />
      </div>
      <button type="submit" className={styles.secondaryButton} disabled={pending}>
        {t("discardSubmit")}
      </button>
      {result ? (
        <p className={result.ok ? styles.msgOk : styles.msgErr} role="status">
          {result.ok ? t("discardSuccess") : failureText(result)}
        </p>
      ) : null}
    </form>
  );
}

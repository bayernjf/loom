"use client";

// Q122：review 态客户审阅岛（Q59 Gate=客户审阅）：通过 / 驳回（原因必填）/ 改稿。
// 仅经同源 Server Action 访问后端，成功后 router.refresh；client 岛不直连服务端访问层。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { decideContentAction, type ContentActionResult } from "./actions";
import styles from "./content.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function DecisionIsland({
  contentId,
  blockRequired,
}: {
  contentId: string;
  blockRequired: boolean;
}) {
  const t = useTranslations("content");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<ContentActionResult | null>(null);

  function failureText(failure: Extract<ContentActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function run(decision: "approve" | "reject" | "revise") {
    if (decision === "reject" && !reason.trim()) {
      setResult({ ok: false, status: 422 });
      return;
    }
    setResult(null);
    startTransition(async () => {
      const actionResult = await decideContentAction(contentId, decision, reason);
      setResult(actionResult);
      if (actionResult.ok) {
        setReason("");
        router.refresh();
      }
    });
  }

  return (
    <section className={styles.island}>
      <h2 className={styles.subtitle}>{t("decisionTitle")}</h2>
      {blockRequired && <p className={styles.blockNote}>{t("blockRequiredNote")}</p>}
      <label className={styles.fieldLabel} htmlFor="reject-reason">
        {t("rejectReasonLabel")}
      </label>
      <textarea
        id="reject-reason"
        className={styles.textArea}
        rows={3}
        value={reason}
        maxLength={500}
        onChange={(event) => setReason(event.target.value)}
        placeholder={t("rejectReasonPlaceholder")}
      />
      <div className={styles.actionButtons}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending}
          onClick={() => run("approve")}
        >
          {t("approve")}
        </button>
        <button
          type="button"
          className={styles.dangerButton}
          disabled={pending}
          onClick={() => run("reject")}
        >
          {t("reject")}
        </button>
        <button
          type="button"
          className={styles.secondaryButton}
          disabled={pending}
          onClick={() => run("revise")}
        >
          {t("revise")}
        </button>
      </div>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok ? t("actionSuccess") : failureText(result)}
        </p>
      ) : null}
    </section>
  );
}

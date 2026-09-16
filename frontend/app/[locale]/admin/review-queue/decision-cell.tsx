"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";
import { decideCandidateAction, type CandidateDecision, type DecideActionResult } from "./actions";
import styles from "../admin.module.css";

type Mode = "idle" | "modify" | "reject";

type Failure = Extract<DecideActionResult, { ok: false }>;

export function DecisionCell({
  candidateId,
  riskLevel,
  initialPayload,
}: {
  candidateId: string;
  riskLevel: string;
  initialPayload: string;
}) {
  const t = useTranslations("admin.reviewQueue");
  const tAdmin = useTranslations("admin");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [mode, setMode] = useState<Mode>("idle");
  const [payloadText, setPayloadText] = useState(initialPayload);
  const [reason, setReason] = useState("");
  const [jsonError, setJsonError] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(result: Failure): string {
    if (result.status === "unconfigured") return tAdmin("unconfigured");
    if (result.status === "unknown") return tError("unknown");
    if (result.status === 422 && result.detail) return result.detail;
    return tError(String(result.status));
  }

  function run(decision: CandidateDecision, parsed?: unknown) {
    setMessage(null);
    startTransition(async () => {
      const result = await decideCandidateAction(candidateId, decision, parsed, reason);
      if (result.ok) {
        setMessage({ kind: "ok", text: t("decideSuccess") });
        setReason("");
        router.refresh();
      } else {
        setMessage({ kind: "err", text: failureText(result) });
      }
    });
  }

  function confirmDirect() {
    if (riskLevel === "critical" && !window.confirm(t("criticalConfirm"))) return;
    run("confirmed");
  }

  function submitModified() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(payloadText);
    } catch {
      setJsonError(true);
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setJsonError(true);
      return;
    }
    setJsonError(false);
    run("modified", parsed);
  }

  return (
    <div className={styles.decisionCell}>
      {mode === "idle" ? (
        <div className={styles.decideActions}>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={confirmDirect}
            disabled={pending}
          >
            {t("decideConfirm")}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => {
              setMode("modify");
              setJsonError(false);
              setMessage(null);
            }}
            disabled={pending}
          >
            {t("decideModify")}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => {
              setMode("reject");
              setMessage(null);
            }}
            disabled={pending}
          >
            {t("decideReject")}
          </button>
        </div>
      ) : null}

      {mode === "modify" ? (
        <div className={styles.decidePanel}>
          <label className={styles.decideField}>
            <span>{t("payloadReplacement")}</span>
            <textarea
              className={styles.jsonArea}
              rows={12}
              value={payloadText}
              onChange={(event) => setPayloadText(event.target.value)}
              disabled={pending}
              spellCheck={false}
            />
          </label>
          {jsonError ? <p className={styles.msgErr}>{t("invalidJson")}</p> : null}
          <label className={styles.decideField}>
            <span>{t("reasonField")}</span>
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={pending}
            />
          </label>
          <div className={styles.decideActions}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={submitModified}
              disabled={pending}
            >
              {t("submitDecision")}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => {
                setMode("idle");
                setPayloadText(initialPayload);
                setJsonError(false);
              }}
              disabled={pending}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {mode === "reject" ? (
        <div className={styles.decidePanel}>
          <label className={styles.decideField}>
            <span>{t("reasonField")}</span>
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={pending}
            />
          </label>
          <div className={styles.decideActions}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={() => run("rejected")}
              disabled={pending}
            >
              {t("submitReject")}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => setMode("idle")}
              disabled={pending}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {message ? (
        <p className={message.kind === "ok" ? styles.msgOk : styles.msgErr} role="status">
          {message.text}
        </p>
      ) : null}
    </div>
  );
}

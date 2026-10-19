"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { opsTransitionIntakeAction, type OpsIntakeActionResult } from "./actions";
import { OPS_INTAKE_EVENTS, isOpsIntakeEvent } from "./ops-intake-codes";
import styles from "../admin.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function OpsIntakeActions({
  intakeId,
  allowedEvents,
}: {
  intakeId: string;
  allowedEvents: string[];
}) {
  const t = useTranslations("admin.opsIntakes");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [activeEvent, setActiveEvent] = useState<string | null>(null);
  const [result, setResult] = useState<OpsIntakeActionResult | null>(null);

  const opsEvents = allowedEvents.filter(isOpsIntakeEvent);

  function failureText(failure: Extract<OpsIntakeActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  // Q371：状态机按钮同 decision-cell 口径——本地 pending + try/catch/finally，
  // 异常必走错误回显（Q369 §6.2 静默失败同类根因一并消除）。
  async function run(event: string) {
    setResult(null);
    setActiveEvent(event);
    setPending(true);
    try {
      const actionResult = await opsTransitionIntakeAction(intakeId, event);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    } catch {
      setResult({ ok: false, status: "unknown" });
    } finally {
      setActiveEvent(null);
      setPending(false);
    }
  }

  if (opsEvents.length === 0) {
    return <p className={styles.notice}>{t("noOpsActions")}</p>;
  }

  return (
    <div className={styles.decisionCell}>
      <div className={styles.decideActions}>
        {OPS_INTAKE_EVENTS.filter((event) => opsEvents.includes(event)).map((event) => (
          <button
            key={event}
            type="button"
            className={styles.primaryButton}
            disabled={pending}
            onClick={() => run(event)}
          >
            {t(`eventLabels.${event}`)}
          </button>
        ))}
      </div>
      {result ? (
        <p
          className={result.ok ? styles.msgOk : styles.msgErr}
          role="status"
        >
          {result.ok ? t("actionSuccess") : failureText(result)}
        </p>
      ) : null}
      {pending && activeEvent ? <p className={styles.notice}>{t("actionPending")}</p> : null}
    </div>
  );
}

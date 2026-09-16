"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { transitionIntakeAction, type IntakeActionResult } from "./actions";
import { CUSTOMER_INTAKE_EVENTS, isCustomerIntakeEvent } from "./intake-codes";
import styles from "./products.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function IntakeActions({
  intakeId,
  allowedEvents,
}: {
  intakeId: string;
  allowedEvents: string[];
}) {
  const t = useTranslations("products");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [activeEvent, setActiveEvent] = useState<string | null>(null);
  const [result, setResult] = useState<IntakeActionResult | null>(null);

  const customerEvents = allowedEvents.filter(isCustomerIntakeEvent);

  function failureText(failure: Extract<IntakeActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.missingFids && failure.missingFids.length > 0)
      return t("missingFields", { fids: failure.missingFids.join("、") });
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function run(event: string) {
    setResult(null);
    setActiveEvent(event);
    startTransition(async () => {
      const actionResult = await transitionIntakeAction(intakeId, event);
      if (actionResult.ok) {
        setResult(actionResult);
        router.refresh();
      } else {
        setResult(actionResult);
      }
      setActiveEvent(null);
    });
  }

  if (customerEvents.length === 0) {
    return <p className={styles.notice}>{t("noCustomerActions")}</p>;
  }

  return (
    <div className={styles.actions}>
      <div className={styles.actionButtons}>
        {CUSTOMER_INTAKE_EVENTS.filter((event) => customerEvents.includes(event)).map(
          (event) => (
            <button
              key={event}
              type="button"
              className={styles.primaryButton}
              disabled={pending}
              onClick={() => run(event)}
            >
              {t(`eventLabels.${event}`)}
            </button>
          ),
        )}
      </div>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok ? t("actionSuccess") : failureText(result)}
        </p>
      ) : null}
      {pending && activeEvent ? <p className={styles.notice}>{t("actionPending")}</p> : null}
    </div>
  );
}

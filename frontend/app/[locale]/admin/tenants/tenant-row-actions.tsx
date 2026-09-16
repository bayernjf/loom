"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";
import {
  changePlanAction,
  pauseTenantAction,
  resumeTenantAction,
  type TenantActionResult,
} from "./actions";
import { TENANT_PLANS } from "./tenant-codes";
import styles from "../admin.module.css";

type Failure = Extract<TenantActionResult, { ok: false }>;

export function TenantRowActions({
  tenantId,
  currentPlan,
  status,
}: {
  tenantId: string;
  currentPlan: string;
  status: string;
}) {
  const t = useTranslations("admin.tenants");
  const tAdmin = useTranslations("admin");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [plan, setPlan] = useState(currentPlan);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(result: Failure): string {
    if (result.status === "unconfigured") return tAdmin("unconfigured");
    if (result.status === "unknown") return tError("unknown");
    if (result.status === 422 && result.detail) return result.detail;
    return tError(String(result.status));
  }

  function run(action: Promise<TenantActionResult>) {
    setMessage(null);
    startTransition(async () => {
      const result = await action;
      if (result.ok) {
        setMessage({ kind: "ok", text: t("actionSuccess") });
        router.refresh();
      } else {
        setMessage({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <div className={styles.decisionCell}>
      <div className={styles.decideActions}>
        <select
          value={plan}
          onChange={(event) => setPlan(event.target.value)}
          disabled={pending}
          aria-label={t("changePlan")}
        >
          {TENANT_PLANS.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => run(changePlanAction(tenantId, plan))}
          disabled={pending || plan === currentPlan}
        >
          {t("changePlan")}
        </button>
        {status === "paused" ? (
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => run(resumeTenantAction(tenantId))}
            disabled={pending}
          >
            {t("resume")}
          </button>
        ) : (
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => run(pauseTenantAction(tenantId))}
            disabled={pending}
          >
            {t("pause")}
          </button>
        )}
      </div>
      {message ? (
        <p className={message.kind === "ok" ? styles.msgOk : styles.msgErr} role="status">
          {message.text}
        </p>
      ) : null}
    </div>
  );
}

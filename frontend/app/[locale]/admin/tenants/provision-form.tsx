"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";
import { provisionTenantAction, type TenantActionResult } from "./actions";
import { TENANT_PLANS } from "./tenant-codes";
import styles from "../admin.module.css";

type Failure = Extract<TenantActionResult, { ok: false }>;

export function ProvisionTenantForm() {
  const t = useTranslations("admin.tenants");
  const tAdmin = useTranslations("admin");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [tenantId, setTenantId] = useState("");
  const [name, setName] = useState("");
  const [plan, setPlan] = useState<string>("trial");
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(result: Failure): string {
    if (result.status === "unconfigured") return tAdmin("unconfigured");
    if (result.status === "unknown") return tError("unknown");
    if (result.status === 422 && result.detail) return result.detail;
    return tError(String(result.status));
  }

  function submit() {
    setMessage(null);
    startTransition(async () => {
      const result = await provisionTenantAction(tenantId, name, plan);
      if (result.ok) {
        setMessage({ kind: "ok", text: t("provisionSuccess") });
        setTenantId("");
        setName("");
        setPlan("trial");
        router.refresh();
      } else {
        setMessage({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <form
      className={styles.provisionForm}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h2 className={styles.sectionTitle}>{t("provisionTitle")}</h2>
      <div className={styles.provisionFields}>
        <label className={styles.decideField}>
          <span>{t("tenantId")}</span>
          <input
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            disabled={pending}
            required
            spellCheck={false}
          />
        </label>
        <label className={styles.decideField}>
          <span>{t("nameOptional")}</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={pending}
          />
        </label>
        <label className={styles.decideField}>
          <span>{t("plan")}</span>
          <select
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            disabled={pending}
          >
            {TENANT_PLANS.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className={styles.decideActions}>
        <button type="submit" className={styles.primaryButton} disabled={pending}>
          {t("provisionSubmit")}
        </button>
      </div>
      {message ? (
        <p className={message.kind === "ok" ? styles.msgOk : styles.msgErr} role="status">
          {message.text}
        </p>
      ) : null}
    </form>
  );
}

"use client";

// Q178：签发内部运营 PAT 岛——填人员 ID/姓名并勾选内部角色；secret 明文仅此一次
// 返回，页面提示立即复制；成功后刷新 RSC 列表，secret 仅本次驻留在岛状态内。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  issueStaffKeyAction,
  STAFF_ROLE_CODES,
  type StaffKeyActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([400, 401, 403, 404, 409, 422]);

export function IssueStaffKeyIsland() {
  const t = useTranslations("admin.staffKeys");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [staffId, setStaffId] = useState("");
  const [staffName, setStaffName] = useState("");
  const [roles, setRoles] = useState<string[]>([]);
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [result, setResult] = useState<StaffKeyActionResult | null>(null);

  function toggleRole(role: string) {
    setRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  }

  function failureText(failure: Extract<StaffKeyActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (typeof failure.status === "number" && failure.status === 422 && failure.detail)
      return failure.detail;
    if (typeof failure.status === "number" && KNOWN_STATUSES.has(failure.status))
      return tError(String(failure.status));
    return tError("unknown");
  }

  function submit() {
    setResult(null);
    setSecret(null);
    startTransition(async () => {
      const actionResult = await issueStaffKeyAction(staffId, staffName, roles);
      setResult(actionResult);
      if (actionResult.ok) {
        setSecret(actionResult.secret ?? "");
        setStaffId("");
        setStaffName("");
        setRoles([]);
        router.refresh();
      }
    });
  }

  const canSubmit =
    staffId.trim().length > 0 &&
    staffName.trim().length > 0 &&
    roles.length > 0 &&
    !pending;

  return (
    <section className={styles.section} data-testid="issue-staff-key">
      <h2 className={styles.sectionTitle}>{t("issueTitle")}</h2>
      <div className={styles.provisionForm}>
        <input
          type="text"
          className={styles.jsonArea}
          aria-label={t("staffIdLabel")}
          placeholder={t("staffIdPlaceholder")}
          value={staffId}
          maxLength={64}
          onChange={(event) => setStaffId(event.target.value)}
        />
        <input
          type="text"
          className={styles.jsonArea}
          aria-label={t("staffNameLabel")}
          placeholder={t("staffNamePlaceholder")}
          value={staffName}
          maxLength={128}
          onChange={(event) => setStaffName(event.target.value)}
        />
      </div>
      <fieldset className={styles.roleFieldset} data-testid="staff-roles">
        <legend className={styles.rolesLabel}>{t("rolesLabel")}</legend>
        {STAFF_ROLE_CODES.map((role) => (
          <label key={role} className={styles.roleCheck}>
            <input
              type="checkbox"
              value={role}
              checked={roles.includes(role)}
              onChange={() => toggleRole(role)}
            />
            <code>{role}</code>
          </label>
        ))}
      </fieldset>
      <div className={styles.provisionForm}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={!canSubmit}
          onClick={submit}
        >
          {t("issueSubmit")}
        </button>
      </div>

      {secret !== null && (
        <div className={styles.decidePanel} data-testid="issued-staff-secret">
          <p className={styles.msgErr}>{t("secretOnceWarning")}</p>
          <pre className={styles.payloadPre}>{secret}</pre>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => {
              navigator.clipboard
                .writeText(secret)
                .then(() => setCopied(true))
                .catch(() => setCopied(false));
            }}
          >
            {copied ? t("copied") : t("copySecret")}
          </button>
        </div>
      )}

      {result && !result.ok && (
        <p className={styles.msgErr} role="status">
          {failureText(result)}
        </p>
      )}
    </section>
  );
}

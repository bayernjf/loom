"use client";

// Q167：签发 Agent Key 岛——secret 明文仅此一次返回，页面提示立即复制；
// 成功后刷新 RSC 列表（新 Key 以 active 入列），secret 仅本次驻留在岛状态内。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  issueAgentKeyAction,
  type AgentKeyActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function IssueKeyIsland() {
  const t = useTranslations("admin.agentKeys");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [result, setResult] = useState<AgentKeyActionResult | null>(null);

  function failureText(failure: Extract<AgentKeyActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function submit() {
    setResult(null);
    setSecret(null);
    startTransition(async () => {
      const actionResult = await issueAgentKeyAction(name);
      setResult(actionResult);
      if (actionResult.ok) {
        setSecret(actionResult.secret ?? "");
        setName("");
        router.refresh();
      }
    });
  }

  async function copySecret() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className={styles.section} data-testid="issue-agent-key">
      <h2 className={styles.sectionTitle}>{t("issueTitle")}</h2>
      <div className={styles.provisionForm}>
        <input
          type="text"
          className={styles.jsonArea}
          aria-label={t("nameLabel")}
          placeholder={t("namePlaceholder")}
          value={name}
          maxLength={128}
          onChange={(event) => setName(event.target.value)}
        />
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending || name.trim().length === 0}
          onClick={submit}
        >
          {t("issueSubmit")}
        </button>
      </div>

      {secret !== null && (
        <div className={styles.decidePanel} data-testid="issued-secret">
          <p className={styles.msgErr}>{t("secretOnceWarning")}</p>
          <pre className={styles.payloadPre}>{secret}</pre>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={copySecret}
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

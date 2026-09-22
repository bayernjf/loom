"use client";

// Q167：吊销 Agent Key 按钮（终态、幂等）；吊销确认后调 Server Action，
// 成功 router.refresh。已吊销行禁用。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  revokeAgentKeyAction,
  type AgentKeyActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function RevokeKeyButton({
  keyId,
  name,
  revoked,
}: {
  keyId: string;
  name: string;
  revoked: boolean;
}) {
  const t = useTranslations("admin.agentKeys");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function failureText(failure: Extract<AgentKeyActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function confirmRevoke() {
    if (!window.confirm(t("revokeConfirm", { name }))) return;
    setError(null);
    startTransition(async () => {
      const result = await revokeAgentKeyAction(keyId);
      if (result.ok) {
        router.refresh();
      } else {
        setError(failureText(result));
      }
    });
  }

  return (
    <span>
      <button
        type="button"
        className={styles.secondaryButton}
        disabled={pending || revoked}
        onClick={confirmRevoke}
      >
        {revoked ? t("statusRevoked") : t("revokeSubmit")}
      </button>
      {error && (
        <span className={styles.msgErr} role="status">
          {error}
        </span>
      )}
    </span>
  );
}

"use client";

// Q178：吊销内部运营 PAT 按钮（终态、幂等）；确认后调 Server Action，成功 refresh。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  revokeStaffKeyAction,
  type StaffKeyActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([400, 401, 403, 404, 409, 422]);

export function RevokeStaffKeyButton({
  keyId,
  staffName,
  revoked,
}: {
  keyId: string;
  staffName: string;
  revoked: boolean;
}) {
  const t = useTranslations("admin.staffKeys");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

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

  function confirmRevoke() {
    if (!window.confirm(t("revokeConfirm", { name: staffName }))) return;
    setError(null);
    startTransition(async () => {
      const result = await revokeStaffKeyAction(keyId);
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

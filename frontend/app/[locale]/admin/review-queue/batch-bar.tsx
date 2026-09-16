"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition, type FormEvent } from "react";
import type { BatchApproveActionResult } from "./actions";
import { batchApproveAction } from "./actions";
import styles from "../admin.module.css";

const ERROR_STATUSES = [403, 404, 409, 422] as const;

export function BatchBar() {
  const t = useTranslations("admin.reviewQueue");
  const tAdmin = useTranslations("admin");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ids = Array.from(
      document.querySelectorAll<HTMLInputElement>("input[data-batch-candidate]:checked"),
    ).map((input) => input.value);
    if (ids.length === 0) {
      setMessage({ kind: "err", text: t("selectFirst") });
      return;
    }
    setMessage(null);
    startTransition(async () => {
      const result: BatchApproveActionResult = await batchApproveAction(ids, reason);
      if (result.ok) {
        setMessage({ kind: "ok", text: t("batchSuccess", { count: result.count }) });
        setReason("");
        router.refresh();
      } else if (result.status === "unconfigured") {
        setMessage({ kind: "err", text: tAdmin("unconfigured") });
      } else if (result.status === "unknown") {
        setMessage({ kind: "err", text: tError("unknown") });
      } else {
        const key = String(result.status) as "403" | "404" | "409" | "422";
        setMessage({
          kind: "err",
          text: ERROR_STATUSES.includes(result.status as (typeof ERROR_STATUSES)[number])
            ? tError(key)
            : tError("unknown"),
        });
      }
    });
  }

  return (
    <form className={styles.batchBar} onSubmit={onSubmit}>
      <input
        className={styles.batchReason}
        type="text"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder={t("batchReason")}
        disabled={pending}
      />
      <button className={styles.primaryButton} type="submit" disabled={pending}>
        {t("batchApprove")}
      </button>
      {message ? (
        <p className={message.kind === "ok" ? styles.msgOk : styles.msgErr} role="status">
          {message.text}
        </p>
      ) : null}
    </form>
  );
}

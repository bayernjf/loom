"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { updateDraftProfileAction, type IntakeActionResult } from "./actions";
import styles from "./products.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function DraftProfileForm({
  intakeId,
  currentName,
}: {
  intakeId: string;
  currentName: string;
}) {
  const t = useTranslations("products");
  const tNew = useTranslations("products.new");
  const tError = useTranslations("error");
  const router = useRouter();
  const [name, setName] = useState(currentName);
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<IntakeActionResult | null>(null);

  function failureText(failure: Extract<IntakeActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || name.trim().length > 100) {
      return;
    }
    setResult(null);
    startTransition(async () => {
      const actionResult = await updateDraftProfileAction(intakeId, name);
      if (actionResult.ok) {
        setResult(actionResult);
        router.refresh();
      } else {
        setResult(actionResult);
      }
    });
  }

  return (
    <form className={styles.form} onSubmit={onSubmit}>
      <label className={styles.fieldLabel} htmlFor={`draft-name-${intakeId}`}>
        {tNew("nameLabel")}
      </label>
      <input
        id={`draft-name-${intakeId}`}
        type="text"
        required
        maxLength={100}
        className={styles.textInput}
        value={name}
        spellCheck={false}
        disabled={pending}
        onChange={(event) => setName(event.target.value)}
      />
      <p className={styles.fieldNote}>{tNew("profileKeyNote")}</p>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok ? t("profileSaved") : failureText(result)}
        </p>
      ) : null}
      <button type="submit" className={styles.primaryButton} disabled={pending}>
        {pending ? t("actionPending") : t("saveProfile")}
      </button>
    </form>
  );
}

"use client";

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { createProductAction } from "./actions";
import styles from "./products.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function NewProductForm() {
  const t = useTranslations("products.new");
  const te = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!String(form.get("productName") ?? "").trim()) {
      setErrorStatus(422);
      return;
    }
    setErrorStatus(null);
    startTransition(async () => {
      const result = await createProductAction(form);
      if (result.ok) {
        router.push(`/products/${result.id}`);
      } else {
        setErrorStatus(result.status);
      }
    });
  }

  return (
    <form className={styles.form} onSubmit={onSubmit}>
      <label className={styles.fieldLabel} htmlFor="productName">
        {t("nameLabel")}
      </label>
      <input
        id="productName"
        name="productName"
        type="text"
        required
        maxLength={100}
        className={styles.textInput}
        placeholder={t("namePlaceholder")}
        onChange={() => setErrorStatus(null)}
      />
      <p className={styles.fieldNote}>{t("profileKeyNote")}</p>
      {errorStatus !== null && (
        <p className={styles.errorText} role="alert">
          {te(KNOWN_STATUSES.has(errorStatus) ? String(errorStatus) : "unknown")}
        </p>
      )}
      <button type="submit" className={styles.primaryButton} disabled={pending}>
        {pending ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}

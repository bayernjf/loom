"use client";

// B3/Q122：段1 录入详情页的产品目标语言控件（Q58 语言交集的产品侧）。
// active 语言多选；空选择 = 未声明（不收窄交集）。仅经同源 Server Action，
// 成功后 router.refresh；client 岛不直连服务端访问层。

import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { setTargetLanguagesAction, type IntakeActionResult } from "./actions";
import styles from "./products.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export interface LanguageOption {
  code: string;
  name: string;
}

export function TargetLanguagesForm({
  intakeId,
  initial,
  options,
}: {
  intakeId: string;
  initial: string[];
  options: LanguageOption[];
}) {
  const t = useTranslations("products");
  const tError = useTranslations("error");
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set(initial));
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<IntakeActionResult | null>(null);

  function failureText(failure: Extract<IntakeActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function toggle(code: string) {
    setResult(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResult(null);
    const languages = options
      .map((option) => option.code)
      .filter((code) => selected.has(code));
    startTransition(async () => {
      const actionResult = await setTargetLanguagesAction(intakeId, languages);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    });
  }

  return (
    <form className={styles.form} onSubmit={onSubmit}>
      <p className={styles.fieldNote}>{t("targetLanguages.note")}</p>
      <ul className={styles.languageList}>
        {options.map((option) => (
          <li key={option.code}>
            <label className={styles.languageOption}>
              <input
                type="checkbox"
                checked={selected.has(option.code)}
                disabled={pending}
                onChange={() => toggle(option.code)}
              />
              <span>{option.name}</span>
              <span className={styles.mono}>{option.code}</span>
            </label>
          </li>
        ))}
      </ul>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok ? t("targetLanguages.saved") : failureText(result)}
        </p>
      ) : null}
      <button type="submit" className={styles.primaryButton} disabled={pending}>
        {pending ? t("actionPending") : t("targetLanguages.save")}
      </button>
    </form>
  );
}

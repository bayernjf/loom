"use client";

// Q56-a/Q122：revising 态客户人工编辑岛——直接改正文提交，后端重过词库与语义
// 复检、ARTICLE-QC 后回 review（不调 ARTICLE-GEN、不占重生成次数）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { saveContentBodyAction, type ContentActionResult } from "./actions";
import styles from "./content.module.css";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function BodyEditIsland({
  contentId,
  initialBody,
}: {
  contentId: string;
  initialBody: string;
}) {
  const t = useTranslations("content");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [body, setBody] = useState(initialBody);
  const [result, setResult] = useState<ContentActionResult | null>(null);

  function failureText(failure: Extract<ContentActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function submit() {
    if (!body.trim()) {
      setResult({ ok: false, status: 422 });
      return;
    }
    setResult(null);
    startTransition(async () => {
      const actionResult = await saveContentBodyAction(contentId, body);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    });
  }

  return (
    <section className={styles.island}>
      <h2 className={styles.subtitle}>{t("editTitle")}</h2>
      <p className={styles.editNote}>{t("editNote")}</p>
      <textarea
        className={styles.textArea}
        rows={14}
        value={body}
        maxLength={20000}
        onChange={(event) => setBody(event.target.value)}
      />
      <div className={styles.actionButtons}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending || !body.trim()}
          onClick={submit}
        >
          {t("submitEdit")}
        </button>
      </div>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok ? t("editSuccess") : failureText(result)}
        </p>
      ) : null}
    </section>
  );
}

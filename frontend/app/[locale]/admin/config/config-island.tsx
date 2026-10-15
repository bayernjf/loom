"use client";

// Q364（Q56 配置功能页）：content.regen_limit 编辑岛。输入为正整数（最小 1，与种子
// validation 同口径），值未变化时不发请求；成功 router.refresh() 让 RSC 重读当前值
// 与版本元信息。只调 Server Action，禁直连 lib/api 与裸 fetch。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  updateRegenLimitAction,
  type ConfigActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 422]);

export function RegenLimitConfigIsland({ current }: { current: number }) {
  const t = useTranslations("admin.systemConfig");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [limitText, setLimitText] = useState(String(current));
  const [changeNote, setChangeNote] = useState("");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null,
  );

  const parsed = Number(limitText);
  const valid = Number.isInteger(parsed) && parsed >= 1;
  const unchanged = valid && parsed === current;

  function failureText(failure: Extract<ConfigActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function submit() {
    setFeedback(null);
    if (!valid) {
      setFeedback({ kind: "err", text: t("invalidLimit") });
      return;
    }
    startTransition(async () => {
      const result = await updateRegenLimitAction({
        limit: parsed,
        changeNote,
      });
      if (result.ok) {
        setFeedback({ kind: "ok", text: t("saved") });
        setChangeNote("");
        router.refresh();
      } else {
        setFeedback({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <div className={styles.provisionForm} data-testid="regen-limit-config">
      <label className={styles.decideField}>
        {t("regenLimitLabel")}
        <input
          className={styles.batchReason}
          type="number"
          min={1}
          step={1}
          value={limitText}
          aria-describedby="regen-limit-hint"
          onChange={(event) => setLimitText(event.target.value)}
        />
      </label>
      <p id="regen-limit-hint" className={styles.notice}>
        {t("regenLimitHint")}
      </p>
      <label className={styles.decideField}>
        {t("changeNoteLabel")}
        <input
          className={styles.batchReason}
          type="text"
          value={changeNote}
          maxLength={200}
          placeholder={t("changeNotePlaceholder")}
          onChange={(event) => setChangeNote(event.target.value)}
        />
      </label>
      <button
        type="button"
        className={styles.primaryButton}
        disabled={pending || !valid || unchanged}
        onClick={submit}
      >
        {pending ? t("saving") : t("save")}
      </button>
      {feedback && (
        <p
          className={feedback.kind === "ok" ? styles.msgOk : styles.msgErr}
          role="status"
        >
          {feedback.text}
        </p>
      )}
    </div>
  );
}

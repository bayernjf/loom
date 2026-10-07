"use client";

// Q308：17 池选项字典的行内编辑岛。池名本身不可在界面增删——那 17 个键是 Q40 权重校验器
// 认的闭合集，加第 18 个池要先改 PCP 口径；界面回填的是每池的可选值（逗号分隔）。
// 重复值由后端挡（422），这里把它的 detail 原样显示出来。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import { archivePoolAction, savePoolOptionsAction, type PoolActionResult } from "./actions";

const KNOWN_STATUSES = new Set([401, 403, 404, 422]);

function splitOptions(text: string): string[] {
  return text
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function PoolOptionEditIsland({
  pool,
  options,
  archived,
}: {
  pool: string;
  options: string[];
  archived: boolean;
}) {
  const t = useTranslations("admin.dictionaries");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(options.join("，"));
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(failure: Extract<PoolActionResult, { ok: false }>): string {
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 401) return t("needStaffToken");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown");
  }

  function save() {
    setFeedback(null);
    startTransition(async () => {
      const result = await savePoolOptionsAction({ pool, options: splitOptions(draft) });
      if (result.ok) {
        setFeedback({ kind: "ok", text: t("saved") });
        setOpen(false);
        router.refresh();
      } else {
        setFeedback({ kind: "err", text: failureText(result) });
      }
    });
  }

  function archive() {
    if (!window.confirm(t("archivePoolConfirm", { pool }))) return;
    setFeedback(null);
    startTransition(async () => {
      const result = await archivePoolAction(pool);
      if (result.ok) {
        setFeedback({ kind: "ok", text: t("archiveDone") });
        router.refresh();
      } else {
        setFeedback({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <span className={styles.decideActions} data-testid={`pool-option-${pool}`}>
      {open ? (
        <span className={styles.decidePanel}>
          <label className={styles.decideField}>
            {t("colOptions")}
            <input
              className={styles.batchReason}
              value={draft}
              placeholder={t("optionsPlaceholder")}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <span>
            <button type="button" className={styles.primaryButton} disabled={pending} onClick={save}>
              {t("save")}
            </button>{" "}
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={pending}
              onClick={() => {
                setOpen(false);
                setDraft(options.join("，"));
              }}
            >
              {t("cancel")}
            </button>
          </span>
        </span>
      ) : (
        <span>
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={pending}
            onClick={() => setOpen(true)}
          >
            {t("edit")}
          </button>
          {!archived && (
            <>
              {" "}
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={pending}
                onClick={archive}
              >
                {t("archive")}
              </button>
            </>
          )}
        </span>
      )}
      {feedback && (
        <span className={feedback.kind === "ok" ? styles.msgOk : styles.msgErr} role="status">
          {feedback.text}
        </span>
      )}
    </span>
  );
}

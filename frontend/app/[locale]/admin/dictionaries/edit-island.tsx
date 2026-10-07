"use client";

// Q306：降级动作字典的行内编辑岛。六码本身不可在界面增删（它们是裁决原文的枚举码），
// 界面补的是中文名与「为什么用这个动作」——保存后 router.refresh() 让 RSC 重读，
// 行内立刻看到回填结果；失败按状态分开报（401 是没人员令牌，不是"没权限"）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  archiveDowngradeActionAction,
  saveDowngradeActionAction,
  type DowngradeActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([401, 403, 404, 422]);

export function DowngradeActionEditIsland({
  code,
  name,
  why,
  archived,
}: {
  code: string;
  name: string;
  why: string;
  archived: boolean;
}) {
  const t = useTranslations("admin.dictionaries");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [draftName, setDraftName] = useState(name);
  const [draftWhy, setDraftWhy] = useState(why);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(failure: Extract<DowngradeActionResult, { ok: false }>): string {
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 401) return t("needStaffToken");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown");
  }

  function save() {
    setFeedback(null);
    startTransition(async () => {
      const result = await saveDowngradeActionAction({
        code,
        name: draftName,
        why: draftWhy,
      });
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
    if (!window.confirm(t("archiveConfirm", { code }))) return;
    setFeedback(null);
    startTransition(async () => {
      const result = await archiveDowngradeActionAction(code);
      if (result.ok) {
        setFeedback({ kind: "ok", text: t("archiveDone") });
        router.refresh();
      } else {
        setFeedback({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <span className={styles.decideActions} data-testid={`downgrade-action-${code}`}>
      {open ? (
        <span className={styles.decidePanel}>
          <label className={styles.decideField}>
            {t("colName")}
            <input
              className={styles.batchReason}
              value={draftName}
              maxLength={64}
              placeholder={t("namePlaceholder")}
              onChange={(e) => setDraftName(e.target.value)}
            />
          </label>
          <label className={styles.decideField}>
            {t("colWhy")}
            <input
              className={styles.batchReason}
              value={draftWhy}
              maxLength={256}
              placeholder={t("whyPlaceholder")}
              onChange={(e) => setDraftWhy(e.target.value)}
            />
          </label>
          <span>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={pending}
              onClick={save}
            >
              {t("save")}
            </button>{" "}
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={pending}
              onClick={() => {
                setOpen(false);
                setDraftName(name);
                setDraftWhy(why);
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
        <span
          className={feedback.kind === "ok" ? styles.msgOk : styles.msgErr}
          role="status"
        >
          {feedback.text}
        </span>
      )}
    </span>
  );
}

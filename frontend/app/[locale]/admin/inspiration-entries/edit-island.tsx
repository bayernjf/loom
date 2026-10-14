"use client";

// Q359：灵感条行内操作岛——编辑（content/tags/enabled，enabled 勾选即启停）与
// 删除（终态，window.confirm 确认）。保存/删除成功 router.refresh() 让 RSC 重读；
// 失败按状态分开报（401 时 request 层已跳登录，这里只见 403/404/409/422 族）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  deleteInspirationEntryAction,
  updateInspirationEntryAction,
  type InspirationActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function EntryRowActions({
  entryId,
  content,
  tags,
  enabled,
}: {
  entryId: string;
  content: string;
  tags: string[];
  enabled: boolean;
}) {
  const t = useTranslations("admin.inspirationEntries");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [draftContent, setDraftContent] = useState(content);
  const [draftTags, setDraftTags] = useState(tags.join(", "));
  const [draftEnabled, setDraftEnabled] = useState(enabled);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function failureText(failure: Extract<InspirationActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function save() {
    setFeedback(null);
    startTransition(async () => {
      const result = await updateInspirationEntryAction(entryId, {
        content: draftContent,
        tags: draftTags
          .split(/[,，]/)
          .map((tag) => tag.trim())
          .filter(Boolean),
        enabled: draftEnabled,
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

  function remove() {
    if (!window.confirm(t("deleteConfirm", { id: entryId.slice(0, 8) }))) return;
    setFeedback(null);
    startTransition(async () => {
      const result = await deleteInspirationEntryAction(entryId);
      if (result.ok) {
        setFeedback({ kind: "ok", text: t("deleted") });
        router.refresh();
      } else {
        setFeedback({ kind: "err", text: failureText(result) });
      }
    });
  }

  return (
    <span className={styles.decideActions} data-testid={`inspiration-entry-${entryId.slice(0, 8)}`}>
      {open ? (
        <span className={styles.decidePanel}>
          <label className={styles.decideField}>
            {t("contentLabel")}
            <textarea
              className={styles.jsonArea}
              value={draftContent}
              maxLength={2000}
              onChange={(event) => setDraftContent(event.target.value)}
            />
          </label>
          <label className={styles.decideField}>
            {t("tagsLabel")}
            <input
              className={styles.batchReason}
              value={draftTags}
              maxLength={256}
              placeholder={t("tagsPlaceholder")}
              onChange={(event) => setDraftTags(event.target.value)}
            />
          </label>
          <label className={styles.decideField}>
            <input
              type="checkbox"
              checked={draftEnabled}
              onChange={(event) => setDraftEnabled(event.target.checked)}
            />{" "}
            {t("stateEnabled")}
          </label>
          <span>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={pending || draftContent.trim().length === 0}
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
                setDraftContent(content);
                setDraftTags(tags.join(", "));
                setDraftEnabled(enabled);
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
          </button>{" "}
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={pending}
            onClick={remove}
          >
            {t("deleteSubmit")}
          </button>
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

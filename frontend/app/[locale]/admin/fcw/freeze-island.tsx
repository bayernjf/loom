"use client";

// Q321：冻结管理专用岛（D3.5 第 6 项产品面，Q251 冻结引擎已闭环后的 UI 片）。
// 行内展示当前快照冻结状态（frozen=生效可作废／revoked=已作废含时间与原因／
// 无快照），frozen 时提供「作废」操作（reason 必填，走 Server Action 调
// POST /api/admin/fcw/{final_id}/revoke，operations 写闸）。作废成功只留痕并
// 提示「重冻新版走组装台『复用』预填」（Q250 裁决 c＝E1.1 再发证，本岛不跳转、
// 不刷新列表、不做任何其它写操作）。
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { Link } from "@/i18n/navigation";
import styles from "../admin.module.css";
import { revokeFcwAction, type RevokeFcwResult } from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function FreezeIsland({
  finalId,
  snapshotStatus,
  snapshotRevokedAt,
  revokeReason,
}: {
  finalId: string;
  snapshotStatus: string | null;
  snapshotRevokedAt: string | null;
  revokeReason: string | null;
}) {
  const t = useTranslations("admin.fcw");
  const tError = useTranslations("error");
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<RevokeFcwResult | null>(null);
  const [revoked, setRevoked] = useState(false);

  const frozen = snapshotStatus === "frozen" && !revoked;

  function failureText(r: Extract<RevokeFcwResult, { ok: false }>): string {
    if (r.status === "unconfigured") return t("actorUnconfigured");
    if (r.status === "missing_role") return t("revokeMissingRole");
    if (r.status === "unknown") return tError("unknown");
    if (r.status === 422 && r.detail) return r.detail;
    return tError(
      KNOWN_STATUSES.has(Number(r.status)) ? String(r.status) : "unknown",
    );
  }

  function confirmRevoke() {
    if (!frozen || !reason.trim() || pending) return;
    startTransition(async () => {
      const r = await revokeFcwAction(finalId, reason);
      if (r.ok) {
        setRevoked(true);
        setOpen(false);
      } else {
        setResult(r);
      }
    });
  }

  return (
    <>
      {snapshotStatus === null ? (
        <span className={styles.metaLine}>—</span>
      ) : (
        <span
          className={`${styles.chip} ${
            snapshotStatus === "frozen" && !revoked ? styles.chipActive : ""
          }`}
          data-testid="fcw-freeze-status"
        >
          {snapshotStatus === "frozen" && !revoked
            ? t("snapshotFrozen")
            : t("snapshotRevoked")}
        </span>
      )}
      {frozen ? (
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          data-testid="fcw-revoke-toggle"
        >
          {t("revoke")}
        </button>
      ) : null}
      {open ? (
        <div className={styles.tableWrap} data-testid="fcw-revoke-form">
          <label className={styles.filterField}>
            <span>{t("revokeReasonLabel")}</span>
            <textarea
              name="revoke_reason"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t("revokeReasonPlaceholder")}
              data-testid="fcw-revoke-reason"
            />
          </label>
          <div className={styles.actionsRow}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={confirmRevoke}
              disabled={!reason.trim() || pending}
              data-testid="fcw-revoke-confirm"
            >
              {pending ? t("revoking") : t("revokeConfirm")}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => setOpen(false)}
              disabled={pending}
            >
              {t("cancel")}
            </button>
          </div>
          {result !== null && !result.ok ? (
            <p className={styles.msgErr} role="status">
              {failureText(result)}
            </p>
          ) : null}
        </div>
      ) : null}
      {!frozen && snapshotStatus === "revoked" ? (
        <p className={styles.metaLine} data-testid="fcw-revoked-note">
          {t("revokedAt", { at: snapshotRevokedAt ?? "—" })}
          {revokeReason ? ` · ${revokeReason}` : ""}
          <br />
          <Link href={{ pathname: "/admin/fcw/assemble" }}>
            {t("reassembleHint")}
          </Link>
        </p>
      ) : null}
    </>
  );
}

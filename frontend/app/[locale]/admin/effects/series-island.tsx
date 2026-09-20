"use client";

// Q126/Q129/Q130：成品效果时序查询岛 + 已认领映射解绑入口。
// 查询/解绑均走同源 Server Action；解绑为撤销人工判断的动作，须 window.confirm。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import type { EffectRecordView } from "./actions";
import styles from "../admin.module.css";
import {
  queryEffectSeriesAction,
  unclaimEffectAction,
  type EffectActionResult,
  type EffectSeriesResult,
} from "./actions";
import { METRIC_FIELDS, capturedAtText, metricText } from "./effect-fields";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function SeriesQueryIsland() {
  const t = useTranslations("admin.effects");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [contentId, setContentId] = useState("");
  const [rows, setRows] = useState<EffectRecordView[] | null>(null);
  const [queriedId, setQueriedId] = useState("");
  const [result, setResult] = useState<EffectActionResult | null>(null);

  function failureText(
    failure: Extract<EffectSeriesResult | EffectActionResult, { ok: false }>,
  ): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if ("detail" in failure && failure.status === 422 && failure.detail)
      return failure.detail;
    return tError(
      KNOWN_STATUSES.has(Number(failure.status)) ? String(failure.status) : "unknown",
    );
  }

  function query(id: string) {
    const cid = (id ?? contentId).trim();
    if (!cid) return;
    setResult(null);
    startTransition(async () => {
      const actionResult = await queryEffectSeriesAction(cid);
      if (actionResult.ok) {
        setRows(actionResult.rows);
        setQueriedId(cid);
        router.refresh();
      } else {
        setRows(null);
        setResult(actionResult);
      }
    });
  }

  function unclaim(externalContentId: string) {
    if (!window.confirm(t("unclaimConfirm"))) return;
    setResult(null);
    startTransition(async () => {
      const actionResult = await unclaimEffectAction(externalContentId);
      setResult(actionResult);
      if (actionResult.ok) query(queriedId);
    });
  }

  return (
    <>
      <form
        className={styles.provisionForm}
        action={() => query(contentId)}
        aria-label={t("seriesFormLabel")}
      >
        <div className={styles.provisionFields}>
          <input
            type="text"
            value={contentId}
            required
            placeholder={t("seriesInputPlaceholder")}
            aria-label={t("seriesInputLabel")}
            onChange={(event) => setContentId(event.target.value)}
          />
        </div>
        <button type="submit" className={styles.primaryButton} disabled={pending}>
          {t("seriesQuery")}
        </button>
      </form>

      {rows !== null ? (
        rows.length === 0 ? (
          <p className={styles.notice}>{t("seriesEmpty")}</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colCaptured")}</th>
                  <th>{t("colExternal")}</th>
                  <th>{t("colSource")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colMetrics")}</th>
                  <th>{t("colClaim")}</th>
                  <th>{t("colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.record_id}>
                    <td>{capturedAtText(row.captured_at)}</td>
                    <td>
                      <span className={styles.metaLine}>{row.content_id}</span>
                    </td>
                    <td>{row.source}</td>
                    <td>
                      <span className={styles.planChip}>
                        {t(`status.${row.status}`)}
                      </span>
                    </td>
                    <td>
                      <ul className={styles.detailList}>
                        {METRIC_FIELDS.filter(
                          (key) => row.metrics && key in row.metrics,
                        ).map((key) => (
                          <li key={key}>
                            {t(`metric.${key}`)}: {metricText(row.metrics, key)}
                          </li>
                        ))}
                        {!row.metrics || Object.keys(row.metrics).length === 0
                          ? "—"
                          : null}
                      </ul>
                    </td>
                    <td>
                      {row.claimed_by ? (
                        <span className={styles.metaLine}>
                          {t("claimedBy", { actor: row.claimed_by })}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {row.claimed_by ? (
                        <button
                          type="button"
                          className={styles.secondaryButton}
                          disabled={pending}
                          onClick={() => unclaim(row.content_id)}
                        >
                          {t("unclaimSubmit")}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}

      {result && !result.ok ? (
        <p className={styles.msgErr} role="status">
          {failureText(result)}
        </p>
      ) : null}
      {result?.ok ? (
        <p className={styles.msgOk} role="status">
          {t("unclaimSuccess")}
        </p>
      ) : null}
    </>
  );
}

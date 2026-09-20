"use client";

// Q127/Q129/Q130：孤儿队列认领岛——单条认领 + 勾选批量认领（整批 all-or-nothing）。
// 只读首屏数据由 RSC 传入；写操作只走同源 Server Action，成功后 router.refresh。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import type { EffectRecordView } from "./actions";
import styles from "../admin.module.css";
import {
  batchClaimEffectsAction,
  claimEffectAction,
  type EffectActionResult,
} from "./actions";
import { METRIC_FIELDS, capturedAtText, metricText } from "./effect-fields";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function OrphanTableIsland({ rows }: { rows: EffectRecordView[] }) {
  const t = useTranslations("admin.effects");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [result, setResult] = useState<EffectActionResult | null>(null);

  function failureText(failure: Extract<EffectActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "missing_role") return t("actorMissingRole");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function claimOne(recordId: string) {
    const contentId = (targets[recordId] ?? "").trim();
    if (!contentId) {
      setResult({ ok: false, status: 422, detail: null });
      return;
    }
    setResult(null);
    startTransition(async () => {
      const actionResult = await claimEffectAction(recordId, contentId);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    });
  }

  function claimChecked() {
    const items = rows
      .filter((row) => checked[row.record_id])
      .map((row) => ({
        record_id: row.record_id,
        content_id: (targets[row.record_id] ?? "").trim(),
      }));
    if (items.length === 0) {
      setResult({ ok: false, status: 422, detail: null });
      return;
    }
    if (items.some((item) => !item.content_id)) {
      setResult({ ok: false, status: 422, detail: null });
      return;
    }
    setResult(null);
    startTransition(async () => {
      const actionResult = await batchClaimEffectsAction(items);
      setResult(actionResult);
      if (actionResult.ok) router.refresh();
    });
  }

  if (rows.length === 0)
    return <p className={styles.notice}>{t("orphanEmpty")}</p>;

  const checkedCount = rows.filter((row) => checked[row.record_id]).length;

  return (
    <>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th aria-label={t("colSelect")} />
              <th>{t("colExternal")}</th>
              <th>{t("colSource")}</th>
              <th>{t("colPost")}</th>
              <th>{t("colCaptured")}</th>
              <th>{t("colMetrics")}</th>
              <th>{t("colTarget")}</th>
              <th>{t("colAction")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.record_id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={t("colSelect")}
                    checked={Boolean(checked[row.record_id])}
                    onChange={(event) =>
                      setChecked((prev) => ({
                        ...prev,
                        [row.record_id]: event.target.checked,
                      }))
                    }
                  />
                </td>
                <td>
                  <span className={styles.metaLine}>{row.content_id}</span>
                </td>
                <td>{row.source}</td>
                <td>
                  <span className={styles.metaLine}>{row.platform_post_id}</span>
                </td>
                <td>{capturedAtText(row.captured_at)}</td>
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
                  <input
                    type="text"
                    aria-label={t("targetPlaceholder")}
                    placeholder={t("targetPlaceholder")}
                    value={targets[row.record_id] ?? ""}
                    onChange={(event) =>
                      setTargets((prev) => ({
                        ...prev,
                        [row.record_id]: event.target.value,
                      }))
                    }
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={pending}
                    onClick={() => claimOne(row.record_id)}
                  >
                    {t("claimSubmit")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.batchBar}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending || checkedCount === 0}
          onClick={claimChecked}
        >
          {t("batchSubmit", { count: checkedCount })}
        </button>
      </div>
      {result ? (
        <p className={result.ok ? styles.msgOk : styles.msgErr} role="status">
          {result.ok
            ? t("claimSuccess")
            : failureText(result)}
        </p>
      ) : null}
    </>
  );
}

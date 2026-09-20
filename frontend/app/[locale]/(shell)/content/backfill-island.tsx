"use client";

// Q128/Q131：客户效果手工回填岛（内容详情页，非 discarded 成品均显示）。
// 走客户专用通道 POST /api/effects/backfill（无 Agent Key、绝不产生孤儿）；
// V1 仅单条手工录入，批量表格/CSV 随 V2。指标留空即缺席（绝不补 0）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import {
  backfillEffectAction,
  type BackfillActionResult,
} from "./actions";
import styles from "./content.module.css";

const COUNT_METRICS = [
  "plays",
  "likes",
  "comments",
  "shares",
  "inquiries",
  "conversions",
] as const;
const RATE_METRICS = ["read_rate"] as const;
const METRIC_KEYS = [...COUNT_METRICS, ...RATE_METRICS] as const;

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

const EMPTY_METRICS: Record<string, string> = {
  plays: "",
  likes: "",
  comments: "",
  shares: "",
  inquiries: "",
  conversions: "",
  read_rate: "",
};

export function BackfillIsland({ contentId }: { contentId: string }) {
  const t = useTranslations("content");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [platformPostId, setPlatformPostId] = useState("");
  const [capturedAt, setCapturedAt] = useState("");
  const [metrics, setMetrics] = useState<Record<string, string>>(EMPTY_METRICS);
  const [result, setResult] = useState<BackfillActionResult | null>(null);

  function failureText(failure: Extract<BackfillActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function submit() {
    if (!platformPostId.trim()) {
      setResult({ ok: false, status: 422, detail: t("backfillPostRequired") });
      return;
    }
    if (!capturedAt || Number.isNaN(new Date(capturedAt).getTime())) {
      setResult({ ok: false, status: 422, detail: t("backfillCapturedRequired") });
      return;
    }
    const parsed: Record<string, number> = {};
    for (const key of COUNT_METRICS) {
      const raw = metrics[key].trim();
      if (!raw) continue;
      const value = Number(raw);
      if (!Number.isInteger(value) || value < 0) {
        setResult({ ok: false, status: 422, detail: t("backfillMetricInteger") });
        return;
      }
      parsed[key] = value;
    }
    const rateRaw = metrics.read_rate.trim();
    if (rateRaw) {
      const rate = Number(rateRaw);
      if (Number.isNaN(rate) || rate < 0 || rate > 1) {
        setResult({ ok: false, status: 422, detail: t("backfillReadRateRange") });
        return;
      }
      parsed.read_rate = rate;
    }
    // datetime-local 按浏览器本地时区解析，转带 Z 的 UTC ISO（后端要求 tz-aware）。
    const iso = new Date(capturedAt).toISOString();
    setResult(null);
    startTransition(async () => {
      const actionResult = await backfillEffectAction(
        contentId,
        platformPostId.trim(),
        iso,
        parsed,
      );
      setResult(actionResult);
      if (actionResult.ok) {
        setPlatformPostId("");
        setCapturedAt("");
        setMetrics(EMPTY_METRICS);
        router.refresh();
      }
    });
  }

  return (
    <section className={styles.island}>
      <h2 className={styles.subtitle}>{t("backfillTitle")}</h2>
      <p className={styles.editNote}>{t("backfillNote")}</p>
      <label className={styles.fieldLabel} htmlFor="backfill-post-id">
        {t("backfillPostLabel")}
      </label>
      <input
        id="backfill-post-id"
        type="text"
        className={styles.textArea}
        value={platformPostId}
        maxLength={200}
        placeholder={t("backfillPostPlaceholder")}
        onChange={(event) => setPlatformPostId(event.target.value)}
      />
      <label className={styles.fieldLabel} htmlFor="backfill-captured-at">
        {t("backfillCapturedLabel")}
      </label>
      <input
        id="backfill-captured-at"
        type="datetime-local"
        className={styles.textArea}
        value={capturedAt}
        onChange={(event) => setCapturedAt(event.target.value)}
      />
      <p className={styles.fieldLabel}>{t("backfillMetricsLabel")}</p>
      <div>
        {METRIC_KEYS.map((key) => (
          <label key={key} className={styles.fieldLabel} htmlFor={`backfill-${key}`}>
            {t(`backfillMetric.${key}`)}
            <input
              id={`backfill-${key}`}
              type="number"
              min="0"
              step={key === "read_rate" ? "0.001" : "1"}
              max={key === "read_rate" ? "1" : undefined}
              value={metrics[key]}
              placeholder={t("backfillMetricAbsent")}
              onChange={(event) =>
                setMetrics((prev) => ({ ...prev, [key]: event.target.value }))
              }
            />
          </label>
        ))}
      </div>
      <div className={styles.actionButtons}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending}
          onClick={submit}
        >
          {t("backfillSubmit")}
        </button>
      </div>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok
            ? t("backfillSuccess", { count: result.receipt.matched })
            : failureText(result)}
        </p>
      ) : null}
    </section>
  );
}

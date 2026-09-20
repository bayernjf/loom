"use client";

// Q136：客户效果批量回填岛（内容详情页，非 discarded 成品均显示）。
// 甲案（02 C1.80）：纯前端 CSV/表格录入——不建后端上传端点、无迁移、无新依赖；
// 解析与行级校验在浏览器完成，整批走 Q128 客户通道 records[]（all-or-nothing、绝不产生孤儿）。
// 指标列留空即缺席（绝不补 0）；captured_at 统一转带 Z 的 UTC ISO（后端要求 tz-aware）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState, useTransition } from "react";

import {
  batchBackfillEffectsAction,
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
const HEADER_COLUMNS = ["platform_post_id", "captured_at", ...METRIC_KEYS];
// V1 前端软上限（后端 records 仅要求 ≥1，无上限）；避免单次超大 JSON。
const MAX_ROWS = 500;
const PREVIEW_ROWS = 10;

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

type ParsedRow = {
  line: number; // 物理行号（含表头，首条数据行 = 2）
  platformPostId: string;
  capturedAt: string; // 带 Z 的 UTC ISO
  metrics: Record<string, number>;
};

type RowError = { line: number; message: string };

type ParseResult = {
  rows: ParsedRow[];
  errors: RowError[];
  headerError: string | null;
  tooMany: boolean;
};

// 最小 CSV 行解析：支持双引号包裹与转义双引号，不支持字段内换行（指标数据无此场景）。
function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (quoted) {
      if (char === '"') {
        if (line[i + 1] === '"') {
          current += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        current += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      cells.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current);
  return cells.map((cell) => cell.trim());
}

// 支持 ISO 串、`YYYY-MM-DD HH:MM`、datetime-local 形态；纯日期按本地 00:00（与单条岛一致）。
function parseCapturedAt(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? `${value}T00:00`
    : value.replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function parseCsv(
  text: string,
  t: ReturnType<typeof useTranslations>,
): ParseResult {
  const result: ParseResult = {
    rows: [],
    errors: [],
    headerError: null,
    tooMany: false,
  };
  const physicalLines = text.split(/\r?\n/);
  const firstDataIndex = physicalLines.findIndex((line) => line.trim() !== "");
  if (firstDataIndex === -1) return result;

  const headerCells = splitCsvLine(physicalLines[firstDataIndex]).map((cell) =>
    cell.toLowerCase(),
  );
  const columnIndex: Record<string, number> = {};
  for (const column of HEADER_COLUMNS) {
    const index = headerCells.indexOf(column);
    if (index === -1) {
      result.headerError = t("backfillBatchHeaderMissing");
      return result;
    }
    columnIndex[column] = index;
  }

  for (let i = firstDataIndex + 1; i < physicalLines.length; i += 1) {
    const line = physicalLines[i];
    if (line.trim() === "") continue;
    const lineNumber = i + 1;
    const cells = splitCsvLine(line);
    const cell = (column: string) =>
      (cells[columnIndex[column]] ?? "").trim();

    const platformPostId = cell("platform_post_id");
    if (!platformPostId) {
      result.errors.push({
        line: lineNumber,
        message: t("backfillPostRequired"),
      });
      continue;
    }
    const capturedAt = parseCapturedAt(cell("captured_at"));
    if (!capturedAt) {
      result.errors.push({
        line: lineNumber,
        message: t("backfillCapturedRequired"),
      });
      continue;
    }
    const metrics: Record<string, number> = {};
    let badMetric = false;
    for (const key of COUNT_METRICS) {
      const raw = cell(key);
      if (!raw) continue;
      const value = Number(raw);
      if (!Number.isInteger(value) || value < 0) {
        result.errors.push({
          line: lineNumber,
          message: t("backfillMetricInteger"),
        });
        badMetric = true;
        break;
      }
      metrics[key] = value;
    }
    if (badMetric) continue;
    const rateRaw = cell("read_rate");
    if (rateRaw) {
      const rate = Number(rateRaw);
      if (Number.isNaN(rate) || rate < 0 || rate > 1) {
        result.errors.push({
          line: lineNumber,
          message: t("backfillReadRateRange"),
        });
        continue;
      }
      metrics.read_rate = rate;
    }
    result.rows.push({ line: lineNumber, platformPostId, capturedAt, metrics });
  }

  if (result.rows.length > MAX_ROWS) result.tooMany = true;
  return result;
}

export function BatchBackfillIsland({ contentId }: { contentId: string }) {
  const t = useTranslations("content");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [text, setText] = useState("");
  const [result, setResult] = useState<BackfillActionResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const parsed = useMemo(() => parseCsv(text, t), [text, t]);
  const blocked =
    parsed.headerError !== null ||
    parsed.tooMany ||
    parsed.errors.length > 0 ||
    parsed.rows.length === 0;

  function failureText(failure: Extract<BackfillActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function loadFile(file: File | undefined) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setText(typeof reader.result === "string" ? reader.result : "");
      setResult(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    };
    reader.readAsText(file);
  }

  function submit() {
    if (blocked) return;
    setResult(null);
    startTransition(async () => {
      const actionResult = await batchBackfillEffectsAction(
        contentId,
        parsed.rows.map((row) => ({
          platform_post_id: row.platformPostId,
          captured_at: row.capturedAt,
          metrics: row.metrics,
        })),
      );
      setResult(actionResult);
      if (actionResult.ok) {
        setText("");
        router.refresh();
      }
    });
  }

  const previewRows = parsed.rows.slice(0, PREVIEW_ROWS);

  return (
    <section className={styles.island}>
      <h2 className={styles.subtitle}>{t("backfillBatchTitle")}</h2>
      <p className={styles.editNote}>{t("backfillBatchNote")}</p>
      <p className={styles.blockNote}>
        {t("backfillBatchFormat", { max: MAX_ROWS })}
      </p>
      <p className={styles.mono}>{HEADER_COLUMNS.join(",")}</p>
      <label className={styles.fieldLabel} htmlFor="backfill-batch-file">
        {t("backfillBatchFile")}
      </label>
      <input
        id="backfill-batch-file"
        ref={fileInputRef}
        type="file"
        accept=".csv,text/csv"
        onChange={(event) => loadFile(event.target.files?.[0])}
      />
      <textarea
        className={styles.textArea}
        rows={8}
        value={text}
        placeholder={t("backfillBatchPlaceholder")}
        onChange={(event) => {
          setText(event.target.value);
          setResult(null);
        }}
      />
      {parsed.headerError ? (
        <p className={styles.errorText} role="status">
          {parsed.headerError}
        </p>
      ) : null}
      {parsed.tooMany ? (
        <p className={styles.errorText} role="status">
          {t("backfillBatchTooMany", {
            max: MAX_ROWS,
            count: parsed.rows.length,
          })}
        </p>
      ) : null}
      {parsed.errors.length > 0 ? (
        <div className={styles.errorText} role="status">
          <p>{t("backfillBatchErrors", { count: parsed.errors.length })}</p>
          <ul>
            {parsed.errors.slice(0, 20).map((error) => (
              <li key={error.line}>
                {t("backfillBatchLine", {
                  line: error.line,
                  message: error.message,
                })}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {!parsed.headerError && parsed.rows.length > 0 && !parsed.tooMany ? (
        <>
          <p className={styles.successText}>
            {t("backfillBatchParsed", { count: parsed.rows.length })}
          </p>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("backfillPostLabel")}</th>
                <th>{t("backfillCapturedLabel")}</th>
                {METRIC_KEYS.map((key) => (
                  <th key={key}>{t(`backfillMetric.${key}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {previewRows.map((row) => (
                <tr key={`${row.line}-${row.platformPostId}`}>
                  <td>{row.platformPostId}</td>
                  <td>{row.capturedAt}</td>
                  {METRIC_KEYS.map((key) => (
                    <td key={key}>
                      {row.metrics[key] === undefined ? "—" : row.metrics[key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {parsed.rows.length > PREVIEW_ROWS ? (
            <p className={styles.blockNote}>
              {t("backfillBatchPreviewMore", {
                count: parsed.rows.length - PREVIEW_ROWS,
              })}
            </p>
          ) : null}
        </>
      ) : null}
      <div className={styles.actionButtons}>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending || blocked}
          onClick={submit}
        >
          {t("backfillBatchSubmit")}
        </button>
      </div>
      {result ? (
        <p
          className={result.ok ? styles.successText : styles.errorText}
          role="status"
        >
          {result.ok
            ? t("backfillBatchSuccess", { count: result.receipt.matched })
            : failureText(result)}
        </p>
      ) : null}
    </section>
  );
}

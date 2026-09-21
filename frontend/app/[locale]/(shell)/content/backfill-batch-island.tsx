"use client";

// Q159：客户效果批量回填岛（内容详情页，非 discarded 成品均显示）。
// Q136 甲案为纯前端解析后走 Q128 records[]；Q156 落地服务端上传端点后，本岛切换为
// 提交 CSV 原文到 POST /api/effects/backfill/upload——服务端固定 9 列解析、逐行校验
// （权威），全合法才整批 all-or-nothing 落库（绝不产生孤儿），422 回逐行错误。
// 浏览器侧仍做一次同构即时解析，仅用于上传前预览/前置反馈；服务端校验为最终权威。
// 指标列留空即缺席（绝不补 0）；captured_at 必须带时区（Z 或 ±HH:MM），不臆造时区。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState, useTransition } from "react";

import {
  batchBackfillEffectsAction,
  type BatchBackfillActionResult,
  type BackfillServerError,
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
// 与后端 LOOM_BACKFILL_UPLOAD_MAX_ROWS 默认值对齐（服务端为权威，env 可调）。
const MAX_ROWS = 10000;
const PREVIEW_ROWS = 10;

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);
// 服务端计数列只接受非负整数字面量（^\d+$），镜像该口径。
const INT_RE = /^\d+$/;
// 服务端要求 tz-aware：结尾必须是 Z/z 或 ±HH:MM（可带冒号）。
const TZ_RE = /(Z|z|[+-]\d{2}:?\d{2})$/;

type ParsedRow = {
  line: number; // 物理行号（含表头，首条数据行 = 2）
  platformPostId: string;
  capturedAt: string; // 带时区的 ISO（归一化为 UTC）
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

// 服务端 csv_io 铁律：captured_at 必须带时区（Z 或 ±HH:MM）；naive/纯日期一律拒，
// 前端不做浏览器本地时区猜测（与 Q156 服务端口径一致）。
function parseCapturedAt(raw: string): string | null {
  const value = raw.trim();
  if (!value || !TZ_RE.test(value)) return null;
  const candidate = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(candidate);
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
  const physicalLines = text.replace(/^\ufeff/, "").split(/\r?\n/);
  const firstDataIndex = physicalLines.findIndex((line) => line.trim() !== "");
  if (firstDataIndex === -1) return result;

  const headerCells = splitCsvLine(physicalLines[firstDataIndex]).map((cell) =>
    cell.toLowerCase(),
  );
  const columnIndex: Record<string, number> = {};
  let headerInvalid = false;
  for (let pos = 0; pos < headerCells.length; pos += 1) {
    const name = headerCells[pos];
    if (name in columnIndex || !HEADER_COLUMNS.includes(name)) {
      headerInvalid = true;
    } else {
      columnIndex[name] = pos;
    }
  }
  const missing = HEADER_COLUMNS.filter((c) => !(c in columnIndex));
  if (headerInvalid || headerCells.length !== HEADER_COLUMNS.length) {
    result.headerError = t("backfillBatchHeaderInvalid");
    return result;
  }
  if (missing.length > 0) {
    result.headerError = t("backfillBatchHeaderMissing");
    return result;
  }

  const cell = (cells: string[], column: string) =>
    (cells[columnIndex[column]] ?? "").trim();
  let dataIndex = -1;

  for (let i = firstDataIndex + 1; i < physicalLines.length; i += 1) {
    const line = physicalLines[i];
    if (line.trim() === "") continue;
    const lineNumber = i + 1;
    dataIndex += 1;
    if (dataIndex >= MAX_ROWS) {
      result.tooMany = true;
      continue;
    }
    const cells = splitCsvLine(line);
    if (cells.length !== HEADER_COLUMNS.length) {
      result.errors.push({
        line: lineNumber,
        message: t("backfillBatchColumnCount", {
          line: lineNumber,
          n: cells.length,
        }),
      });
      continue;
    }

    const platformPostId = cell(cells, "platform_post_id");
    if (!platformPostId) {
      result.errors.push({
        line: lineNumber,
        message: t("backfillPostRequired"),
      });
      continue;
    }
    const capturedAt = parseCapturedAt(cell(cells, "captured_at"));
    if (!capturedAt) {
      result.errors.push({
        line: lineNumber,
        message: t("backfillBatchTzRequired"),
      });
      continue;
    }
    const metrics: Record<string, number> = {};
    let badMetric = false;
    for (const key of COUNT_METRICS) {
      const raw = cell(cells, key);
      if (!raw) continue;
      if (!INT_RE.test(raw)) {
        result.errors.push({
          line: lineNumber,
          message: t("backfillMetricInteger"),
        });
        badMetric = true;
        break;
      }
      metrics[key] = Number(raw);
    }
    if (badMetric) continue;
    const rateRaw = cell(cells, "read_rate");
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

  return result;
}

export function BatchBackfillIsland({ contentId }: { contentId: string }) {
  const t = useTranslations("content");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [text, setText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [result, setResult] = useState<BatchBackfillActionResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const parsed = useMemo(() => parseCsv(text, t), [text, t]);
  const blocked =
    parsed.headerError !== null ||
    parsed.tooMany ||
    parsed.errors.length > 0 ||
    parsed.rows.length === 0;

  function failureText(failure: Extract<BatchBackfillActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function serverErrorText(error: BackfillServerError): string {
    // 服务端逐行回执（field 可空，如表头/文件级错误）；message 为后端权威文本。
    const prefix = error.field ? `${error.field}: ` : "";
    return t("backfillBatchLine", {
      line: error.line,
      message: `${prefix}${error.message}`,
    });
  }

  function loadFile(file: File | undefined) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setText(typeof reader.result === "string" ? reader.result : "");
      setFilename(file.name);
      setResult(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    };
    reader.readAsText(file);
  }

  function submit() {
    if (blocked) return;
    setResult(null);
    startTransition(async () => {
      // 提交 CSV 原文与文件名；服务端解析校验，浏览器解析仅用于上方即时预览。
      const actionResult = await batchBackfillEffectsAction(
        contentId,
        text,
        filename,
      );
      setResult(actionResult);
      if (actionResult.ok) {
        setText("");
        setFilename(null);
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
          setFilename(null);
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
        result.ok ? (
          <p className={styles.successText} role="status">
            {t("backfillBatchSuccess", { count: result.receipt.matched })}
          </p>
        ) : (
          <div className={styles.errorText} role="status">
            {result.serverErrors.length > 0 ? (
              <>
                <p>
                  {t("backfillBatchServerErrors", {
                    count: result.serverErrors.length,
                  })}
                </p>
                <ul>
                  {result.serverErrors.slice(0, 20).map((error, idx) => (
                    <li key={`${error.line}-${idx}`}>{serverErrorText(error)}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p>{failureText(result)}</p>
            )}
          </div>
        )
      ) : null}
    </section>
  );
}

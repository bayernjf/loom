"use client";

// Q168：创建导出任务岛——选格式（csv/json，枚举码原样）+ 选填发布位，
// 提交走 Server Action，成功 router.refresh（门控关同步 completed、开则 queued）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  createExportJobAction,
  type ExportActionResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function CreateExportIsland({ tenantId }: { tenantId: string }) {
  const t = useTranslations("admin.exports");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [productSpaceId, setProductSpaceId] = useState("");
  const [result, setResult] = useState<ExportActionResult | null>(null);

  function failureText(failure: Extract<ExportActionResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function submit() {
    setResult(null);
    startTransition(async () => {
      const actionResult = await createExportJobAction(
        tenantId,
        productSpaceId,
        format,
      );
      setResult(actionResult);
      if (actionResult.ok) {
        setProductSpaceId("");
        router.refresh();
      }
    });
  }

  return (
    <section className={styles.section} data-testid="create-export-job">
      <h2 className={styles.sectionTitle}>{t("createTitle")}</h2>
      <div className={styles.provisionForm}>
        <select
          aria-label={t("formatLabel")}
          value={format}
          onChange={(event) => setFormat(event.target.value as "csv" | "json")}
        >
          <option value="csv">csv</option>
          <option value="json">json</option>
        </select>
        <input
          type="text"
          className={styles.jsonArea}
          aria-label={t("productSpaceLabel")}
          placeholder={t("productSpacePlaceholder")}
          value={productSpaceId}
          onChange={(event) => setProductSpaceId(event.target.value)}
        />
        <button
          type="button"
          className={styles.primaryButton}
          disabled={pending}
          onClick={submit}
        >
          {t("createSubmit")}
        </button>
      </div>
      {result && !result.ok && (
        <p className={styles.msgErr} role="status">
          {failureText(result)}
        </p>
      )}
    </section>
  );
}

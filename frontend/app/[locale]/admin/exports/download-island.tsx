"use client";

// Q168：下载导出成品岛——仅 completed 可取（queued/running 409、failed 409）。
// 文本经 Server Action 回传，client 端组 Blob 触发浏览器下载（不经裸 URL）。
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  downloadExportJobAction,
  type ExportDownloadResult,
} from "./actions";

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function DownloadExportButton({
  jobId,
  tenantId,
  status,
}: {
  jobId: string;
  tenantId: string;
  status: string;
}) {
  const t = useTranslations("admin.exports");
  const tError = useTranslations("error");
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function failureText(failure: Extract<ExportDownloadResult, { ok: false }>): string {
    if (failure.status === "unconfigured") return t("actorUnconfigured");
    if (failure.status === "unknown") return tError("unknown");
    if (failure.status === 409) return t("notReady");
    if (failure.status === 422 && failure.detail) return failure.detail;
    return tError(
      KNOWN_STATUSES.has(failure.status) ? String(failure.status) : "unknown",
    );
  }

  function download() {
    setError(null);
    startTransition(async () => {
      const result = await downloadExportJobAction(jobId, tenantId);
      if (!result.ok) {
        setError(failureText(result));
        return;
      }
      const blob = new Blob([result.content], { type: result.mediaType });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      router.refresh();
    });
  }

  const ready = status === "completed";
  return (
    <span>
      <button
        type="button"
        className={styles.secondaryButton}
        disabled={pending || !ready}
        onClick={download}
        title={ready ? "" : t("notReady")}
      >
        {t("downloadSubmit")}
      </button>
      {error && (
        <span className={styles.msgErr} role="status">
          {error}
        </span>
      )}
    </span>
  );
}

"use client";

// Q177：台内白名单卡片六层原料包按需展开岛（纯只读）。点击才经 Server Action 拉取
// GET /api/admin/fcw/{final_id}/material，按六层 details/pre 展开；client 岛不直连
// API、不做任何写操作、展开后也不刷新 RSC 列表。枚举码/标识原样直出，不做翻译。
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import styles from "../admin.module.css";
import {
  getFcwMaterialAction,
  type FcwMaterialPack,
  type FcwMaterialResult,
} from "./actions";

const LAYER_KEYS = [
  "product",
  "platform",
  "strategy",
  "structure",
  "expression",
  "compliance",
] as const;

const KNOWN_STATUSES = new Set([403, 404, 409, 422]);

export function MaterialIsland({ finalId }: { finalId: string }) {
  const t = useTranslations("admin.fcw");
  const tError = useTranslations("error");
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [pack, setPack] = useState<FcwMaterialPack | null>(null);
  const [result, setResult] = useState<FcwMaterialResult | null>(null);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && pack === null && !(result !== null && !result.ok)) {
      startTransition(async () => {
        const r = await getFcwMaterialAction(finalId);
        if (r.ok) setPack(r.pack);
        else setResult(r);
      });
    }
  }

  function failureText(r: Extract<FcwMaterialResult, { ok: false }>): string {
    if (r.status === "unconfigured") return t("actorUnconfigured");
    if (r.status === "missing_role") return t("actorMissingRole");
    if (r.status === "unknown") return tError("unknown");
    if (r.status === 422 && r.detail) return r.detail;
    return tError(
      KNOWN_STATUSES.has(Number(r.status)) ? String(r.status) : "unknown",
    );
  }

  // Q186 D3.5 余项：已展开的六层原料包一键存盘。与 Q168 导出下载同范式——组 Blob
  // 触发浏览器下载（不经裸 URL），只读岛不刷新路由。
  function downloadJson() {
    if (!pack) return;
    const blob = new Blob([JSON.stringify(pack, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `fcw-${finalId}-material.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={toggle}
        aria-expanded={open}
        data-testid="fcw-material-toggle"
      >
        {open ? t("materialHide") : t("materialShow")}
      </button>
      {open ? (
        <div className={styles.tableWrap} data-testid="fcw-material">
          {pending ? <p className={styles.notice}>{t("materialLoading")}</p> : null}
          {result !== null && !result.ok ? (
            <p className={styles.msgErr} role="status">
              {failureText(result)}
            </p>
          ) : null}
          {pack ? (
            <>
              <p className={styles.metaLine}>{pack.schema}</p>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={downloadJson}
                data-testid="fcw-material-download"
              >
                {t("downloadMaterial")}
              </button>
              {Array.isArray(pack.warnings) && pack.warnings.length > 0 ? (
                <details open>
                  <summary>{t("warningsTitle")}</summary>
                  <pre>{JSON.stringify(pack.warnings, null, 2)}</pre>
                </details>
              ) : null}
              {LAYER_KEYS.map((key) =>
                pack.layers[key] ? (
                  <details key={key}>
                    <summary>{t(`layer.${key}`)}</summary>
                    <pre>{JSON.stringify(pack.layers[key], null, 2)}</pre>
                  </details>
                ) : null,
              )}
              <details>
                <summary>{t("guardsTitle")}</summary>
                <pre>{JSON.stringify(pack.guards, null, 2)}</pre>
              </details>
            </>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

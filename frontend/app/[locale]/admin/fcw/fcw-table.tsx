"use client";

// Q186 D3.5 余项：白名单卡片台的 final_id 单条/多选复制。表格下沉为 client 岛
// 只为承载「本页选中态」（跨行共享状态无法由 RSC 持有）；数据仍由 page.tsx 服务端
// 取好后以 props 传入，岛内不直连后端、不做任何写操作、不刷新路由。
// 复制范式沿用 Q167/Q178 密钥岛的 navigator.clipboard + 按钮换文案。
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { FcwListItem } from "@/lib/api";
import styles from "../admin.module.css";
import { MaterialIsland } from "./material-island";

function shortId(value: string): string {
  return value.slice(0, 8);
}

function fmt(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}

function CopyIdButton({ finalId }: { finalId: string }) {
  const t = useTranslations("admin.fcw");
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(finalId);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      type="button"
      className={styles.secondaryButton}
      onClick={copy}
      title={finalId}
      data-testid="fcw-copy-id"
    >
      {copied ? t("copied") : t("copyId")}
    </button>
  );
}

export function FcwTable({ items }: { items: FcwListItem[] }) {
  const t = useTranslations("admin.fcw");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [bulkCopied, setBulkCopied] = useState(false);

  const ids = items.map((item) => item.final_id);
  const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));

  function toggleOne(finalId: string) {
    setBulkCopied(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(finalId)) next.delete(finalId);
      else next.add(finalId);
      return next;
    });
  }

  function toggleAll() {
    setBulkCopied(false);
    setSelected(allSelected ? new Set() : new Set(ids));
  }

  async function copySelected() {
    // 只复制本页仍存在的行：翻页/筛选后 props 变化，旧选中项自然失效。
    const picked = ids.filter((id) => selected.has(id));
    if (picked.length === 0) return;
    try {
      await navigator.clipboard.writeText(picked.join("\n"));
      setBulkCopied(true);
    } catch {
      setBulkCopied(false);
    }
  }

  return (
    <>
      <div className={styles.pager} data-testid="fcw-bulk-copy">
        <button
          type="button"
          className={styles.primaryButton}
          onClick={copySelected}
          disabled={selected.size === 0}
        >
          {t("bulkCopy")}
        </button>
        <span className={styles.metaLine}>
          {t("bulkCopyHint", { count: selected.size })}
        </span>
        {bulkCopied ? (
          <span className={styles.metaLine} role="status">
            {t("copied")}
          </span>
        ) : null}
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label={t("selectAll")}
                  data-testid="fcw-select-all"
                />
              </th>
              <th>{t("colFinal")}</th>
              <th>{t("colTenant")}</th>
              <th>{t("colPlatform")}</th>
              <th>{t("colSlot")}</th>
              <th>{t("colGoal")}</th>
              <th>{t("colScore")}</th>
              <th>{t("colStatus")}</th>
              <th>{t("colCreated")}</th>
              <th>{t("colAction")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((fcw) => (
              <tr key={fcw.final_id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(fcw.final_id)}
                    onChange={() => toggleOne(fcw.final_id)}
                    aria-label={fcw.final_id}
                  />
                </td>
                <td>
                  <span className={styles.metaLine} title={fcw.final_id}>
                    {shortId(fcw.final_id)}
                  </span>
                </td>
                <td>
                  <span className={styles.metaLine}>{fcw.tenant_id}</span>
                </td>
                <td>{fcw.platform}</td>
                <td>
                  <span className={styles.metaLine} title={fcw.slot_id}>
                    {shortId(fcw.slot_id)}
                  </span>
                </td>
                <td>{fcw.goal}</td>
                <td>{fcw.score === null ? "—" : fcw.score.toFixed(1)}</td>
                <td>
                  <span
                    className={`${styles.chip} ${
                      fcw.publish_status === "published" ? styles.chipActive : ""
                    }`}
                  >
                    {fcw.publish_status}
                  </span>
                </td>
                <td>{fmt(fcw.created_at)}</td>
                <td>
                  <CopyIdButton finalId={fcw.final_id} />
                  <MaterialIsland finalId={fcw.final_id} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

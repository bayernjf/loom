"use client";

// Q186 D3.5 余项：客户白名单卡片 final_id 复制。纯 client 交互，不直连后端、
// 不写任何数据；复制范式沿用 Q167/Q178 密钥岛的 navigator.clipboard + 按钮换文案。
import { useTranslations } from "next-intl";
import { useState } from "react";

import styles from "../content.module.css";

export function CopyIdButton({ finalId }: { finalId: string }) {
  const t = useTranslations("content.cards");
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
      data-testid="card-copy-id"
    >
      {copied ? t("copied") : t("copyId")}
    </button>
  );
}

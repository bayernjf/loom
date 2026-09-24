"use client";

// Q180 D3.5：客户白名单卡片「六层原料包」展开岛：点击经 Server Action 拉取、pre 只读展示。
// client 岛不直连后端，复用 Q155 build_material_pack 的 material.json 出口。
// Q186：展开后补一键存盘（与 Q168 导出下载同范式，组 Blob 不经裸 URL）。
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { getFcwMaterialAction } from "../actions";
import styles from "../content.module.css";

export function CardMaterialIsland({ finalId }: { finalId: string }) {
  const t = useTranslations("content.cards");
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [packText, setPackText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (packText === null && !failed) {
      startTransition(async () => {
        const result = await getFcwMaterialAction(finalId);
        if (result.ok) setPackText(JSON.stringify(result.pack, null, 2));
        else setFailed(true);
      });
    }
  }

  function downloadJson() {
    if (packText === null) return;
    const blob = new Blob([packText], { type: "application/json" });
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
    <div>
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={toggle}
      >
        {open ? t("collapseMaterial") : t("expandMaterial")}
      </button>
      {open && pending && packText === null ? (
        <p className={styles.notice}>{t("loading")}</p>
      ) : null}
      {open && packText !== null ? (
        <>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={downloadJson}
            data-testid="card-material-download"
          >
            {t("downloadMaterial")}
          </button>
          <pre className={styles.bodyPre}>{packText}</pre>
        </>
      ) : null}
      {open && failed && packText === null ? (
        <p className={styles.errorText}>{t("materialFailed")}</p>
      ) : null}
    </div>
  );
}

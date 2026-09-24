"use client";

// Q180 D3.5：客户白名单卡片「六层原料包」展开岛：点击经 Server Action 拉取、pre 只读展示。
// client 岛不直连后端，复用 Q155 build_material_pack 的 material.json 出口。
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
        <pre className={styles.bodyPre}>{packText}</pre>
      ) : null}
      {open && failed && packText === null ? (
        <p className={styles.errorText}>{t("materialFailed")}</p>
      ) : null}
    </div>
  );
}

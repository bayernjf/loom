import { getTranslations } from "next-intl/server";

import type { NavPhase } from "../nav";
import styles from "./menu-placeholder.module.css";

export async function MenuPlaceholder({
  labelKey,
  phase,
}: {
  labelKey: string;
  phase: NavPhase;
}) {
  const t = await getTranslations();

  return (
    <div className={styles.wrapper}>
      <div className={styles.titleRow}>
        <h1 className={styles.title}>{t(labelKey)}</h1>
        {phase === "v2" && (
          <span className={styles.badge}>{t("shell.v2Badge")}</span>
        )}
      </div>
      <p className={styles.note}>
        {phase === "v2" ? t("shell.placeholderV2") : t("shell.placeholderV1")}
      </p>
    </div>
  );
}

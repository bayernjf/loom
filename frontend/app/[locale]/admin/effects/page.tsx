import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ApiError, CURRENT_ADMIN_ACTOR_ID, getEffectOrphans } from "@/lib/api";
import styles from "../admin.module.css";
import { OrphanTableIsland } from "./orphan-table-island";
import { SeriesQueryIsland } from "./series-island";

// Q126–Q130：管理端效果运营台——孤儿数据队列人工认领（Q60a，单条/批量/解绑）
// 与成品效果时序查询。读口 operations | platform_admin，写口 operations 硬闸
//（岛与 Server Action 在缺 operations 时本地拒发）。
export const dynamic = "force-dynamic";

const KNOWN_ERROR_STATUSES = new Set([403, 404, 422]);

export default async function AdminEffectsPage() {
  const t = await getTranslations("admin.effects");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  let orphanSection: ReactNode;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    orphanSection = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
  } else {
    let errorStatus = 0;
    let orphans = null;
    try {
      orphans = await getEffectOrphans({ limit: 100 });
    } catch (err) {
      errorStatus = err instanceof ApiError ? err.status : 0;
    }
    if (orphans === null) {
      const key = KNOWN_ERROR_STATUSES.has(errorStatus)
        ? String(errorStatus)
        : "unknown";
      orphanSection = <p className={styles.notice}>{tError(key)}</p>;
    } else {
      orphanSection = <OrphanTableIsland rows={orphans} />;
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("orphanTitle")}</h2>
        <p className={styles.intro}>{t("orphanIntro")}</p>
        {orphanSection}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("seriesTitle")}</h2>
        <p className={styles.intro}>{t("seriesIntro")}</p>
        {CURRENT_ADMIN_ACTOR_ID ? (
          <SeriesQueryIsland />
        ) : (
          <p className={styles.notice}>{tAdmin("unconfigured")}</p>
        )}
      </section>
    </div>
  );
}

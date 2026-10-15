import { formatDateTimeLocal } from "@/lib/time";
import { ErrorState } from "@/components/error-state";
import { getTranslations } from "next-intl/server";

import { ApiError, CURRENT_ADMIN_ACTOR_ID, getConfigItem } from "@/lib/api";
import styles from "../admin.module.css";
import { RegenLimitConfigIsland } from "./config-island";

export const dynamic = "force-dynamic";

// Q364（Q56 配置功能页）：运行配置台。当前仅 content.regen_limit 一项（重生成上限，
// Q56 明确要求配置页面；后端读/写口与 {min:1} 校验早已齐备，见 config_center）。
// 页面只读 RSC：当前值与版本元信息（版本/更新人/时间）服务端直读；修改走 client 岛
// → Server Action（platform_admin 写闸，配置变更落版本历史与审计）。
const REGEN_LIMIT_KEY = "content.regen_limit";
const KNOWN_ERROR_STATUSES = new Set([403, 404, 422]);

export default async function SystemConfigPage() {
  const t = await getTranslations("admin.systemConfig");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  let body;
  if (!CURRENT_ADMIN_ACTOR_ID) {
    body = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
  } else {
    try {
      const item = await getConfigItem(REGEN_LIMIT_KEY);
      if (typeof item.value !== "number" || !Number.isInteger(item.value)) {
        body = (
          <ErrorState
            title={t("loadFailed")}
            hint={tError("retryHint")}
            retryLabel={tError("retry")}
          />
        );
      } else {
        body = (
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("contentSectionTitle")}</h2>
            <table className={styles.table}>
              <tbody>
                <tr>
                  <td>
                    <span className={styles.chip}>{item.key}</span>
                  </td>
                  <td className="num">{item.value}</td>
                  <td>
                    {t("metaLine", {
                      version: item.version,
                      by: item.updated_by ?? "—",
                      at: formatDateTimeLocal(item.updated_at),
                    })}
                  </td>
                </tr>
              </tbody>
            </table>
            <RegenLimitConfigIsland current={item.value} />
          </section>
        );
      }
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      body = (
        <ErrorState
          title={t("loadFailed")}
          code={KNOWN_ERROR_STATUSES.has(status) ? String(status) : undefined}
          hint={tError("retryHint")}
          retryLabel={tError("retry")}
        />
      );
    }
  }

  return (
    <main className={styles.page} data-testid="system-config-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      {body}
    </main>
  );
}

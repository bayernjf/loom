import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { ApiError, CURRENT_TENANT_ID, getCurrentTenant } from "@/lib/api";
import styles from "./settings.module.css";

export const dynamic = "force-dynamic";

// D5 系统设置 = 账户信息 / 平台授权 / 通知 / 帮助；团队（D3.11-3）、账单（D3.11-6）随 V2。
// V1 只做账户信息（只读）+ 语言（当前 zh-CN），其余挂 V2 徽标占位。
const V2_ITEMS = [
  "itemPlatformAuth",
  "itemNotifications",
  "itemHelp",
  "itemTeam",
  "itemBilling",
] as const;

const KNOWN_ERROR_STATUSES = new Set([403, 404, 409, 422]);

export default async function SettingsPage() {
  const t = await getTranslations("settings");
  const tNav = await getTranslations("nav");
  const tError = await getTranslations("error");

  let accountBody: ReactNode;

  if (!CURRENT_TENANT_ID) {
    accountBody = <p className={styles.notice}>{t("unconfigured")}</p>;
  } else {
    try {
      const tenant = await getCurrentTenant(CURRENT_TENANT_ID);
      accountBody = (
        <dl className={styles.accountList}>
          <div className={styles.accountRow}>
            <dt className={styles.accountLabel}>{t("fieldTenantId")}</dt>
            <dd className={styles.accountValue}>{tenant.tenant_id}</dd>
          </div>
          <div className={styles.accountRow}>
            <dt className={styles.accountLabel}>{t("fieldTenantName")}</dt>
            <dd className={styles.accountValue}>
              {tenant.name?.trim() || t("nameEmpty")}
            </dd>
          </div>
          <div className={styles.accountRow}>
            <dt className={styles.accountLabel}>{t("fieldPlan")}</dt>
            <dd className={styles.accountValue}>{tenant.plan}</dd>
          </div>
          <div className={styles.accountRow}>
            <dt className={styles.accountLabel}>{t("fieldStatus")}</dt>
            <dd className={styles.accountValue}>{tenant.status}</dd>
          </div>
          <div className={styles.accountRow}>
            <dt className={styles.accountLabel}>{t("fieldQuota")}</dt>
            <dd className={styles.accountValue}>
              {tenant.monthly_token_quota == null
                ? t("quotaEmpty")
                : String(tenant.monthly_token_quota)}
            </dd>
          </div>
        </dl>
      );
    } catch (err) {
      const key =
        err instanceof ApiError && KNOWN_ERROR_STATUSES.has(err.status)
          ? String(err.status)
          : "unknown";
      accountBody = <p className={styles.notice}>{tError(key)}</p>;
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{tNav("settings")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <section className={styles.card} aria-labelledby="account-info">
        <h2 id="account-info" className={styles.cardTitle}>
          {t("accountTitle")}
        </h2>
        <p className={styles.cardNote}>{t("accountNote")}</p>
        {accountBody}
      </section>

      <section className={styles.card} aria-labelledby="language">
        <h2 id="language" className={styles.cardTitle}>
          {t("languageTitle")}
        </h2>
        <p className={styles.languageValue}>{t("languageValue")}</p>
        <p className={styles.cardNote}>{t("languageNote")}</p>
      </section>

      <section className={styles.card} aria-labelledby="more-settings">
        <h2 id="more-settings" className={styles.cardTitle}>
          {t("moreTitle")}
        </h2>
        <p className={styles.cardNote}>{t("moreNote")}</p>
        <ul className={styles.moreList}>
          {V2_ITEMS.map((item) => (
            <li key={item} className={styles.moreItem}>
              <span className={styles.moreName}>{t(item)}</span>
              <span className={styles.v2Badge}>V2</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

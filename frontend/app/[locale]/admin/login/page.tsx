import { getTranslations } from "next-intl/server";

import { LoomBrand } from "@/components/loom-brand";
import { ApiError, getStaffMe } from "@/lib/api";
import type { StaffMe } from "@/lib/api";
import { getStaffToken } from "@/lib/staff-auth";
import styles from "../admin.module.css";
import { LoginIsland } from "./login-island";

export const dynamic = "force-dynamic";

// Q178：内部运营登录录入页（粘贴 staff PAT → /api/auth/me 自检 → 写 httpOnly cookie）。
// 门控由后端单边控制：门控关 /api/auth/me 返回 400，登录岛提示门控未开启（此时沿用
// V1 env 自报，无需登录）；门控开则校验通过后写入 cookie 并跳回管理首页。
// Q331：品牌化——顶部 Loom 品牌标 + 登录卡片居中限宽。
export default async function AdminLoginPage() {
  const t = await getTranslations("admin.staffAuth");
  const tCommon = await getTranslations("common");

  let me: StaffMe | null = null;
  const token = await getStaffToken();
  if (token) {
    try {
      me = await getStaffMe(token);
    } catch (err) {
      if (err instanceof ApiError) {
        me = null;
      } else {
        throw err;
      }
    }
  }

  return (
    <main
      className={`${styles.page} ${styles.loginPage}`}
      data-testid="staff-login-page"
    >
      <LoomBrand
        name={tCommon("appName")}
        tagline={tCommon("appTagline")}
        size={40}
        className={styles.brandHero}
      />
      <header className={`${styles.pageHeader} ${styles.loginHeader}`}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      <LoginIsland initialMe={me} />
    </main>
  );
}

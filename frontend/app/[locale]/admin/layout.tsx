import { getTranslations } from "next-intl/server";

import { AdminSidebar } from "./admin-sidebar";
import styles from "./admin.module.css";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const t = await getTranslations("admin");

  return (
    <div className={styles.frame}>
      <AdminSidebar />
      <div className={styles.main}>
        <header className={styles.topbar}>{t("appName")}</header>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}

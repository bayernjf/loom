import { getTranslations } from "next-intl/server";

import { Sidebar } from "./sidebar";
import styles from "./shell.module.css";

export default async function ShellLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const t = await getTranslations("common");

  return (
    <div className={styles.frame}>
      <Sidebar />
      <div className={styles.main}>
        <header className={styles.topbar}>{t("appName")}</header>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}

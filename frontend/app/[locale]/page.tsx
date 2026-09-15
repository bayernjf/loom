import { getTranslations, setRequestLocale } from "next-intl/server";

import styles from "./page.module.css";

export default async function Home({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("home");
  const common = await getTranslations("common");

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{common("appName")}</h1>
      <p className={styles.tagline}>{common("appTagline")}</p>
      <span className={styles.badge}>{t("scaffoldTitle")}</span>
      <p className={styles.note}>{t("scaffoldNote")}</p>
    </main>
  );
}

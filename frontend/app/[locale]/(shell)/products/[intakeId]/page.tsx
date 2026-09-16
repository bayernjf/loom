import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { ApiError, getIntake, intakeDisplayName } from "@/lib/api";
import { ProductsSubnav } from "../products-subnav";
import styles from "../products.module.css";

export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ intakeId: string }>;
}) {
  const { intakeId } = await params;
  const t = await getTranslations("products");
  const tStatus = await getTranslations("intake.status");

  let intake;
  try {
    intake = await getIntake(intakeId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const profileEntries = Object.entries(intake.profile);

  return (
    <div>
      <ProductsSubnav />
      <h1 className={styles.title}>{intakeDisplayName(intake)}</h1>
      <dl className={styles.detailList}>
        <dt>{t("detail.fieldId")}</dt>
        <dd className={styles.mono}>{intake.intake_id}</dd>
        <dt>{t("detail.fieldTenant")}</dt>
        <dd className={styles.mono}>{intake.tenant_id}</dd>
        <dt>{t("detail.fieldStatus")}</dt>
        <dd>
          <span className={styles.statusChip}>{tStatus(intake.status)}</span>
        </dd>
      </dl>
      <h2 className={styles.subtitle}>{t("detail.fieldProfile")}</h2>
      {profileEntries.length === 0 ? (
        <p className={styles.notice}>{t("detail.profileEmpty")}</p>
      ) : (
        <dl className={styles.detailList}>
          {profileEntries.map(([key, value]) => (
            <div key={key} className={styles.profileEntry}>
              <dt className={styles.mono}>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <Link href="/products" className={styles.backLink}>
        {t("detail.back")}
      </Link>
    </div>
  );
}

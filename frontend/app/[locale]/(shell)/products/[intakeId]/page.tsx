import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import {
  ApiError,
  CURRENT_ACTOR_ID,
  PRODUCT_NAME_PROFILE_KEY,
  getAllowedEvents,
  getIntake,
  getProductSpace,
  intakeDisplayName,
} from "@/lib/api";
import { ProductsSubnav } from "../products-subnav";
import { DraftProfileForm } from "../draft-profile-form";
import { IntakeActions } from "../intake-actions";
import styles from "../products.module.css";

export const dynamic = "force-dynamic";

export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ intakeId: string }>;
}) {
  const { intakeId } = await params;
  const t = await getTranslations("products");
  const tStatus = await getTranslations("intake.status");

  let intake;
  let allowedEvents: string[] = [];
  try {
    [intake, { allowed_events: allowedEvents }] = await Promise.all([
      getIntake(intakeId),
      getAllowedEvents(intakeId),
    ]);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  // 已发起建模（approved→modeling）后产品空间可能已生成；未生成时端点 404，本段不渲染。
  const space = await getProductSpace(intakeId);

  const profileEntries = Object.entries(intake.profile);
  const isDraft = intake.status === "draft";
  const isCategoryCreating = intake.status === "category_creating";

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

      {isCategoryCreating && <p className={styles.notice}>{t("neutralAnalyzing")}</p>}

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

      {isDraft && (
        <section>
          <h2 className={styles.subtitle}>{t("editProfileTitle")}</h2>
          {CURRENT_ACTOR_ID ? (
            <DraftProfileForm
              intakeId={intake.intake_id}
              currentName={intake.profile[PRODUCT_NAME_PROFILE_KEY] ?? ""}
            />
          ) : (
            <p className={styles.errorText} role="status">
              {t("actorUnconfigured")}
            </p>
          )}
        </section>
      )}

      <section>
        <h2 className={styles.subtitle}>{t("actionsTitle")}</h2>
        {CURRENT_ACTOR_ID ? (
          <IntakeActions intakeId={intake.intake_id} allowedEvents={allowedEvents} />
        ) : (
          <p className={styles.errorText} role="status">
            {t("actorUnconfigured")}
          </p>
        )}
      </section>

      {space && (
        <section>
          <h2 className={styles.subtitle}>{t("spaceTitle")}</h2>
          <dl className={styles.detailList}>
            <dt>{t("space.fieldId")}</dt>
            <dd className={styles.mono}>{space.product_space_id}</dd>
            <dt>{t("space.fieldLifecycle")}</dt>
            <dd className={styles.mono}>{space.lifecycle}</dd>
          </dl>
          <details className={styles.snapshotDetails}>
            <summary>{t("space.snapshot")}</summary>
            <pre className={styles.snapshotPre}>
              {JSON.stringify(space.profile_snapshot, null, 2)}
            </pre>
          </details>
        </section>
      )}

      <Link href="/products" className={styles.backLink}>
        {t("detail.back")}
      </Link>
    </div>
  );
}

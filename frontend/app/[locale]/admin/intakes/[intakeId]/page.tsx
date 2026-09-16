import { Link } from "@/i18n/navigation";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import {
  ApiError,
  getAllowedEvents,
  getIntake,
  getProductSpace,
} from "@/lib/api";
import { OpsIntakeActions } from "../ops-intake-actions";
import styles from "../../admin.module.css";

export const dynamic = "force-dynamic";

export default async function AdminIntakeDetailPage({
  params,
}: {
  params: Promise<{ intakeId: string }>;
}) {
  const { intakeId } = await params;
  const t = await getTranslations("admin.opsIntakes");
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

  // start_modeling 后产品空间才生成；端点 404 表示尚未生成，本段不渲染。
  const space = await getProductSpace(intakeId);

  const profileEntries = Object.entries(intake.profile);

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("detailTitle")}</h1>
        <p className={styles.intro}>
          <span className={styles.metaLine}>{intake.intake_id}</span>
        </p>
      </header>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("detailSection")}</h2>
        <dl className={styles.detailList}>
          <dt>{t("fieldIntake")}</dt>
          <dd>{intake.intake_id}</dd>
          <dt>{t("fieldTenant")}</dt>
          <dd>{intake.tenant_id}</dd>
          <dt>{t("fieldStatus")}</dt>
          <dd>
            <span className={styles.planChip}>{tStatus(intake.status)}</span>
          </dd>
          <dt>{t("fieldCategoryPending")}</dt>
          <dd>{intake.category_pending_id ?? "—"}</dd>
        </dl>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("profileTitle")}</h2>
        {profileEntries.length === 0 ? (
          <p className={styles.notice}>{t("profileEmpty")}</p>
        ) : (
          <dl className={styles.detailList}>
            {profileEntries.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("actionsTitle")}</h2>
        <OpsIntakeActions intakeId={intake.intake_id} allowedEvents={allowedEvents} />
      </section>

      {space ? (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t("spaceTitle")}</h2>
          <dl className={styles.detailList}>
            <dt>{t("spaceFieldId")}</dt>
            <dd>{space.product_space_id}</dd>
            <dt>{t("spaceFieldLifecycle")}</dt>
            <dd>{space.lifecycle}</dd>
          </dl>
          <details>
            <summary>{t("spaceSnapshot")}</summary>
            <pre className={styles.payloadPre}>
              {JSON.stringify(space.profile_snapshot, null, 2)}
            </pre>
          </details>
        </section>
      ) : null}

      <Link href="/admin/intakes" className={styles.secondaryButton}>
        {t("backToQueue")}
      </Link>
    </div>
  );
}

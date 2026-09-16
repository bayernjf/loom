import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import { ApiError, CURRENT_ADMIN_ACTOR_ID, getTenant } from "@/lib/api";
import styles from "../../admin.module.css";

export const dynamic = "force-dynamic";

function statusChipClass(status: string): string {
  if (status === "active") return styles.statusActive;
  if (status === "paused") return styles.statusPaused;
  return styles.statusTrial;
}

function timeText(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().slice(0, 16).replace("T", " ");
}

export default async function TenantDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const t = await getTranslations("admin.tenants");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  if (!CURRENT_ADMIN_ACTOR_ID) {
    return (
      <main>
        <h1>{t("detailTitle")}</h1>
        <p className={styles.msgErr}>{tAdmin("unconfigured")}</p>
      </main>
    );
  }

  try {
    const tenant = await getTenant(tenantId);
    return (
      <main>
        <Link href="/admin/tenants" className={styles.secondaryButton}>
          {t("backToList")}
        </Link>
        <h1>{t("detailTitle")}</h1>
        <dl className={styles.detailList}>
          <dt>{t("colTenantId")}</dt>
          <dd>{tenant.tenant_id}</dd>
          <dt>{t("colName")}</dt>
          <dd>{tenant.name ?? "—"}</dd>
          <dt>{t("colPlan")}</dt>
          <dd>
            <span className={styles.planChip}>{tenant.plan}</span>
          </dd>
          <dt>{t("colStatus")}</dt>
          <dd>
            <span className={`${styles.riskChip} ${statusChipClass(tenant.status)}`}>
              {tenant.status}
            </span>
          </dd>
          <dt>{t("colQuota")}</dt>
          <dd>{tenant.monthly_token_quota ?? "—"}</dd>
          <dt>{t("colCreated")}</dt>
          <dd>{timeText(tenant.created_at)}</dd>
        </dl>

        <h2 className={styles.sectionTitle}>{t("onboardingTitle")}</h2>
        <p className={styles.onboardingNote}>{t("onboardingNote")}</p>
        <dl className={styles.detailList}>
          <dt>{t("intakeCount")}</dt>
          <dd>{tenant.onboarding.intakes}</dd>
          <dt>{t("spaceCount")}</dt>
          <dd>{tenant.onboarding.product_spaces}</dd>
          <dt>{t("firstModelingStarted")}</dt>
          <dd>{tenant.onboarding.first_modeling_started ? t("yes") : t("no")}</dd>
        </dl>
      </main>
    );
  } catch (err) {
    const key =
      err instanceof ApiError && [403, 404, 422].includes(err.status)
        ? String(err.status)
        : "unknown";
    return (
      <main>
        <Link href="/admin/tenants" className={styles.secondaryButton}>
          {t("backToList")}
        </Link>
        <h1>{t("detailTitle")}</h1>
        <p className={styles.msgErr}>{tError(key)}</p>
      </main>
    );
  }
}

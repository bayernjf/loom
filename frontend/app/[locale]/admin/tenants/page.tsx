import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  listTenants,
  type TenantView,
} from "@/lib/api";
import { ProvisionTenantForm } from "./provision-form";
import { TenantRowActions } from "./tenant-row-actions";
import styles from "../admin.module.css";

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

export default async function TenantsPage() {
  const t = await getTranslations("admin.tenants");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  if (!CURRENT_ADMIN_ACTOR_ID) {
    return (
      <main>
        <h1>{t("title")}</h1>
        <p className={styles.msgErr}>{tAdmin("unconfigured")}</p>
      </main>
    );
  }

  let tenants: TenantView[];
  try {
    tenants = await listTenants();
  } catch (err) {
    const key =
      err instanceof ApiError && [403, 404, 422].includes(err.status)
        ? String(err.status)
        : "unknown";
    return (
      <main>
        <h1>{t("title")}</h1>
        <p className={styles.msgErr}>{tError(key)}</p>
      </main>
    );
  }

  return (
    <main>
      <h1>{t("title")}</h1>
      <p>{t("intro")}</p>

      <ProvisionTenantForm />

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>{t("colTenantId")}</th>
              <th>{t("colName")}</th>
              <th>{t("colPlan")}</th>
              <th>{t("colStatus")}</th>
              <th>{t("colQuota")}</th>
              <th>{t("colCreated")}</th>
              <th>{t("colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {tenants.length === 0 ? (
              <tr>
                <td colSpan={7} className={styles.emptyRow}>
                  {t("empty")}
                </td>
              </tr>
            ) : (
              tenants.map((tenant) => (
                <tr key={tenant.tenant_id}>
                  <td>
                    <Link href={`/admin/tenants/${encodeURIComponent(tenant.tenant_id)}`}>
                      {tenant.tenant_id}
                    </Link>
                  </td>
                  <td>{tenant.name ?? "—"}</td>
                  <td>
                    <span className={styles.planChip}>{tenant.plan}</span>
                  </td>
                  <td>
                    <span className={`${styles.riskChip} ${statusChipClass(tenant.status)}`}>
                      {tenant.status}
                    </span>
                  </td>
                  <td>{tenant.monthly_token_quota ?? "—"}</td>
                  <td>{timeText(tenant.created_at)}</td>
                  <td>
                    <TenantRowActions
                      tenantId={tenant.tenant_id}
                      currentPlan={tenant.plan}
                      status={tenant.status}
                    />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}

import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";

import { ApiError, listStaffKeys } from "@/lib/api";
import styles from "../admin.module.css";
import { IssueStaffKeyIsland } from "./issue-staff-island";
import { RevokeStaffKeyButton } from "./revoke-staff-island";

export const dynamic = "force-dynamic";

// Q178：内部运营个人访问令牌（PAT）治理页（staff_auth 后端三端点的前端消费）。
// 列表只读 RSC，签发/吊销走 client 岛 → Server Action；status 枚举原样直出。
// 门控开启后未认证访问由 lib/api 层 401 重定向到 /admin/login（错误向上冒泡）。
type SearchParams = Record<string, string | string[] | undefined>;

function fmt(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}

export default async function StaffKeysPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.staffKeys");
  const sp = await searchParams;
  const includeRevoked = sp.include_revoked === "true" || sp.include_revoked === "1";

  let keys: Awaited<ReturnType<typeof listStaffKeys>> = [];
  let failed = false;
  try {
    keys = await listStaffKeys({ includeRevoked });
  } catch (err) {
    if (err instanceof ApiError && [400, 403, 404, 409, 422].includes(err.status)) {
      failed = true;
    } else {
      throw err;
    }
  }

  return (
    <main className={styles.page} data-testid="staff-keys-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <IssueStaffKeyIsland />

      <section className={styles.section}>
        <div className={styles.chipRow}>
          <h2 className={styles.sectionTitle}>{t("listTitle")}</h2>
          {includeRevoked ? (
            <Link href="/admin/staff-keys" className={styles.secondaryButton}>
              {t("hideRevoked")}
            </Link>
          ) : (
            <Link
              href="/admin/staff-keys?include_revoked=true"
              className={styles.secondaryButton}
            >
              {t("showRevoked")}
            </Link>
          )}
        </div>

        {failed && <p className={styles.msgErr}>{t("loadFailed")}</p>}
        {!failed && keys.length === 0 && (
          <p className={styles.notice}>{t("empty")}</p>
        )}

        {keys.length > 0 && (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colStaff")}</th>
                  <th>{t("colName")}</th>
                  <th>{t("colRoles")}</th>
                  <th>{t("colPrefix")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colCreated")}</th>
                  <th>{t("colLastUsed")}</th>
                  <th>{t("colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => {
                  const revoked = key.status === "revoked";
                  return (
                    <tr key={key.key_id}>
                      <td>
                        <span className={styles.metaLine}>{key.staff_id}</span>
                      </td>
                      <td>{key.staff_name}</td>
                      <td>
                        <span className={styles.chipRow}>
                          {key.roles.map((role) => (
                            <span key={role} className={styles.chip}>
                              <code>{role}</code>
                            </span>
                          ))}
                        </span>
                      </td>
                      <td>
                        <span className={styles.metaLine}>{key.key_prefix}</span>
                      </td>
                      <td>
                        <span
                          className={`${styles.chip} ${
                            revoked ? "" : styles.chipActive
                          }`}
                        >
                          {key.status}
                        </span>
                      </td>
                      <td>{fmt(key.created_at)}</td>
                      <td>{fmt(key.last_used_at)}</td>
                      <td>
                        <RevokeStaffKeyButton
                          keyId={key.key_id}
                          staffName={key.staff_name}
                          revoked={revoked}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

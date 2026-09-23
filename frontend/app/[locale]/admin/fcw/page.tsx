import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

import { ApiError, CURRENT_ADMIN_ACTOR_ID, listAdminFcw } from "@/lib/api";
import styles from "../admin.module.css";
import { MaterialIsland } from "./material-island";

export const dynamic = "force-dynamic";

// Q177：D3.5 白名单组装引擎运营只读首片（02 C1.121）。跨租户分页浏览已发证
// FCW（tenant_id 可空＝全部），行内按需展开六层原料包；纯只读 RSC，枚举码原样直出。
type SearchParams = Record<string, string | string[] | undefined>;

const PAGE_SIZE = 50;

function oneParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value.trim() : undefined;
}

function parseOffset(value: string | undefined): number {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : 0;
}

function shortId(value: string): string {
  return value.slice(0, 8);
}

function fmt(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}

export default async function FcwAdminPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.fcw");
  const sp = await searchParams;
  const tenantId = oneParam(sp.tenant_id);
  const offset = parseOffset(oneParam(sp.offset));

  let page: Awaited<ReturnType<typeof listAdminFcw>> | null = null;
  let failed = false;
  let missingRole = false;
  if (CURRENT_ADMIN_ACTOR_ID) {
    try {
      page = await listAdminFcw({ tenantId, limit: PAGE_SIZE, offset });
    } catch (err) {
      if (err instanceof ApiError && [403, 404, 409, 422].includes(err.status)) {
        failed = true;
        missingRole = err.status === 403;
      } else {
        throw err;
      }
    }
  }

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + items.length, total);
  const queryFor = (nextOffset: number) => {
    const q: Record<string, string> = {};
    if (tenantId) q.tenant_id = tenantId;
    if (nextOffset > 0) q.offset = String(nextOffset);
    return { pathname: "/admin/fcw", query: q };
  };

  return (
    <main className={styles.page} data-testid="fcw-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <form method="get" className={styles.filters} data-testid="fcw-tenant-filter">
        <label className={styles.filterField}>
          <span>{t("tenantLabel")}</span>
          <input
            type="text"
            name="tenant_id"
            defaultValue={tenantId ?? ""}
            placeholder={t("tenantPlaceholder")}
          />
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("querySubmit")}
        </button>
        {tenantId ? (
          <Link href={{ pathname: "/admin/fcw" }} className={styles.secondaryButton}>
            {t("reset")}
          </Link>
        ) : null}
      </form>

      {!CURRENT_ADMIN_ACTOR_ID ? (
        <p className={styles.msgErr}>{t("actorUnconfigured")}</p>
      ) : failed ? (
        <p className={styles.msgErr}>
          {missingRole ? t("actorMissingRole") : t("loadFailed")}
        </p>
      ) : (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t("listTitle")}</h2>
          {items.length === 0 ? (
            <p className={styles.notice}>{t("empty")}</p>
          ) : (
            <>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>{t("colFinal")}</th>
                      <th>{t("colTenant")}</th>
                      <th>{t("colPlatform")}</th>
                      <th>{t("colSlot")}</th>
                      <th>{t("colGoal")}</th>
                      <th>{t("colScore")}</th>
                      <th>{t("colStatus")}</th>
                      <th>{t("colCreated")}</th>
                      <th>{t("colAction")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((fcw) => (
                      <tr key={fcw.final_id}>
                        <td>
                          <span className={styles.metaLine} title={fcw.final_id}>
                            {shortId(fcw.final_id)}
                          </span>
                        </td>
                        <td>
                          <span className={styles.metaLine}>{fcw.tenant_id}</span>
                        </td>
                        <td>{fcw.platform}</td>
                        <td>
                          <span className={styles.metaLine} title={fcw.slot_id}>
                            {shortId(fcw.slot_id)}
                          </span>
                        </td>
                        <td>{fcw.goal}</td>
                        <td>{fcw.score === null ? "—" : fcw.score.toFixed(1)}</td>
                        <td>
                          <span
                            className={`${styles.chip} ${
                              fcw.publish_status === "published"
                                ? styles.chipActive
                                : ""
                            }`}
                          >
                            {fcw.publish_status}
                          </span>
                        </td>
                        <td>{fmt(fcw.created_at)}</td>
                        <td>
                          <MaterialIsland finalId={fcw.final_id} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={styles.metaLine}>
                {t("pageInfo", { from, to, total })}
              </p>
              <div className={styles.pager}>
                {offset > 0 ? (
                  <Link
                    href={queryFor(Math.max(0, offset - PAGE_SIZE))}
                    className={styles.secondaryButton}
                  >
                    {t("prev")}
                  </Link>
                ) : null}
                {page?.has_more ? (
                  <Link
                    href={queryFor(offset + PAGE_SIZE)}
                    className={styles.secondaryButton}
                  >
                    {t("next")}
                  </Link>
                ) : null}
              </div>
            </>
          )}
        </section>
      )}
    </main>
  );
}

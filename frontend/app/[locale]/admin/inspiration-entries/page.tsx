import { formatDateTimeLocal } from "@/lib/time";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { getTranslations } from "next-intl/server";

import { ApiError, listInspirationEntries } from "@/lib/api";
import type { InspirationEntryView } from "@/lib/api";
import styles from "../admin.module.css";
import { CreateEntryIsland } from "./create-island";
import { EntryRowActions } from "./edit-island";

export const dynamic = "force-dynamic";

// Q359：租户灵感库运营配置台（Q358 后端四端点的前端消费）。tenant_id 必填查询，
// layer/product_space_id/enabled 可选过滤；layer 枚举码（common/product）原样直出。
// 列表只读 RSC；新建/编辑/启停/删除全部走 client 岛 → Server Action（operations/
// platform_admin 写闸，三次写均落审计）。
type SearchParams = Record<string, string | string[] | undefined>;

function oneParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value.trim() : undefined;
}

function fmt(iso: string | null): string {
  return formatDateTimeLocal(iso);
}

export default async function InspirationEntriesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.inspirationEntries");
  const tError = await getTranslations("error");
  const sp = await searchParams;
  const tenantId = oneParam(sp.tenant_id);
  const layerRaw = oneParam(sp.layer);
  const layer =
    layerRaw === "common" || layerRaw === "product" ? layerRaw : undefined;
  const productSpaceId = oneParam(sp.product_space_id);
  const enabledRaw = oneParam(sp.enabled);
  const enabled =
    enabledRaw === "true" ? true : enabledRaw === "false" ? false : undefined;

  let entries: InspirationEntryView[] = [];
  let failed = false;
  let failedStatus = 0;
  if (tenantId) {
    try {
      entries = await listInspirationEntries({
        tenantId,
        layer,
        productSpaceId,
        enabled,
      });
    } catch (err) {
      if (err instanceof ApiError && [403, 404, 409, 422].includes(err.status)) {
        failed = true;
        failedStatus = err.status;
      } else {
        throw err;
      }
    }
  }

  return (
    <main className={styles.page} data-testid="inspiration-entries-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <form method="get" className={styles.filters} data-testid="inspiration-filter">
        <label className={styles.filterField}>
          <span>{t("tenantLabel")}</span>
          <input
            type="text"
            name="tenant_id"
            defaultValue={tenantId ?? ""}
            placeholder={t("tenantPlaceholder")}
          />
        </label>
        <label className={styles.filterField}>
          <span>{t("layerLabel")}</span>
          <select name="layer" defaultValue={layer ?? ""}>
            <option value="">{t("layerAll")}</option>
            <option value="common">common</option>
            <option value="product">product</option>
          </select>
        </label>
        <label className={styles.filterField}>
          <span>{t("enabledLabel")}</span>
          <select name="enabled" defaultValue={enabledRaw ?? ""}>
            <option value="">{t("enabledAll")}</option>
            <option value="true">{t("stateEnabled")}</option>
            <option value="false">{t("stateDisabled")}</option>
          </select>
        </label>
        <label className={styles.filterField}>
          <span>{t("productSpaceLabel")}</span>
          <input
            type="text"
            name="product_space_id"
            defaultValue={productSpaceId ?? ""}
            placeholder={t("productSpacePlaceholder")}
          />
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("querySubmit")}
        </button>
      </form>

      {!tenantId && <p className={styles.notice}>{t("needTenant")}</p>}
      {tenantId && failed && (
        <ErrorState
          title={t("loadFailed")}
          code={[403, 404, 409, 422].includes(failedStatus) ? String(failedStatus) : undefined}
          hint={tError("retryHint")}
          retryLabel={tError("retry")}
        />
      )}

      {tenantId && !failed && (
        <>
          <CreateEntryIsland tenantId={tenantId} />

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("listTitle")}</h2>
            {entries.length === 0 ? (
              <EmptyState title={t("empty")} />
            ) : (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>{t("colContent")}</th>
                      <th>{t("colLayer")}</th>
                      <th>{t("colProductSpace")}</th>
                      <th>{t("colTags")}</th>
                      <th>{t("colEnabled")}</th>
                      <th className="num">{t("colUsage")}</th>
                      <th>{t("colUpdated")}</th>
                      <th>{t("colAction")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr key={entry.entry_id}>
                        <td>
                          <span className={styles.metaLine}>
                            {entry.entry_id.slice(0, 8)}
                          </span>
                          <br />
                          {entry.content}
                        </td>
                        <td>
                          <span className={styles.chip}>{entry.layer}</span>
                        </td>
                        <td>
                          {entry.product_space_id ? (
                            <span className={styles.metaLine}>
                              {entry.product_space_id}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          {entry.tags.length > 0 ? (
                            <span className={styles.chipRow}>
                              {entry.tags.map((tag) => (
                                <span key={tag} className={styles.chip}>
                                  {tag}
                                </span>
                              ))}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          <span
                            className={`${styles.chip} ${
                              entry.enabled ? styles.chipActive : ""
                            }`}
                          >
                            {entry.enabled
                              ? t("stateEnabled")
                              : t("stateDisabled")}
                          </span>
                        </td>
                        <td className="num">{entry.usage_count}</td>
                        <td>{fmt(entry.updated_at)}</td>
                        <td>
                          <EntryRowActions
                            entryId={entry.entry_id}
                            content={entry.content}
                            tags={entry.tags}
                            enabled={entry.enabled}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}

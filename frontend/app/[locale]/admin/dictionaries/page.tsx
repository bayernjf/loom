import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";

import { ApiError, listDowngradeActions, type DowngradeActionView } from "@/lib/api";
import styles from "../admin.module.css";
import { DowngradeActionEditIsland } from "./edit-island";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

// Q306：Q38 降级动作字典管理面（docs/02:141 用户原话的六项初始动作）。
// 六码由迁移 0051 播种、不可由界面删；界面填的是中文名与「为什么用这个动作」——
// 这两项原文未给出（【原文未给出，待补】），所以种子为 NULL，等运营回填。
export default async function DictionariesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.dictionaries");
  const sp = await searchParams;
  const includeArchived = sp.include_archived === "true" || sp.include_archived === "1";

  let rows: DowngradeActionView[] = [];
  let failed = false;
  try {
    rows = await listDowngradeActions({ includeArchived });
  } catch (err) {
    if (err instanceof ApiError && [400, 403, 404, 422].includes(err.status)) {
      failed = true;
    } else {
      throw err;
    }
  }

  return (
    <main className={styles.page} data-testid="dictionaries-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <section className={styles.section}>
        <div className={styles.chipRow}>
          <h2 className={styles.sectionTitle}>{t("actionsTitle")}</h2>
          {includeArchived ? (
            <Link href="/admin/dictionaries" className={styles.secondaryButton}>
              {t("hideArchived")}
            </Link>
          ) : (
            <Link
              href="/admin/dictionaries?include_archived=true"
              className={styles.secondaryButton}
            >
              {t("showArchived")}
            </Link>
          )}
        </div>

        {failed && <p className={styles.msgErr}>{t("loadFailed")}</p>}
        {!failed && rows.length === 0 && <p className={styles.notice}>{t("empty")}</p>}

        {!failed && rows.length > 0 && (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colCode")}</th>
                  <th>{t("colName")}</th>
                  <th>{t("colWhy")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.code}>
                    <td>
                      <code>{row.code}</code>
                    </td>
                    <td>{row.name ?? <span className={styles.notice}>{t("pendingFill")}</span>}</td>
                    <td>{row.why ?? ""}</td>
                    <td>{row.status}</td>
                    <td>
                      <DowngradeActionEditIsland
                        code={row.code}
                        name={row.name ?? ""}
                        why={row.why ?? ""}
                        archived={row.status !== "active"}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className={styles.metaLine}>{t("editRequiresToken")}</p>
      </section>
    </main>
  );
}

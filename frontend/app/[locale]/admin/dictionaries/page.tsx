import { getTranslations } from "next-intl/server";
import { EmptyState } from "@/components/empty-state";
import { Link } from "@/i18n/navigation";

import {
  ApiError,
  listDowngradeActions,
  listPoolOptions,
} from "@/lib/api";
import styles from "../admin.module.css";
import { DowngradeActionEditIsland } from "./edit-island";
import { PoolOptionEditIsland } from "./pool-edit-island";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

async function load<T>(fn: () => Promise<T>): Promise<{ rows: T; failed: boolean }> {
  try {
    return { rows: await fn(), failed: false };
  } catch (err) {
    if (err instanceof ApiError && [400, 403, 404, 422].includes(err.status)) {
      return { rows: [] as T, failed: true };
    }
    throw err;
  }
}

// Q306：Q38 降级动作字典管理面（docs/02:141 用户原话的六项初始动作）。
// Q308：同页第二屏＝Q43 17 池选项字典（docs/02:155）。
// 六码与十七池都由迁移播种、不可由界面增删；界面填的是降级动作的中文名与理由
// （这两项原文未给出，【原文未给出，待补】，种子为 NULL），以及每池的可选值
// （原文同样未给候选值，种子为空数组）。
export default async function DictionariesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.dictionaries");
  const sp = await searchParams;
  const includeArchived = sp.include_archived === "true" || sp.include_archived === "1";

  // 两口分开载、各自兜错：Q306 查实过 Promise.all 会让一个口 403 把整屏一起打塌。
  const actions = await load(() => listDowngradeActions({ includeArchived }));
  const pools = await load(() => listPoolOptions({ includeArchived }));

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

        {actions.failed && <p className={styles.msgErr}>{t("loadFailed")}</p>}
        {!actions.failed && actions.rows.length === 0 && (
          <EmptyState title={t("empty")} />
        )}

        {!actions.failed && actions.rows.length > 0 && (
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
                {actions.rows.map((row) => (
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

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("poolsTitle")}</h2>
        <p className={styles.metaLine}>{t("poolsIntro")}</p>

        {pools.failed && <p className={styles.msgErr}>{t("loadFailed")}</p>}
        {!pools.failed && pools.rows.length === 0 && (
          <p className={styles.notice}>{t("poolsEmpty")}</p>
        )}

        {!pools.failed && pools.rows.length > 0 && (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colPool")}</th>
                  <th>{t("colOptions")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {pools.rows.map((row) => (
                  <tr key={row.pool}>
                    <td>
                      <code>{row.pool}</code>
                    </td>
                    <td>
                      {row.options.length === 0 ? (
                        <span className={styles.notice}>{t("pendingFill")}</span>
                      ) : (
                        <span className={styles.chipRow}>
                          {row.options.map((option) => (
                            <span key={option} className={styles.chip}>
                              {option}
                            </span>
                          ))}
                        </span>
                      )}
                    </td>
                    <td>{row.status}</td>
                    <td>
                      <PoolOptionEditIsland
                        pool={row.pool}
                        options={row.options}
                        archived={row.status !== "active"}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

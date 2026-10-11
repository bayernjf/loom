import { formatDateTimeLocal } from "@/lib/time";
import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";

import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  listChangeLedger,
  type ChangeLedgerPage,
} from "@/lib/api";
import styles from "../admin.module.css";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

// Q344：回滚中心＝Q334 甲案「变更-回滚清单」只读聚合面的界面片。
// 五机制码与 app/core/change_ledger/service.py 的 MECHANISM_ACTIONS 键同源；
// 系统标识一律原样展示、不翻译（docs/18 口径），所以这里只列码、不配中文名。
const MECHANISMS = [
  "config_center",
  "pws",
  "fcw",
  "wordlist",
  "skill_prompt",
] as const;

const PAGE_SIZE = 50;

function single(value: string | string[] | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function ledgerPath(mechanism: string, offset: number): string {
  const params = new URLSearchParams();
  if (mechanism) params.set("mechanism", mechanism);
  if (offset > 0) params.set("offset", String(offset));
  const qs = params.toString();
  return `/admin/change-ledger${qs ? `?${qs}` : ""}`;
}

export default async function ChangeLedgerAdminPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.changeLedger");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");
  const sp = await searchParams;

  const mechanismParam = single(sp.mechanism);
  // 未知机制码在后端是"返回空集"的既定契约（test_unknown_mechanism_returns_empty），
  // 但界面把它当非法筛选直接拒掉，免得运营把打错的筛选看成"这五套没动过"。
  const badMechanism =
    mechanismParam !== "" &&
    !(MECHANISMS as readonly string[]).includes(mechanismParam);
  const mechanism = badMechanism ? "" : mechanismParam;
  const offsetParam = Number(single(sp.offset));
  const offset = Number.isInteger(offsetParam) && offsetParam >= 0 ? offsetParam : 0;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    return (
      <main className={styles.page} data-testid="change-ledger-admin">
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.msgErr}>{tAdmin("unconfigured")}</p>
      </main>
    );
  }

  let page: ChangeLedgerPage;
  try {
    page = badMechanism
      ? { total: 0, items: [] }
      : await listChangeLedger({
          mechanism: mechanism || undefined,
          limit: PAGE_SIZE,
          offset,
        });
  } catch (err) {
    const key =
      err instanceof ApiError && [400, 403, 404, 422].includes(err.status)
        ? String(err.status)
        : "unknown";
    return (
      <main className={styles.page} data-testid="change-ledger-admin">
        <h1 className={styles.title}>{t("title")}</h1>
        <ErrorState
          title={tError(key)}
          code={key === "unknown" ? undefined : key}
          hint={tError("retryHint")}
          retryLabel={tError("retry")}
        />
      </main>
    );
  }

  const rows = page.items;
  const prevOffset = offset - PAGE_SIZE;
  const hasNext = rows.length > 0 && offset + rows.length < page.total;

  return (
    <main className={styles.page} data-testid="change-ledger-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <section className={styles.section}>
        <div className={styles.filters}>
          <div className={styles.filterGroup}>
            <span className={styles.filterField}>{t("filterMechanism")}</span>
            <span className={styles.chipRow}>
              <Link
                href={ledgerPath("", 0)}
                className={mechanism ? styles.chip : styles.chipActive}
                scroll={false}
              >
                {t("filterAll")}
              </Link>
              {MECHANISMS.map((code) => (
                <Link
                  key={code}
                  href={ledgerPath(code, 0)}
                  className={
                    mechanism === code ? styles.chipActive : styles.chip
                  }
                  scroll={false}
                >
                  {code}
                </Link>
              ))}
            </span>
          </div>
        </div>

        {badMechanism && (
          <p className={styles.msgErr} data-testid="change-ledger-bad-mechanism">
            {t("badMechanism", { mechanism: mechanismParam })}
          </p>
        )}

        <p className={styles.metaLine}>
          {t("meta", { total: page.total, size: PAGE_SIZE })}
        </p>

        {rows.length === 0 ? (
          <EmptyState title={t("empty")} hint={t("emptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colTime")}</th>
                  <th>{t("colMechanism")}</th>
                  <th>{t("colAction")}</th>
                  <th>{t("colEntity")}</th>
                  <th>{t("colActor")}</th>
                  <th>{t("colRollback")}</th>
                  <th>{t("colSurface")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{formatDateTimeLocal(row.created_at)}</td>
                    <td>
                      <code>{row.mechanism}</code>
                    </td>
                    <td>
                      <code>{row.action}</code>
                    </td>
                    <td>
                      {row.entity_id ? (
                        <>
                          <code>{row.entity_type}</code> ·{" "}
                          <code>{row.entity_id}</code>
                        </>
                      ) : (
                        <span className={styles.notice}>—</span>
                      )}
                    </td>
                    <td>{row.actor_id ?? "—"}</td>
                    <td>
                      <span className={styles.chip}>{row.rollbackability}</span>
                    </td>
                    <td>
                      {/* 提示串含未解析占位符（如 {key}），照真进程实测只作文本展示、不做跳转。 */}
                      {row.ops_surface ? (
                        <code>{row.ops_surface}</code>
                      ) : (
                        <span className={styles.notice}>
                          {t("surfaceNone")}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {(offset > 0 || hasNext) && (
          <p className={styles.chipRow}>
            {offset > 0 ? (
              <Link
                href={ledgerPath(mechanism, prevOffset > 0 ? prevOffset : 0)}
                className={styles.secondaryButton}
                scroll={false}
              >
                {t("pagerPrev")}
              </Link>
            ) : (
              <span className={styles.pagerDisabled}>{t("pagerPrev")}</span>
            )}
            {hasNext ? (
              <Link
                href={ledgerPath(mechanism, offset + PAGE_SIZE)}
                className={styles.secondaryButton}
                scroll={false}
              >
                {t("pagerNext")}
              </Link>
            ) : (
              <span className={styles.pagerDisabled}>{t("pagerNext")}</span>
            )}
          </p>
        )}

        <p className={styles.metaLine}>{t("surfaceNote")}</p>
      </section>
    </main>
  );
}

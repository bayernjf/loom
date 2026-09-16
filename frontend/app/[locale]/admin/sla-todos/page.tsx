import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ApiError, CURRENT_ADMIN_ACTOR_ID, getSlaTodos, type SlaTodoView } from "@/lib/api";
import styles from "../admin.module.css";

export const dynamic = "force-dynamic";

const TODO_STATUS_FILTERS = ["open", "escalated", "resolved", "all"] as const;
const DEFAULT_STATUS = "open";
const KNOWN_ERROR_STATUSES = new Set([403, 422]);

type SearchParams = Record<string, string | string[] | undefined>;
type Translator = Awaited<ReturnType<typeof getTranslations>>;

function asString(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function timeText(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function slaClassName(state: SlaTodoView["sla_state"]): string {
  if (state === "red") return styles.riskCritical;
  if (state === "yellow") return styles.riskMedium;
  if (state === "resolved") return styles.stateArchived;
  return styles.riskLow;
}

function StatusFilters({ status, t }: { status: string; t: Translator }) {
  return (
    <form method="get" className={styles.filters}>
      <div className={styles.filterFields}>
        <label className={styles.filterField}>
          <span>{t("filterStatus")}</span>
          <select name="status" defaultValue={status}>
            {TODO_STATUS_FILTERS.map((value) => (
              <option key={value} value={value}>
                {t(`filter_${value}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className={styles.primaryButton}>
          {t("apply")}
        </button>
        <Link href="/admin/sla-todos" className={styles.secondaryButton}>
          {t("reset")}
        </Link>
      </div>
    </form>
  );
}

function TodoTable({ todos, t }: { todos: SlaTodoView[]; t: Translator }) {
  if (todos.length === 0) {
    return <p className={styles.notice}>{t("empty")}</p>;
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("colTodo")}</th>
            <th>{t("colTenant")}</th>
            <th>{t("colType")}</th>
            <th>{t("colRole")}</th>
            <th>{t("colEntity")}</th>
            <th>{t("colStatus")}</th>
            <th>{t("colSlaState")}</th>
            <th>{t("colDue")}</th>
            <th>{t("colEscalated")}</th>
          </tr>
        </thead>
        <tbody>
          {todos.map((todo) => (
            <tr key={todo.todo_id}>
              <td>
                <span className={styles.planChip} title={todo.todo_id}>
                  {shortId(todo.todo_id)}
                </span>
              </td>
              <td>{todo.tenant_id}</td>
              <td className={styles.metaLine}>{todo.todo_type}</td>
              <td className={styles.metaLine}>{todo.assignee_role}</td>
              <td className={styles.metaLine} title={todo.entity_id}>
                {todo.entity_type}:{shortId(todo.entity_id)}
              </td>
              <td>
                <span className={styles.planChip}>{todo.status}</span>
              </td>
              <td>
                <span className={`${styles.riskChip} ${slaClassName(todo.sla_state)}`}>
                  {todo.sla_state}
                </span>
              </td>
              <td>{timeText(todo.due_at)}</td>
              <td>{timeText(todo.escalated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function AdminSlaTodosPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const t = await getTranslations("admin.slaTodos");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");

  const rawStatus = asString(sp.status);
  const status = (TODO_STATUS_FILTERS as readonly string[]).includes(rawStatus)
    ? rawStatus
    : DEFAULT_STATUS;

  let body: ReactNode;

  if (!CURRENT_ADMIN_ACTOR_ID) {
    body = <p className={styles.notice}>{tAdmin("unconfigured")}</p>;
  } else {
    try {
      const todos = await getSlaTodos(status);
      body = (
        <>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("filters")}</h2>
            <StatusFilters status={status} t={t} />
            <p className={styles.notice}>{t("yellowNote")}</p>
          </section>
          <section className={styles.section}>
            <TodoTable todos={todos} t={t} />
          </section>
        </>
      );
    } catch (err) {
      const key =
        err instanceof ApiError && KNOWN_ERROR_STATUSES.has(err.status)
          ? String(err.status)
          : "unknown";
      body = <p className={styles.notice}>{tError(key)}</p>;
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>
      {body}
    </div>
  );
}

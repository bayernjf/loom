import { getTranslations } from "next-intl/server";

import { ApiError, listExportJobs } from "@/lib/api";
import type { ExportJobView } from "./actions";
import styles from "../admin.module.css";
import { CreateExportIsland } from "./create-island";
import { DownloadExportButton } from "./download-island";

export const dynamic = "force-dynamic";

// Q168：中台导出任务管理页（Q132/Q137 前端消费）。按租户查任务、创建导出、
// 下载成品；中台面无 RBAC 闸（actor 留痕）。status/format 枚举码原样直出。
type SearchParams = Record<string, string | string[] | undefined>;

function oneParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value.trim() : undefined;
}

function fmt(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}

function shortId(value: string): string {
  return value.slice(0, 8);
}

export default async function ExportsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.exports");
  const sp = await searchParams;
  const tenantId = oneParam(sp.tenant_id);

  let jobs: ExportJobView[] = [];
  let failed = false;
  if (tenantId) {
    try {
      const page = await listExportJobs(tenantId, 100);
      jobs = page.jobs;
    } catch (err) {
      if (err instanceof ApiError && [403, 404, 409, 422].includes(err.status)) {
        failed = true;
      } else {
        throw err;
      }
    }
  }

  return (
    <main className={styles.page} data-testid="exports-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <form method="get" className={styles.filters} data-testid="exports-tenant-filter">
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
      </form>

      {!tenantId && <p className={styles.notice}>{t("needTenant")}</p>}
      {tenantId && failed && <p className={styles.msgErr}>{t("loadFailed")}</p>}

      {tenantId && !failed && (
        <>
          <CreateExportIsland tenantId={tenantId} />

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t("listTitle")}</h2>
            {jobs.length === 0 ? (
              <p className={styles.notice}>{t("empty")}</p>
            ) : (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>{t("colJob")}</th>
                      <th>{t("colFormat")}</th>
                      <th>{t("colStatus")}</th>
                      <th>{t("colRows")}</th>
                      <th>{t("colFile")}</th>
                      <th>{t("colCreated")}</th>
                      <th>{t("colCompleted")}</th>
                      <th>{t("colAction")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.job_id}>
                        <td>
                          <span className={styles.metaLine}>{shortId(job.job_id)}</span>
                          {job.error && (
                            <span className={styles.msgErr}> {job.error}</span>
                          )}
                        </td>
                        <td>{job.format}</td>
                        <td>
                          <span
                            className={`${styles.chip} ${
                              job.status === "completed" ? styles.chipActive : ""
                            }`}
                          >
                            {job.status}
                          </span>
                        </td>
                        <td>{job.row_count}</td>
                        <td>
                          <span className={styles.metaLine}>{job.file_name}</span>
                        </td>
                        <td>{fmt(job.created_at)}</td>
                        <td>{fmt(job.completed_at)}</td>
                        <td>
                          <DownloadExportButton
                            jobId={job.job_id}
                            tenantId={job.tenant_id}
                            status={job.status}
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

import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import {
  ApiError,
  CURRENT_TENANT_ID,
  intakeDisplayName,
  listIntakes,
} from "@/lib/api";
import { ProductsSubnav } from "./products-subnav";
import styles from "./products.module.css";

// 运行时读取服务端 env（LOOM_TENANT_ID / LOOM_API_BASE_URL），不得在构建期静态固化。
export const dynamic = "force-dynamic";

export default async function ProductsPage() {
  const t = await getTranslations("products");
  const te = await getTranslations("error");
  const tStatus = await getTranslations("intake.status");

  let body: React.ReactNode;

  if (!CURRENT_TENANT_ID) {
    body = <p className={styles.notice}>{t("unconfigured")}</p>;
  } else {
    try {
      const list = await listIntakes(CURRENT_TENANT_ID, { limit: 100 });
      body =
        list.items.length === 0 ? (
          <p className={styles.notice}>{t("empty")}</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("columnName")}</th>
                <th>{t("columnStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((intake) => (
                <tr key={intake.intake_id}>
                  <td>
                    <Link
                      href={`/products/${intake.intake_id}`}
                      className={styles.rowLink}
                    >
                      {intakeDisplayName(intake)}
                    </Link>
                  </td>
                  <td>
                    <span className={styles.statusChip}>{tStatus(intake.status)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        );
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      body = (
        <p className={styles.notice}>
          {te(status === 403 || status === 404 || status === 409 || status === 422
            ? String(status)
            : "unknown")}
        </p>
      );
    }
  }

  return (
    <div>
      <ProductsSubnav />
      <div className={styles.headerRow}>
        <h1 className={styles.title}>{t("myProducts")}</h1>
        <Link href="/products/new" className={styles.primaryButton}>
          {t("newProduct")}
        </Link>
      </div>
      {body}
    </div>
  );
}

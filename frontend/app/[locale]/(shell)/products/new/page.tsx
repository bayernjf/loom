import { getTranslations } from "next-intl/server";

import { NewProductForm } from "../new-product-form";
import styles from "../products.module.css";

export default async function NewProductPage() {
  const t = await getTranslations("products");
  return (
    <div>
      <h1 className={styles.title}>{t("new.title")}</h1>
      <NewProductForm />
    </div>
  );
}

import { getTranslations } from "next-intl/server";

import styles from "../../admin.module.css";
import { AssembleIsland } from "./assemble-island";

export const dynamic = "force-dynamic";

// Q249 / D3.5 §3.1 甲：组装工作台（手动单条发证 + 预检只读口）。
// RSC 只负责壳与标题，表单/预检/签发交互全在 client 岛；预检零副作用，
// 签发走既有 E1.1 唯一出口（七 Guard 全绿才 mint final_id）。
export default async function FcwAssemblePage() {
  const t = await getTranslations("admin.fcwAssemble");
  return (
    <section className={styles.section}>
      <h1 className={styles.title}>{t("title")}</h1>
      <AssembleIsland />
    </section>
  );
}

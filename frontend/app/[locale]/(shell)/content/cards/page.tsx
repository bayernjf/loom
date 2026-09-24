import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { CURRENT_TENANT_ID, listMyFcw } from "@/lib/api";

import { CardMaterialIsland } from "./card-material-island";
import { CopyIdButton } from "./copy-id-island";
import styles from "./cards.module.css";
import contentStyles from "../content.module.css";

// Q180 D3.5：客户白名单卡片视图——本租户已发证 FCW 卡片列表 + 行内六层原料包展开。
// Q186：行内补 final_id 复制与原料包 JSON 存盘（D3.5 余项，纯前端）。
// 运行时读取服务端 env，不构建期固化；只读，不触发 Guard、不写审计。
export const dynamic = "force-dynamic";

export default async function FcwCardsPage() {
  const t = await getTranslations("content.cards");

  let body: React.ReactNode;
  if (!CURRENT_TENANT_ID) {
    body = <p className={contentStyles.notice}>{t("unconfigured")}</p>;
  } else {
    const items = await listMyFcw(CURRENT_TENANT_ID);
    body =
      items.length === 0 ? (
        <p className={contentStyles.notice}>{t("empty")}</p>
      ) : (
        <div className={styles.cardList}>
          {items.map((item) => (
            <article key={item.final_id} className={contentStyles.island}>
              <div className={styles.cardHead}>
                <span className={contentStyles.mono}>{item.final_id}</span>
                <span className={contentStyles.statusChip}>
                  {item.publish_status}
                </span>
                <CopyIdButton finalId={item.final_id} />
              </div>
              <dl className={contentStyles.detailList}>
                <dt>{t("columnPlatform")}</dt>
                <dd>{item.platform}</dd>
                <dt>{t("columnGoal")}</dt>
                <dd>{item.goal}</dd>
                <dt>{t("columnCountry")}</dt>
                <dd>{item.country ?? "—"}</dd>
                <dt>{t("columnScore")}</dt>
                <dd>
                  {item.score === null ? "—" : Math.round(item.score * 100)}
                </dd>
                <dt>{t("columnCreated")}</dt>
                <dd className={contentStyles.mono}>
                  {item.created_at ?? "—"}
                </dd>
              </dl>
              <CardMaterialIsland finalId={item.final_id} />
            </article>
          ))}
        </div>
      );
  }

  return (
    <div>
      <h1 className={contentStyles.title}>{t("title")}</h1>
      <nav className={styles.subnav}>
        <Link href="/content">{t("subnavContent")}</Link>
        <span aria-current="page">{t("subnavCards")}</span>
      </nav>
      <p className={contentStyles.notice}>{t("pageNote")}</p>
      {body}
    </div>
  );
}

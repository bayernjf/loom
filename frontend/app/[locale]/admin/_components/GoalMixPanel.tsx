"use client";

// Q44：任务页常驻面板 + 段13 回流报表“目的配比健康度”栏共用。
// 只呈现只读聚合与软提示，不提供任何写操作、不阻断发证。
import { useTranslations } from "next-intl";

import type {
  ContentGoalMix,
  ContentGoalMixRow,
  GoalMixHealth,
} from "@/lib/content-goal-mix";
import styles from "../admin.module.css";

function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function healthClass(health: GoalMixHealth): string {
  if (health === "above" || health === "below") return styles.goalMixBad;
  if (health === "within") return styles.goalMixGood;
  return styles.goalMixMuted;
}

export function GoalMixPanel({
  mix,
  status,
  testId = "goal-mix-panel",
}: {
  mix: ContentGoalMix | null;
  status: "ok" | "unconfigured" | "failed";
  testId?: string;
}) {
  const t = useTranslations("admin.goalMix");

  function healthLabel(health: GoalMixHealth): string {
    switch (health) {
      case "above":
        return t("healthAbove");
      case "below":
        return t("healthBelow");
      case "within":
        return t("healthWithin");
      case "unconfigured":
        return t("healthUnconfigured");
      default:
        return t("healthNoData");
    }
  }

  function targetText(row: ContentGoalMixRow): string {
    if (row.ratio_min === null && row.ratio_max === null) return t("targetUnset");
    if (row.ratio_min === null) return t("targetMax", { value: pct(row.ratio_max) });
    if (row.ratio_max === null) return t("targetMin", { value: pct(row.ratio_min) });
    return t("targetRange", {
      min: pct(row.ratio_min),
      max: pct(row.ratio_max),
    });
  }

  return (
    <div className={styles.goalMixPanel} data-testid={testId}>
      <div className={styles.goalMixHead}>
        <h2 className={styles.sectionTitle}>{t("title")}</h2>
        {status === "ok" && mix && (
          <span className={styles.metaLine}>
            {t("windowLine", {
              from: mix.window.date_from,
              to: mix.window.date_to,
              days: mix.window.days,
            })}
          </span>
        )}
      </div>
      <p className={styles.windowLine}>{t("intro")}</p>

      {status === "unconfigured" && (
        <p className={styles.notice}>{t("tenantUnconfigured")}</p>
      )}
      {status === "failed" && <p className={styles.notice}>{t("loadFailed")}</p>}

      {status === "ok" && mix && (
        <>
          {mix.alerts.map((alert) => (
            <p
              key={`${alert.code}-${alert.health}`}
              className={styles.goalMixAlert}
              data-testid="goal-mix-alert"
              role="status"
            >
              {alert.health === "above"
                ? t("alertAbove", {
                    code: alert.code,
                    actual: pct(alert.actual_ratio),
                    bound: pct(alert.bound),
                  })
                : t("alertBelow", {
                    code: alert.code,
                    actual: pct(alert.actual_ratio),
                    bound: pct(alert.bound),
                  })}
            </p>
          ))}

          <p className={styles.metaLine}>
            {t("summary", {
              total: mix.total,
              window: mix.window.days,
            })}
            {mix.unmapped_count > 0
              ? ` · ${t("unmapped", { count: mix.unmapped_count })}`
              : ""}
          </p>

          {mix.total === 0 && <p className={styles.notice}>{t("noData")}</p>}

          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colGoal")}</th>
                  <th>{t("colCount")}</th>
                  <th>{t("colActual")}</th>
                  <th>{t("colTarget")}</th>
                  <th>{t("colHealth")}</th>
                </tr>
              </thead>
              <tbody>
                {mix.goals.map((row) => (
                  <tr key={row.code}>
                    <td className={styles.mono}>{row.code}</td>
                    <td>{row.count}</td>
                    <td>{pct(row.actual_ratio)}</td>
                    <td>{targetText(row)}</td>
                    <td>
                      <span className={`${styles.goalMixBadge} ${healthClass(row.health)}`}>
                        {healthLabel(row.health)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { Link } from "@/i18n/navigation";
import {
  ApiError,
  CURRENT_TENANT_ID,
  getCurrentTenant,
  getIntakeOverview,
  type TenantOnboarding,
} from "@/lib/api";
import styles from "./workbench.module.css";

export const dynamic = "force-dynamic";

// docs/13 §1.1 的 15 态顺序（与后端 statemachine.STATE_LABELS 一致）；仅渲染计数 > 0 的状态。
const STATUS_ORDER = [
  "draft",
  "ai_recognizing",
  "pending_confirm",
  "pending_params",
  "pending_quota",
  "submitted",
  "in_review",
  "need_more_info",
  "approved",
  "modeling",
  "stored",
  "store_failed",
  "rejected",
  "archived",
  "category_creating",
] as const;

// D5 原文五指标（docs/09 D5 表：今日生成/发布/互动/趋势/健康度）；数据源在段 12/13，V1 禁用挂账。
const FUTURE_METRICS = ["generated", "published", "interactions", "trends", "health"] as const;

const KNOWN_ERROR_STATUSES = new Set([403, 404, 409, 422]);

type StepState = "done" | "active" | "todo";

interface OnboardingStep {
  key: "step1" | "step2" | "step3" | "step4";
  state: StepState;
}

// Q163：四步进度由 onboarding 派生（注册恒完成；建模=intakes>0；AI拆解=product_spaces>0；
// 内容上线=product_spaces>0 近似为进行中，待 FCW 成品精确判断随 V2，甲案待追认）。
function deriveSteps(onboarding: TenantOnboarding): OnboardingStep[] {
  const hasIntakes = onboarding.intakes > 0;
  const hasSpaces = onboarding.product_spaces > 0;
  return [
    { key: "step1", state: "done" },
    { key: "step2", state: hasIntakes ? "done" : "active" },
    { key: "step3", state: hasSpaces ? "done" : hasIntakes ? "active" : "todo" },
    { key: "step4", state: hasSpaces ? "active" : "todo" },
  ];
}

const STATE_BADGE: Record<StepState, string> = {
  done: styles.stepDone,
  active: styles.stepActive,
  todo: styles.stepTodo,
};

const STATE_NAME: Record<StepState, string> = {
  done: styles.stepNameDone,
  active: styles.stepNameActive,
  todo: styles.stepNameTodo,
};

export default async function WorkbenchPage() {
  const t = await getTranslations("workbench");
  const tNav = await getTranslations("nav");
  const tStatus = await getTranslations("intake.status");
  const tError = await getTranslations("error");
  const tOb = await getTranslations("workbench.onboarding");

  let body: ReactNode;
  let onboardingNode: ReactNode = null;

  if (!CURRENT_TENANT_ID) {
    body = <p className={styles.notice}>{t("unconfigured")}</p>;
  } else {
    // Q163：客户首启引导（best-effort；取不到 onboarding 时不渲染引导岛）。
    let onboarding: TenantOnboarding | null = null;
    try {
      const tenant = await getCurrentTenant(CURRENT_TENANT_ID);
      onboarding = tenant.onboarding;
    } catch {
      onboarding = null;
    }

    if (onboarding) {
      const steps = deriveSteps(onboarding);
      const stepLabel = (key: OnboardingStep["key"]) => tOb(key);
      const badgeLabel = (s: StepState) => tOb(s);
      if (onboarding.intakes === 0) {
        // 空态：完整引导卡片 + 去录入产品 CTA。
        onboardingNode = (
          <section className={styles.onboardingCard} data-testid="onboarding-guide">
            <h2 className={styles.onboardingTitle}>{tOb("title")}</h2>
            <p className={styles.onboardingNote}>{tOb("note")}</p>
            <ul className={styles.stepList}>
              {steps.map((step) => (
                <li key={step.key} className={styles.stepRow}>
                  <span className={`${styles.stepBadge} ${STATE_BADGE[step.state]}`}>
                    {badgeLabel(step.state)}
                  </span>
                  <span className={STATE_NAME[step.state]}>{stepLabel(step.key)}</span>
                </li>
              ))}
            </ul>
            <Link href="/products/new" className={styles.onboardingCta}>
              {tOb("cta")}
            </Link>
          </section>
        );
      } else {
        // 已有录入：收起为紧凑进度条。
        onboardingNode = (
          <section
            className={`${styles.card} ${styles.onboardingCompact}`}
            data-testid="onboarding-compact"
          >
            {steps.map((step) => (
              <span key={step.key} className={styles.onboardingCompactStep}>
                <span className={`${styles.stepBadge} ${STATE_BADGE[step.state]}`}>
                  {badgeLabel(step.state)}
                </span>
                <span>{stepLabel(step.key)}</span>
              </span>
            ))}
          </section>
        );
      }
    }

    try {
      const overview = await getIntakeOverview(CURRENT_TENANT_ID);
      const presentStatuses = STATUS_ORDER.filter((code) => (overview.by_status[code] ?? 0) > 0);
      body = (
        <>
          <section className={styles.card} aria-labelledby="product-overview">
            <div className={styles.cardHeader}>
              <h2 id="product-overview" className={styles.cardTitle}>
                {t("productOverview")}
              </h2>
              <Link href="/products" className={styles.textLink}>
                {t("viewAll")}
              </Link>
            </div>
            <p className={styles.totalLine}>
              <span className={styles.totalValue}>{overview.total}</span>
              <span className={styles.totalLabel}>{t("totalProducts")}</span>
            </p>
            {overview.total === 0 ? (
              <p className={styles.empty}>{t("empty")}</p>
            ) : (
              <>
                <p className={styles.statusListTitle}>{t("statusBreakdown")}</p>
                <dl className={styles.statusList}>
                  {presentStatuses.map((code) => (
                    <div key={code} className={styles.statusRow}>
                      <dd className={styles.statusName}>{tStatus(code)}</dd>
                      <dd className={styles.statusCount}>{overview.by_status[code]}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </section>

          <section className={styles.card} aria-labelledby="quick-actions">
            <h2 id="quick-actions" className={styles.cardTitle}>
              {t("quickActions")}
            </h2>
            <div className={styles.actionRow}>
              <Link href="/products/new" className={styles.primaryButton}>
                {t("newProduct")}
              </Link>
              <Link href="/products" className={styles.secondaryButton}>
                {t("viewAll")}
              </Link>
            </div>
          </section>
        </>
      );
    } catch (err) {
      const key = err instanceof ApiError && KNOWN_ERROR_STATUSES.has(err.status)
        ? String(err.status)
        : "unknown";
      body = <p className={styles.notice}>{tError(key)}</p>;
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{tNav("workbench")}</h1>
      </header>

      {onboardingNode}
      {body}

      <ul className={styles.metricGrid}>
        {FUTURE_METRICS.map((metric) => (
          <li key={metric} className={styles.metricCard} aria-disabled="true">
            <div className={styles.metricHeader}>
              <span className={styles.metricName}>{t(`metrics.${metric}`)}</span>
              <span className={styles.v2Badge}>V2</span>
            </div>
            <p className={styles.metricNote}>{t("metricsNote")}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

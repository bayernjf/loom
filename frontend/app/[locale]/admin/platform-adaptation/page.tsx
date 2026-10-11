import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";

import {
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  getAdminContentGoals,
  getAdminFitScore,
  getAdminPublishSlots,
  listAdminAdapterCandidates,
  listAdminDynamicEvents,
  listAdminFitWeights,
  listAdminPcpTemplates,
  listAdminPlatformRules,
  listAdminRecalcCandidates,
  listAdminSlotTypeDefaults,
  matchAdminPlatformRules,
  type AdminAdapterCandidate,
  type AdminDynamicEvent,
  type AdminFitScore,
  type AdminFitWeight,
  type AdminPcpTemplate,
  type AdminPlatformRule,
  type AdminPublishSlot,
  type AdminRecalcCandidate,
  type AdminRuleMatch,
  type AdminSlotTypeDefault,
} from "@/lib/api";
import styles from "../admin.module.css";

export const dynamic = "force-dynamic";

// Q345 建屏＝段7/8 静态底表与 PCP 那族只读口的界面片；Q346 负责人「按你推荐的搞」裁甲
// （docs/19 清单二第 10／11 项）把这族管理端读口统一到 `require_ops_admin_view`
// （operations＋platform_admin）之后，九张读口全部接齐（＋目的字典＝本屏十个来源）。
// 全部只读：写面走 Q203/Q242 已验真 staff 令牌，不在这一屏；Q346 也没动任何写口。
// 枚举码（gate/effect/level/status/score_source/decision）一律原样展示、不翻译（docs/18 口径）。

type SearchParams = Record<string, string | string[] | undefined>;

// error.* 只有这四个状态码键（403/404/409/422）；其余一律落 unknown，
// 不拿一个不存在的文案键去喂 next-intl（Q344 实测过 MISSING_MESSAGE 只在浏览器控制台现形）。
const ERROR_KEYS = ["403", "404", "409", "422"];

function single(value: string | string[] | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

/** 派生值只展示不裁决：后端给的是浮点聚合，界面按 4 位有效截显示，不四舍五入进任何判定。 */
function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(Number(value.toFixed(4)));
}

function cell(value: string | null | undefined): string {
  const v = (value ?? "").trim();
  return v === "" ? "—" : v;
}

/**
 * 后端不约束键名的 JSON 明细（change_list／refs／defaults／missing）折起来原样给运营看。
 * 不猜键名、不挑字段——docs/05 对这些列写明【待补】或自由 JSON，界面替它编列名就是臆造。
 */
function jsonFold(label: string, value: unknown) {
  const count = Array.isArray(value) ? value.length : Object.keys(value ?? {}).length;
  if (count === 0) return <span className={styles.notice}>—</span>;
  return (
    <details data-testid="platform-adaptation-json-fold">
      <summary>{`${label} · ${count}`}</summary>
      <pre className={styles.jsonArea}>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

/** 权重字典逐键列示（键序由后端给，界面不重排、不补 0）。 */
function weightChips(weights: Record<string, number>) {
  return (
    <span className={styles.chipRow}>
      {Object.entries(weights).map(([key, value]) => (
        <code key={key}>
          {key}={num(value)}
        </code>
      ))}
    </span>
  );
}

function adaptPath(input: {
  platform: string;
  slot: string;
  goal: string;
  archived: boolean;
}): string {
  const params = new URLSearchParams();
  if (input.platform) params.set("platform", input.platform);
  if (input.slot) params.set("slot", input.slot);
  if (input.goal) params.set("goal", input.goal);
  if (input.archived) params.set("archived", "1");
  const qs = params.toString();
  return `/admin/platform-adaptation${qs ? `?${qs}` : ""}`;
}

export default async function PlatformAdaptationAdminPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const t = await getTranslations("admin.platformAdaptation");
  const tAdmin = await getTranslations("admin");
  const tError = await getTranslations("error");
  const sp = await searchParams;

  const platform = single(sp.platform);
  const wantedSlot = single(sp.slot);
  const wantedGoal = single(sp.goal);
  const archived = single(sp.archived) === "1";

  if (!CURRENT_ADMIN_ACTOR_ID) {
    return (
      <main className={styles.page} data-testid="platform-adaptation-admin">
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.msgErr}>{tAdmin("unconfigured")}</p>
      </main>
    );
  }

  let slots: AdminPublishSlot[];
  let goalCodes: string[];
  let rules: AdminPlatformRule[];
  let templates: AdminPcpTemplate[];
  let fitWeights: AdminFitWeight[];
  let typeDefaults: AdminSlotTypeDefault[];
  let events: AdminDynamicEvent[];
  let recalc: AdminRecalcCandidate[];
  let adapter: AdminAdapterCandidate[];
  try {
    // 九张主读口一屏取齐：任一口挂了就整屏进错误态（Q340 的 ErrorState 口径，不留半屏）。
    [slots, goalCodes, rules, templates, fitWeights, typeDefaults, events, recalc, adapter] =
      await Promise.all([
        getAdminPublishSlots(platform || undefined, { includeArchived: archived }),
        getAdminContentGoals().then((rows) =>
          rows.filter((row) => row.status === "active").map((row) => row.code),
        ),
        listAdminPlatformRules({ platform: platform || undefined, includeArchived: archived }),
        listAdminPcpTemplates(),
        listAdminFitWeights(),
        listAdminSlotTypeDefaults(),
        listAdminDynamicEvents({ platform: platform || undefined, includeArchived: archived }),
        listAdminRecalcCandidates(),
        listAdminAdapterCandidates(),
      ]);
  } catch (err) {
    const key =
      err instanceof ApiError && ERROR_KEYS.includes(String(err.status))
        ? String(err.status)
        : "unknown";
    return (
      <main className={styles.page} data-testid="platform-adaptation-admin">
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

  // 选中行：筛选后第一行兜底（后端按 code 升序，故默认目标可复现）。
  const slot = slots.find((row) => row.slot_id === wantedSlot) ?? slots[0];
  // 目的：Q34 权重矩阵按目的取，未配矩阵的目的回 incomplete——界面照实说"不凑分"。
  const goal = goalCodes.includes(wantedGoal) ? wantedGoal : goalCodes[0] ?? "";

  let fit: AdminFitScore | null = null;
  let match: AdminRuleMatch | null = null;
  let probeErr = "";
  if (slot && goal) {
    try {
      [fit, match] = await Promise.all([
        getAdminFitScore(slot.slot_id, goal),
        matchAdminPlatformRules({
          platform: slot.platform,
          slotType: slot.slot_type,
          slotId: slot.slot_id,
        }),
      ]);
    } catch (err) {
      // 预演取数失败只降级这一节（档案／规则／模板三节仍然可读），并把状态码原样报出来。
      fit = null;
      match = null;
      probeErr = err instanceof ApiError ? String(err.status) : "unknown";
    }
  }

  const platforms = [...new Set(slots.map((row) => row.platform))].sort();

  return (
    <main className={styles.page} data-testid="platform-adaptation-admin">
      <header className={styles.pageHeader}>
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.intro}>{t("intro")}</p>
      </header>

      <section className={styles.section}>
        <div className={styles.filters}>
          <div className={styles.filterGroup}>
            <span className={styles.filterField}>{t("filterPlatform")}</span>
            <span className={styles.chipRow}>
              <Link
                href={adaptPath({ platform: "", slot: wantedSlot, goal: wantedGoal, archived })}
                className={platform ? styles.chip : styles.chipActive}
                scroll={false}
              >
                {t("filterAll")}
              </Link>
              {platforms.map((code) => (
                <Link
                  key={code}
                  href={adaptPath({ platform: code, slot: "", goal: wantedGoal, archived })}
                  className={platform === code ? styles.chipActive : styles.chip}
                  scroll={false}
                >
                  {code}
                </Link>
              ))}
            </span>
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterField}>{t("filterArchived")}</span>
            <Link
              href={adaptPath({ platform, slot: wantedSlot, goal: wantedGoal, archived: !archived })}
              className={archived ? styles.chipActive : styles.chip}
              scroll={false}
              data-testid="platform-adaptation-archived"
            >
              {archived ? t("archivedOn") : t("archivedOff")}
            </Link>
          </div>
        </div>

        <p className={styles.metaLine}>{t("slotsMeta", { count: slots.length })}</p>

        {slots.length === 0 ? (
          <EmptyState title={t("slotsEmpty")} hint={t("slotsEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colCode")}</th>
                  <th>{t("colName")}</th>
                  <th>{t("colPlatform")}</th>
                  <th>{t("colSlotType")}</th>
                  <th>{t("colCharsMax")}</th>
                  <th>{t("colDuration")}</th>
                  <th>{t("colDims")}</th>
                  <th>{t("colScoreSource")}</th>
                  <th>{t("colRisk")}</th>
                  <th>{t("colGate")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colProbe")}</th>
                </tr>
              </thead>
              <tbody>
                {slots.map((row) => (
                  <tr key={row.slot_id} data-testid="platform-adaptation-slot-row">
                    <td>
                      <code>{row.code}</code>
                    </td>
                    <td>{row.name}</td>
                    <td>{row.platform}</td>
                    <td>
                      <code>{row.slot_type}</code>
                    </td>
                    <td>{num(row.chars_max)}</td>
                    <td>
                      {row.dur_min === null && row.dur_max === null
                        ? "—"
                        : `${num(row.dur_min)}–${num(row.dur_max)}`}
                    </td>
                    <td>
                      {/* 四维原样列：traffic/safe/conv/load，逐键标出免得被读成一个总分。 */}
                      <span className={styles.chipRow}>
                        {(["traffic", "safe", "conv", "load"] as const).map((dim) => (
                          <code key={dim}>
                            {dim}={num(row[dim])}
                          </code>
                        ))}
                      </span>
                    </td>
                    <td>
                      <code>{row.score_source}</code>
                    </td>
                    <td>{cell(row.risk)}</td>
                    <td>
                      <code>{row.gate}</code>
                    </td>
                    <td>
                      <code>{row.status}</code>
                    </td>
                    <td>
                      <Link
                        href={adaptPath({
                          platform,
                          slot: row.slot_id,
                          goal: wantedGoal,
                          archived,
                        })}
                        className={styles.secondaryButton}
                        scroll={false}
                      >
                        {t("probeThis")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("probeTitle")}</h2>

        {probeErr ? (
          <p className={styles.msgErr} data-testid="platform-adaptation-probe-error">
            {t("probeError", { status: probeErr })}
          </p>
        ) : !slot || !fit || !match ? (
          <EmptyState title={t("probeNone")} hint={t("probeNoneHint")} />
        ) : (
          <>
            <div className={styles.filterGroup}>
              <span className={styles.filterField}>{t("filterGoal")}</span>
              <span className={styles.chipRow}>
                {goalCodes.map((code) => (
                  <Link
                    key={code}
                    href={adaptPath({ platform, slot: slot.slot_id, goal: code, archived })}
                    className={goal === code ? styles.chipActive : styles.chip}
                    scroll={false}
                  >
                    {code}
                  </Link>
                ))}
              </span>
            </div>

            <p className={styles.metaLine} data-testid="platform-adaptation-probe-target">
              {t("probeTarget", {
                code: slot.code,
                platform: slot.platform,
                slotType: slot.slot_type,
                goal: goal || "—",
              })}
            </p>

            <p className={styles.metaLine}>
              {fit.incomplete ? t("fitIncomplete") : t("fitScore", { score: num(fit.fit_score) })}
            </p>

            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>{t("colDim")}</th>
                    <th>{t("colScore")}</th>
                    <th>{t("colWeight")}</th>
                    <th>{t("colContribution")}</th>
                  </tr>
                </thead>
                <tbody>
                  {fit.breakdown.map((row) => (
                    <tr key={row.dim} data-testid="platform-adaptation-fit-row">
                      <td>
                        <code>{row.dim}</code>
                      </td>
                      <td>{num(row.score)}</td>
                      <td>{num(row.weight)}</td>
                      <td>{num(row.contribution)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className={styles.metaLine} data-testid="platform-adaptation-match">
              {t("matchEffect", {
                effect: match.effect === null ? t("matchNative") : match.effect,
              })}
            </p>
            <p className={styles.metaLine}>
              {match.matched_rule_ids.length === 0
                ? t("matchNone")
                : t("matchIds", { ids: match.matched_rule_ids.join(", ") })}
            </p>
            <p className={styles.metaLine}>
              {match.events.length === 0
                ? t("eventsNone")
                : t("eventsMeta", { count: match.events.length })}
            </p>
            {match.events.length > 0 && (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>{t("colEventType")}</th>
                      <th>{t("colSeverity")}</th>
                      <th>{t("colWindow")}</th>
                      <th>{t("colNote")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {match.events.map((event) => (
                      <tr key={event.event_id} data-testid="platform-adaptation-event-row">
                        <td>
                          <code>{event.event_type}</code>
                        </td>
                        <td>
                          <code>{event.severity}</code>
                        </td>
                        <td>{event.effective_start}</td>
                        <td>{cell(event.note)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("weightsTitle")}</h2>
        <p className={styles.metaLine}>{t("weightsMeta", { count: fitWeights.length })}</p>
        {fitWeights.length === 0 ? (
          <EmptyState title={t("weightsEmpty")} hint={t("weightsEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colGoal")}</th>
                  <th>{t("colMatrix")}</th>
                  <th>{t("colSigma")}</th>
                  <th>{t("colUpdatedBy")}</th>
                </tr>
              </thead>
              <tbody>
                {fitWeights.map((row) => {
                  const sigma = Object.values(row.weights).reduce((a, b) => a + b, 0);
                  return (
                    <tr key={row.goal} data-testid="platform-adaptation-weight-row">
                      <td>
                        <code>{row.goal}</code>
                      </td>
                      <td>{weightChips(row.weights)}</td>
                      <td>{num(sigma)}</td>
                      <td>{cell(row.updated_by)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {/* 目的字典里没配矩阵的目的＝上面这一族 fit-score 一律"不凑分"的直接原因，两表并读才闭环。 */}
        {goalCodes
          .filter((code) => !fitWeights.some((row) => row.goal === code))
          .map((code) => (
            <p
              key={code}
              className={styles.metaLine}
              data-testid="platform-adaptation-weight-missing"
            >
              {t("weightMissing", { goal: code })}
            </p>
          ))}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("defaultsTitle")}</h2>
        <p className={styles.metaLine}>
          {t("defaultsMeta", { count: typeDefaults.length })}
        </p>
        {typeDefaults.length === 0 ? (
          <EmptyState title={t("defaultsEmpty")} hint={t("defaultsEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colSlotType")}</th>
                  <th>{t("colDailyLimit")}</th>
                  <th>{t("colDefaults")}</th>
                </tr>
              </thead>
              <tbody>
                {typeDefaults.map((row) => (
                  <tr key={row.slot_type} data-testid="platform-adaptation-default-row">
                    <td>
                      <code>{row.slot_type}</code>
                    </td>
                    <td>
                      {row.daily_limit_min === null && row.daily_limit_max === null
                        ? "—"
                        : `${num(row.daily_limit_min)}–${num(row.daily_limit_max)}`}
                    </td>
                    <td>{jsonFold(t("colDefaults"), row.defaults)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("rulesTitle")}</h2>
        <p className={styles.metaLine}>{t("rulesMeta", { count: rules.length })}</p>
        {rules.length === 0 ? (
          <EmptyState title={t("rulesEmpty")} hint={t("rulesEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colLevel")}</th>
                  <th>{t("colPlatform")}</th>
                  <th>{t("colSlotType")}</th>
                  <th>{t("colSlotId")}</th>
                  <th>{t("colCountry")}</th>
                  <th>{t("colEffect")}</th>
                  <th>{t("colNote")}</th>
                  <th>{t("colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((row) => (
                  <tr key={row.rule_id} data-testid="platform-adaptation-rule-row">
                    <td>
                      <code>{row.selector_level}</code>
                    </td>
                    <td>{cell(row.platform)}</td>
                    <td>{cell(row.slot_type)}</td>
                    <td>{row.slot_id ? <code>{row.slot_id}</code> : "—"}</td>
                    <td>{cell(row.country)}</td>
                    <td>
                      <code>{row.effect}</code>
                    </td>
                    <td>{cell(row.note)}</td>
                    <td>
                      <code>{row.status}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("eventsTitle")}</h2>
        <p className={styles.metaLine}>{t("eventsListMeta", { count: events.length })}</p>
        {events.length === 0 ? (
          <EmptyState title={t("eventsEmpty")} hint={t("eventsEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colPlatform")}</th>
                  <th>{t("colSlotId")}</th>
                  <th>{t("colEventType")}</th>
                  <th>{t("colSeverity")}</th>
                  <th>{t("colWindow")}</th>
                  <th>{t("colNote")}</th>
                  <th>{t("colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {events.map((row) => (
                  <tr key={row.event_id} data-testid="platform-adaptation-event-list-row">
                    <td>{row.platform}</td>
                    <td>{row.slot_id ? <code>{row.slot_id}</code> : "—"}</td>
                    <td>
                      <code>{row.event_type}</code>
                    </td>
                    <td>
                      <code>{row.severity}</code>
                    </td>
                    <td>
                      {row.effective_end
                        ? `${row.effective_start} → ${row.effective_end}`
                        : `${row.effective_start} → ${t("windowOpen")}`}
                    </td>
                    <td>{cell(row.note)}</td>
                    <td>
                      <code>{row.status}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("templatesTitle")}</h2>
        <p className={styles.metaLine}>{t("templatesIntro")}</p>
        {templates.length === 0 ? (
          <EmptyState title={t("templatesEmpty")} hint={t("templatesEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colTemplateCode")}</th>
                  <th>{t("colTemplateName")}</th>
                  <th>{t("colSigma")}</th>
                  <th>{t("colWeights")}</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((row) => {
                  const sigma = Object.values(row.weights).reduce((a, b) => a + b, 0);
                  return (
                    <tr key={row.template_id} data-testid="platform-adaptation-template-row">
                      <td>
                        <code>{row.code}</code>
                      </td>
                      <td>{row.name}</td>
                      <td>{num(sigma)}</td>
                      <td>{weightChips(row.weights)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("recalcTitle")}</h2>
        <p className={styles.metaLine}>{t("recalcMeta", { count: recalc.length })}</p>
        {recalc.length === 0 ? (
          <EmptyState title={t("recalcEmpty")} hint={t("recalcEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colCandidate")}</th>
                  <th>{t("colPcp")}</th>
                  <th>{t("colPlatform")}</th>
                  <th>{t("colSource")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colProposed")}</th>
                  <th>{t("colChangeList")}</th>
                  <th>{t("colDecidedBy")}</th>
                </tr>
              </thead>
              <tbody>
                {recalc.map((row) => (
                  <tr key={row.candidate_id} data-testid="platform-adaptation-recalc-row">
                    <td>
                      <code>{row.candidate_id}</code>
                    </td>
                    <td>
                      <code>{row.pcp_id}</code>
                    </td>
                    <td>{row.platform}</td>
                    <td>
                      <code>{row.source}</code>
                    </td>
                    <td>
                      <code>{row.status}</code>
                    </td>
                    <td>{weightChips(row.proposed_weights)}</td>
                    <td>{jsonFold(t("colChangeList"), row.change_list)}</td>
                    <td>
                      {row.status === "rejected"
                        ? cell(row.rejected_reason)
                        : cell(row.approved_by ?? row.created_by)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("adapterTitle")}</h2>
        <p className={styles.metaLine}>{t("adapterMeta", { count: adapter.length })}</p>
        {adapter.length === 0 ? (
          <EmptyState title={t("adapterEmpty")} hint={t("adapterEmptyHint")} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t("colCandidate")}</th>
                  <th>{t("colPlatform")}</th>
                  <th>{t("colSlotType")}</th>
                  <th>{t("colSlotId")}</th>
                  <th>{t("colSource")}</th>
                  <th>{t("colDecision")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colMissing")}</th>
                  <th>{t("colRefs")}</th>
                  <th>{t("colDecidedBy")}</th>
                </tr>
              </thead>
              <tbody>
                {adapter.map((row) => (
                  <tr key={row.candidate_id} data-testid="platform-adaptation-adapter-row">
                    <td>
                      <code>{row.candidate_id}</code>
                    </td>
                    <td>{row.platform}</td>
                    <td>{row.slot_type ? <code>{row.slot_type}</code> : "—"}</td>
                    <td>{row.slot_id ? <code>{row.slot_id}</code> : "—"}</td>
                    <td>
                      <code>{row.source}</code>
                    </td>
                    <td>
                      <code>{cell(row.decision)}</code>
                    </td>
                    <td>
                      <code>{row.status}</code>
                    </td>
                    <td>
                      {/* 模型列就是 Boolean（PT 四态里的 missing＝无生效 PWS、不造假），原样显值。 */}
                      <code>{String(row.missing)}</code>
                    </td>
                    <td>{jsonFold(t("colRefs"), row.refs)}</td>
                    <td>
                      {row.status === "rejected"
                        ? cell(row.rejected_reason)
                        : cell(row.approved_by ?? row.created_by)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className={styles.metaLine}>{t("boundaryNote")}</p>
    </main>
  );
}

"use client";

// Q249 / D3.5 §3.1 甲：组装工作台表单岛。先预检（只读口，零副作用），七 Guard
// 全绿后才解锁签发；预检结果同时给出 3.3 甲的 8 项判断结果映射表。client 岛只
// 调本目录 Server Actions，不直连 lib/api（check-admin 守卫）。
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, useTransition } from "react";

import styles from "../../admin.module.css";
import {
  assembleManualAction,
  getAssembleFormDataAction,
  previewAssembleAction,
  type AdminContentGoal,
  type AdminPublishSlot,
  type AssembleManualBody,
  type ConflictCheckRow,
} from "./actions";

const KNOWN_STATUSES = new Set([401, 403, 404, 409, 422]);

export function AssembleIsland() {
  const t = useTranslations("admin.fcwAssemble");
  const tError = useTranslations("error");

  const [slots, setSlots] = useState<AdminPublishSlot[]>([]);
  const [goals, setGoals] = useState<AdminContentGoal[]>([]);
  const [formFailed, setFormFailed] = useState(false);
  const [formMissingRole, setFormMissingRole] = useState(false);

  const [psId, setPsId] = useState("");
  const [platform, setPlatform] = useState("");
  const [slotId, setSlotId] = useState("");
  const [goal, setGoal] = useState("");
  const [country, setCountry] = useState("");

  const [pending, startTransition] = useTransition();
  const [previewing, setPreviewing] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [preview, setPreview] = useState<
    Awaited<ReturnType<typeof previewAssembleAction>> | null
  >(null);
  const [issued, setIssued] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  const loadForm = useCallback(() => {
    startTransition(async () => {
      const r = await getAssembleFormDataAction();
      if (r.ok) {
        setSlots(r.slots);
        setGoals(r.goals);
      } else if (r.status === "missing_role") {
        setFormMissingRole(true);
      } else {
        setFormFailed(true);
      }
    });
  }, []);

  // 进入页面才拉发布位/目的字典（一次）。
  useEffect(() => {
    loadForm();
  }, [loadForm]);

  const platforms = Array.from(new Set(slots.map((s) => s.platform))).sort();
  const platformSlots = slots.filter(
    (s) => !platform || s.platform === platform,
  );

  function buildBody(): AssembleManualBody | null {
    if (!psId.trim() || !platform || !slotId || !goal) return null;
    return {
      product_space_id: psId.trim(),
      platform,
      slot_id: slotId,
      goal,
      country: country.trim() ? country.trim() : null,
    };
  }

  function runPreview() {
    const body = buildBody();
    if (!body) return;
    setPreviewing(true);
    setErrorText(null);
    setIssued(null);
    startTransition(async () => {
      const r = await previewAssembleAction(body);
      setPreview(r);
      if (!r.ok) {
        setErrorText(failureText(r.status, r.detail));
      }
      setPreviewing(false);
    });
  }

  function runIssue() {
    const body = buildBody();
    if (!body) return;
    setIssuing(true);
    setErrorText(null);
    startTransition(async () => {
      const r = await assembleManualAction(body);
      if (r.ok) {
        setIssued(r.fcw.final_id);
        setPreview(null);
      } else {
        setErrorText(failureText(r.status, r.detail));
      }
      setIssuing(false);
    });
  }

  function failureText(
    status: string | number,
    detail: string | null,
  ): string {
    if (status === "unconfigured") return t("actorUnconfigured");
    if (status === "missing_role") return t("actorMissingRole");
    if (status === "unknown") return tError("unknown");
    if (detail) return detail;
    return tError(KNOWN_STATUSES.has(Number(status)) ? String(status) : "unknown");
  }

  const previewOk = preview?.ok === true;

  return (
    <section className={styles.section} data-testid="fcw-assemble-form">
      <p className={styles.windowLine}>{t("intro")}</p>

      <div className={styles.grid}>
        <label className={styles.fieldLabel}>
          {t("productSpace")}
          <input
            className={styles.input}
            value={psId}
            onChange={(e) => setPsId(e.target.value)}
            placeholder={t("productSpaceHint")}
          />
        </label>

        <label className={styles.fieldLabel}>
          {t("platform")}
          <select
            className={styles.input}
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value);
              setSlotId("");
            }}
          >
            <option value="">—</option>
            {platforms.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.fieldLabel}>
          {t("slot")}
          <select
            className={styles.input}
            value={slotId}
            onChange={(e) => setSlotId(e.target.value)}
          >
            <option value="">—</option>
            {platformSlots
              .filter((s) => s.status === "active")
              .map((s) => (
                <option key={s.slot_id} value={s.slot_id}>
                  {s.code} · {s.name}（{s.platform}）
                </option>
              ))}
          </select>
        </label>

        <label className={styles.fieldLabel}>
          {t("goal")}
          <select
            className={styles.input}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          >
            <option value="">—</option>
            {goals
              .filter((g) => g.status === "active")
              .map((g) => (
                <option key={g.code} value={g.code}>
                  {g.code}
                </option>
              ))}
          </select>
        </label>

        <label className={styles.fieldLabel}>
          {t("country")}
          <input
            className={styles.input}
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            placeholder={t("countryHint")}
          />
        </label>
      </div>

      {formFailed && <p className={styles.notice}>{t("formFailed")}</p>}
      {formMissingRole && <p className={styles.notice}>{t("actorMissingRole")}</p>}

      <div className={styles.actionsRow}>
        <button
          type="button"
          className={styles.primary}
          disabled={previewing || issuing || buildBody() === null}
          onClick={runPreview}
        >
          {previewing ? t("previewing") : t("preview")}
        </button>
        {previewOk && preview.preview.guards_passed && (
          <button
            type="button"
            className={styles.primary}
            disabled={issuing}
            onClick={runIssue}
          >
            {issuing ? t("assembling") : t("issue")}
          </button>
        )}
      </div>

      {errorText && <p className={styles.notice}>{errorText}</p>}

      {issued && (
        <p className={styles.successLine}>
          {t("issuedOk")}：{issued}
        </p>
      )}

      {previewOk && (
        <>
          <h2 className={styles.sectionTitle}>{t("guardsTitle")}</h2>
          <p className={styles.windowLine}>
            {preview.preview.guards_passed
              ? t("guardsAllGreen")
              : t("guardsBlocked")}
            {" · "}
            {t("score")}:{" "}
            {preview.preview.score === null ? "—" : String(preview.preview.score)}
          </p>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("colCode")}</th>
                <th>{t("colPassed")}</th>
                <th>{t("colDetail")}</th>
              </tr>
            </thead>
            <tbody>
              {preview.preview.guards.map((g) => (
                <tr key={g.code}>
                  <td className={styles.mono}>{g.code}</td>
                  <td>{g.passed ? t("verdictPass") : t("verdictFail")}</td>
                  <td className={styles.mono}>{g.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 className={styles.sectionTitle}>{t("conflictsTitle")}</h3>
          <p className={styles.windowLine}>{t("conflictsNote")}</p>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("colIndex")}</th>
                <th>{t("colLabel")}</th>
                <th>{t("colVerdict")}</th>
                <th>{t("colSource")}</th>
                <th>{t("colEvidence")}</th>
              </tr>
            </thead>
            <tbody>
              {preview.conflicts.map((row: ConflictCheckRow) => (
                <tr key={row.index}>
                  <td>{row.index}</td>
                  <td>{row.label}</td>
                  <td>
                    {row.verdict === "pass" && t("verdictPass")}
                    {row.verdict === "fail" && t("verdictFail")}
                    {row.verdict === "no-source" && (
                      <span className={styles.muted}>{t("verdictNoSource")}</span>
                    )}
                  </td>
                  <td className={styles.mono}>{row.source}</td>
                  <td>{row.evidence ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

"use client";

// Q368：段4 原子管理台 client 岛——候选行内裁决（批准/驳回/复活/风险覆盖/AI 补证）
// 与同义簇合并弹层（Q19 recommended_keeper_id 界面预填）。只调本模块 Server
// Action，禁直连 lib/api/裸 fetch；成功一律 router.refresh() 刷新 RSC。
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useEffect, useState } from "react";

import type { AtomCandidateView, AtomClusterMembers } from "./actions";
import {
  aiSupplementAtomEvidenceAction,
  approveAtomCandidateAction,
  getAtomClusterMembersAction,
  overrideAtomRiskAction,
  rejectAtomCandidateAction,
  resolveAtomClusterAction,
  reviveAtomCandidateAction,
} from "./actions";
import styles from "../admin.module.css";

type AtomRiskLevel = "critical" | "high" | "medium" | "low";
type PendingOp = null | "approve" | "reject" | "revive" | "override" | "ai";

function actionErrorLabel(
  t: (key: string) => string,
  result: { ok: false; status: string; detail: string | null },
): string {
  switch (result.status) {
    case "401":
      return t("errAuth");
    case "403":
      return t("errForbidden");
    case "404":
      return t("errNotFound");
    case "409":
      return result.detail ?? t("errConflict");
    case "422":
      return result.detail ?? t("errInvalid");
    case "502":
      return t("errUpstream");
    case "unconfigured":
      return t("errUnconfigured");
    case "missing_role":
      return t("errMissingRole");
    default:
      return t("errUnknown");
  }
}

export function AtomRowActions({ candidate }: { candidate: AtomCandidateView }) {
  const t = useTranslations("admin.atoms");
  const router = useRouter();
  const [op, setOp] = useState<PendingOp>(null);
  const [reason, setReason] = useState("");
  const [riskLevel, setRiskLevel] = useState<AtomRiskLevel>("medium");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clusterOpen, setClusterOpen] = useState(false);

  const canDecide =
    candidate.status === "pending_review" ||
    candidate.status === "pending_evidence";

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      const result = (await action()) as { ok: boolean } & {
        status?: string;
        detail?: string | null;
      };
      if (result.ok) {
        setOp(null);
        setReason("");
        router.refresh();
      } else {
        setError(
          actionErrorLabel(
            t,
            result as { ok: false; status: string; detail: string | null },
          ),
        );
      }
    } catch {
      setError(t("errUnknown"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className={styles.chipRow}>
        {canDecide && (
          <>
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={busy}
              onClick={() => run(() => approveAtomCandidateAction(candidate.candidate_id))}
            >
              {t("opApprove")}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={busy}
              onClick={() =>
                setOp(op === "reject" ? null : "reject")
              }
            >
              {t("opReject")}
            </button>
          </>
        )}
        {candidate.status === "rejected" && (
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={busy}
            onClick={() =>
              run(() => reviveAtomCandidateAction(candidate.candidate_id))
            }
          >
            {t("opRevive")}
          </button>
        )}
        {canDecide && (
          <>
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={busy}
              onClick={() =>
                setOp(op === "override" ? null : "override")
              }
            >
              {t("opOverride")}
            </button>
            {candidate.status === "pending_evidence" && (
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={busy}
                onClick={() => {
                  if (window.confirm(t("aiConfirm")))
                    run(() => aiSupplementAtomEvidenceAction(candidate.candidate_id));
                }}
              >
                {t("opAiEvidence")}
              </button>
            )}
          </>
        )}
        {candidate.cluster_id && (
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={busy}
            onClick={() => setClusterOpen(true)}
          >
            {t("opCluster")}
          </button>
        )}
      </div>

      {op === "reject" && (
        <div className={styles.windowLine}>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("rejectPlaceholder")}
          />
          <button
            type="button"
            className={styles.primaryButton}
            disabled={busy || !reason.trim()}
            onClick={() =>
              run(() => rejectAtomCandidateAction(candidate.candidate_id, reason))
            }
          >
            {t("opConfirm")}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={() => setOp(null)}>
            {t("opCancel")}
          </button>
        </div>
      )}
      {op === "override" && (
        <div className={styles.windowLine}>
          <select
            value={riskLevel}
            onChange={(e) => setRiskLevel(e.target.value as AtomRiskLevel)}
          >
            <option value="critical">critical</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("overridePlaceholder")}
          />
          <button
            type="button"
            className={styles.primaryButton}
            disabled={busy || !reason.trim()}
            onClick={() =>
              run(() => overrideAtomRiskAction(candidate.candidate_id, riskLevel, reason))
            }
          >
            {t("opConfirm")}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={() => setOp(null)}>
            {t("opCancel")}
          </button>
        </div>
      )}
      {error && <p className={styles.notice}>{error}</p>}

      {clusterOpen && candidate.cluster_id && (
        <ClusterDialog
          clusterId={candidate.cluster_id}
          onClose={() => setClusterOpen(false)}
        />
      )}
    </>
  );
}

function ClusterDialog({
  clusterId,
  onClose,
}: {
  clusterId: string;
  onClose: () => void;
}) {
  const t = useTranslations("admin.atoms");
  const router = useRouter();
  const [data, setData] = useState<AtomClusterMembers | null>(null);
  const [keeper, setKeeper] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const result = await getAtomClusterMembersAction(clusterId);
      if (cancelled) return;
      if ("members" in result && result.ok) {
        setData(result.members);
        // Q19：推荐值预填 keeper；无推荐则默认第一候选（可改）。
        setKeeper(
          result.members.recommended_keeper_id ??
            result.members.members[0]?.candidate_id ??
            null,
        );
      } else if ("status" in result && !result.ok) {
        setError(
          actionErrorLabel(
            t,
            result as { ok: false; status: string; detail: string | null },
          ),
        );
      } else {
        setError(t("errUnknown"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [clusterId, t]);

  async function resolve() {
    if (!keeper) return;
    setBusy(true);
    setError(null);
    try {
      const result = await resolveAtomClusterAction(clusterId, keeper);
      if (result.ok) {
        onClose();
        router.refresh();
      } else {
        setError(
          actionErrorLabel(
            t,
            result as { ok: false; status: string; detail: string | null },
          ),
        );
      }
    } catch {
      setError(t("errUnknown"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.windowLine}>
      <span className={styles.metaLine}>
        {t("clusterTitle")} {clusterId.slice(0, 8)}
        {data?.recommended_keeper_id && (
          <>
            {" · "}
            {t("recommendedKeeper")} {data.recommended_keeper_id.slice(0, 8)}
          </>
        )}
      </span>
      {data && (
        <>
          <label className={styles.filterField}>
            <span>{t("keeperLabel")}</span>
            <select
              value={keeper ?? ""}
              onChange={(e) => setKeeper(e.target.value || null)}
            >
              {data.members.map((m) => (
                <option key={m.candidate_id} value={m.candidate_id}>
                  {m.candidate_id.slice(0, 8)} · {m.content.slice(0, 24)}
                  {m.candidate_id === data.recommended_keeper_id ? " ★" : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={busy || !keeper}
            onClick={resolve}
          >
            {t("opResolve")}
          </button>
        </>
      )}
      <button type="button" className={styles.secondaryButton} onClick={onClose}>
        {t("opCancel")}
      </button>
      {error && <p className={styles.notice}>{error}</p>}
    </div>
  );
}

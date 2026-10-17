"use server";

// Q368：段4 原子管理台写口 Server Action——批准/驳回/复活/风险覆盖/AI 补证/簇合并。
// 后端写口 Q242 只认已验真 staff 令牌（门控关着也自行验真，无令牌 401）；角色按口
// 分流（approve/reject/risk-override/resolve 需 reviewer、ai-supplement 需
// operations）；AI 补证是花钱口（Q354 纪律）。本地缺身份/缺角色零请求，同 Q167。
import {
  ADMIN_ROLE_LIST,
  ApiError,
  CURRENT_ADMIN_ACTOR_ID,
  aiSupplementAtomEvidence,
  approveAtomCandidate,
  getAtomClusterMembers,
  overrideAtomRisk,
  rejectAtomCandidate,
  resolveAtomCluster,
  reviveAtomCandidate,
} from "@/lib/api";
import type {
  AtomCandidateView,
  AtomClusterMembers,
  AtomRiskLevel,
} from "@/lib/api";
export type {
  AtomCandidateView,
  AtomClusterMembers,
  AtomRiskLevel,
} from "@/lib/api";

const KNOWN_STATUSES = new Set([401, 403, 404, 409, 422, 502]);
const RISK_LEVELS = new Set(["critical", "high", "medium", "low"]);

export type AtomActionResult =
  | { ok: true; candidate?: AtomCandidateView }
  | {
      ok: false;
      status: 401 | 403 | 404 | 409 | 422 | 502;
      detail: string | null;
    }
  | { ok: false; status: "unconfigured" | "missing_role" | "unknown" };

function errorDetail(message: string): string | null {
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
    // 后端 409 有时以 violations 数组返回（GuardViolated）。
    if (Array.isArray(parsed.detail) && parsed.detail.length > 0)
      return parsed.detail.map(String).join("; ");
    return null;
  } catch {
    return null;
  }
}

function failure(err: unknown): AtomActionResult {
  if (err instanceof ApiError && KNOWN_STATUSES.has(err.status)) {
    return {
      ok: false,
      status: err.status as 401 | 403 | 404 | 409 | 422 | 502,
      detail: errorDetail(err.message),
    };
  }
  return { ok: false, status: "unknown" };
}

function guardOps(): AtomActionResult | null {
  if (!CURRENT_ADMIN_ACTOR_ID) return { ok: false, status: "unconfigured" };
  if (
    !ADMIN_ROLE_LIST.some(
      (role) => role === "operations" || role === "platform_admin",
    )
  )
    return { ok: false, status: "missing_role" };
  return null;
}

export async function approveAtomCandidateAction(
  candidateId: string,
): Promise<AtomActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = candidateId.trim();
  if (!trimmedId) return { ok: false, status: 422, detail: null };
  try {
    const candidate = await approveAtomCandidate(trimmedId);
    return { ok: true, candidate };
  } catch (err) {
    return failure(err);
  }
}

export async function rejectAtomCandidateAction(
  candidateId: string,
  reason: string,
): Promise<AtomActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = candidateId.trim();
  const trimmedReason = reason.trim();
  if (!trimmedId || !trimmedReason)
    return { ok: false, status: 422, detail: null };
  try {
    const candidate = await rejectAtomCandidate(trimmedId, trimmedReason);
    return { ok: true, candidate };
  } catch (err) {
    return failure(err);
  }
}

export async function reviveAtomCandidateAction(
  candidateId: string,
): Promise<AtomActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = candidateId.trim();
  if (!trimmedId) return { ok: false, status: 422, detail: null };
  try {
    const candidate = await reviveAtomCandidate(trimmedId);
    return { ok: true, candidate };
  } catch (err) {
    return failure(err);
  }
}

export async function overrideAtomRiskAction(
  candidateId: string,
  level: AtomRiskLevel,
  reason: string,
): Promise<AtomActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = candidateId.trim();
  const trimmedReason = reason.trim();
  if (!trimmedId || !RISK_LEVELS.has(level) || !trimmedReason)
    return { ok: false, status: 422, detail: null };
  try {
    const candidate = await overrideAtomRisk(trimmedId, level, trimmedReason);
    return { ok: true, candidate };
  } catch (err) {
    return failure(err);
  }
}

export async function aiSupplementAtomEvidenceAction(
  candidateId: string,
): Promise<AtomActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedId = candidateId.trim();
  if (!trimmedId) return { ok: false, status: 422, detail: null };
  try {
    const candidate = await aiSupplementAtomEvidence(trimmedId);
    return { ok: true, candidate };
  } catch (err) {
    return failure(err);
  }
}

export async function getAtomClusterMembersAction(
  clusterId: string,
): Promise<AtomActionResult | { ok: true; members: AtomClusterMembers }> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedClusterId = clusterId.trim();
  if (!trimmedClusterId) return { ok: false, status: 422, detail: null };
  try {
    const members = await getAtomClusterMembers(trimmedClusterId);
    return { ok: true, members };
  } catch (err) {
    return failure(err);
  }
}

export async function resolveAtomClusterAction(
  clusterId: string,
  keeperCandidateId: string | null,
): Promise<AtomActionResult> {
  const blocked = guardOps();
  if (blocked) return blocked;
  const trimmedClusterId = clusterId.trim();
  const keeperId = keeperCandidateId?.trim() || null;
  if (!trimmedClusterId) return { ok: false, status: 422, detail: null };
  try {
    await resolveAtomCluster(trimmedClusterId, keeperId);
    return { ok: true };
  } catch (err) {
    return failure(err);
  }
}

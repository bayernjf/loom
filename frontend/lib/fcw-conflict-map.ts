// Q249-c / D3.5 §3.3 甲：字段组合合理性校验——结果标签映射（纯前端只读）。
//
// 不新增任何检测逻辑、不臆造公式：仅把既有 Q21/Q24/Q26/Q22 检测输出映射到
// docs/09 L86 的 8 项判断结果并前端展示。8 项中无同源检测源的项一律标
// 【无源·原文未给出，待补】，不得补白（docs/02 C1.70/C1.88 纪律）。
// 映射口径（全部可溯源）：
//   1 合理组合(系统)    ← Q21 预筛通过 + 七 Guard 全绿
//   2 弱冲突·降权        ← Q21/Q22 评分分项体现（score_detail/score_incomplete）
//   3 强冲突·拒绝        ← Q26 冲突阻断 → Guard G4/G5（产品空间/租户一致性）失败
//   4 证据冲突·补证据    ← 【无源·原文未给出，待补】
//   5 合规冲突·阻断      ← Q26 合规阻断 → Guard G2/G6（清洗/法审）失败
//   6 过度营销·降级      ← 【无源·原文未给出，待补】（Q21 漏斗有预筛但独立检测项未给）
//   7 重复冲突·归一化    ← Q24 同平台+账号+发布位去重 → PWC dup_of / usage_count
//   8 范围错配·拒绝      ← 【无源·原文未给出，待补】

export type ConflictVerdict = "pass" | "fail" | "no-source";

export interface ConflictCheckRow {
  /** docs/09 L86 的 8 项判断结果序号（1–8）。 */
  index: number;
  /** 判断结果标签（原文字样）。 */
  label: string;
  /** pass=有源且未触发；fail=有源且已触发；no-source=无同源检测项（禁补白）。 */
  verdict: ConflictVerdict;
  /** 溯源：Q 编号 + 具体字段。 */
  source: string;
  /** 触发时的证据摘要（未触发/无源时为 null）。 */
  evidence: string | null;
}

export interface ConflictMapInput {
  guards: Array<{ code: string; passed: boolean; detail: string }>;
  pwc?: Record<string, unknown> | null;
  scoreIncomplete?: boolean;
}

function guardPassed(
  guards: Array<{ code: string; passed: boolean; detail: string }>,
  code: string,
): boolean | null {
  const row = guards.find((g) => g.code === code);
  return row === undefined ? null : row.passed;
}

export function mapConflictChecks(input: ConflictMapInput): ConflictCheckRow[] {
  const guards = input.guards;
  const guardsAllGreen = guards.length > 0 && guards.every((g) => g.passed);
  const pwc = input.pwc ?? {};

  const dupOf = pwc["dup_of"] ?? null;
  const usageCount =
    typeof pwc["usage_count"] === "number" ? (pwc["usage_count"] as number) : null;

  // Q24 去重：有 dup_of 或高复用计数 ⇒ 重复冲突已被归一化处理。
  const dupNormalized = dupOf != null || (usageCount !== null && usageCount > 0);

  // Q26 强冲突（PS/租户一致性 G4/G5）；合规冲突（清洗 G2 / 法审 G6）。
  const g4 = guardPassed(guards, "g4_product_space_consistent");
  const g5 = guardPassed(guards, "g5_tenant_consistent");
  const g2 = guardPassed(guards, "g2_compliance_clear");
  const g6 = guardPassed(guards, "g6_law_review");
  const strongConflict = g4 === false || g5 === false;
  const complianceConflict = g2 === false || g6 === false;

  const rows: ConflictCheckRow[] = [
    {
      index: 1,
      label: "合理组合(系统)",
      verdict: guardsAllGreen ? "pass" : "fail",
      source: "Q21 预筛 + 七 Guard（g1–g7）全绿",
      evidence: guardsAllGreen ? null : "存在 Guard 未放行，见下方对应行",
    },
    {
      index: 2,
      label: "弱冲突·降权",
      verdict: input.scoreIncomplete ? "fail" : "pass",
      source: "Q21/Q22 评分分项（score_detail / score_incomplete）",
      evidence: input.scoreIncomplete ? "评分存在未覆盖分项（score_incomplete=true）" : null,
    },
    {
      index: 3,
      label: "强冲突·拒绝",
      verdict: strongConflict ? "fail" : "pass",
      source: "Q26 冲突阻断 → Guard G4/G5（产品空间/租户一致性）",
      evidence: strongConflict ? "产品空间或租户一致性 Guard 未放行" : null,
    },
    {
      index: 4,
      label: "证据冲突·补证据",
      verdict: "no-source",
      source: "【无源·原文未给出，待补】",
      evidence: null,
    },
    {
      index: 5,
      label: "合规冲突·阻断",
      verdict: complianceConflict ? "fail" : "pass",
      source: "Q26 合规阻断 → Guard G2/G6（清洗/法审）",
      evidence: complianceConflict ? "清洗或法审 Guard 未放行" : null,
    },
    {
      index: 6,
      label: "过度营销·降级",
      verdict: "no-source",
      source: "【无源·原文未给出，待补】（Q21 漏斗有预筛但独立检测项未给）",
      evidence: null,
    },
    {
      index: 7,
      label: "重复冲突·归一化",
      verdict: dupNormalized ? "fail" : "pass",
      source: "Q24 同平台+账号+发布位去重 → PWC dup_of / usage_count",
      evidence: dupNormalized ? "PWC 存在去重来源（dup_of/高复用计数）" : null,
    },
    {
      index: 8,
      label: "范围错配·拒绝",
      verdict: "no-source",
      source: "【无源·原文未给出，待补】",
      evidence: null,
    },
  ];
  return rows;
}

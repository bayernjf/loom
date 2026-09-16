// Q107：录入单运营事件白名单（docs/13 §1.1）。仅运营角色执行的事件进管理端队列：
// - pending_confirm：ops_confirm（Q3 中置信运营确认）、to_cold_start（转冷启动类目创建）；
//   auto_confirm 是系统事件（Q1 direct_approve 机械实现），不外放；
// - pending_params：reject（params_completed 是客户事件，在客户详情页）；
// - category_creating：b2_approved/b2_parent_fallback/b2_rejected（Q5 运营三选一，均需 operations）。
// 不进白名单：wf01_*（6 Skill/系统）、submit/params_completed/quota_confirmed/resubmit（客户）、
// send_review/review_*/start_modeling/model_*/failed_*（触发方 docs/13 标【待补】，不外放）。
export const OPS_INTAKE_EVENTS = [
  "ops_confirm",
  "to_cold_start",
  "reject",
  "b2_approved",
  "b2_parent_fallback",
  "b2_rejected",
] as const;

export type OpsIntakeEvent = (typeof OPS_INTAKE_EVENTS)[number];

export function isOpsIntakeEvent(value: string): value is OpsIntakeEvent {
  return (OPS_INTAKE_EVENTS as readonly string[]).includes(value);
}

// 队列状态筛选白名单 = productIntake15 全量 15 态（docs/13 §1.1 / docs/05 §2.1 顺序）。
export const INTAKE_STATUS_FILTERS = [
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

export function isIntakeStatus(value: string): boolean {
  return (INTAKE_STATUS_FILTERS as readonly string[]).includes(value);
}

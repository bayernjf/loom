// Q106：客户页可触发的录入单事件白名单（docs/13 §1.1）。
// allowed-events 端点返回当前态全部事件，但其中：
// - wf01_*/auto_confirm 为 6 Skill 与系统事件（非客户操作）；
// - ops_confirm/to_cold_start/reject/b2_* 明确为运营执行（非客户）；
// - send_review/review_*/start_modeling/model_*/failed_* 的触发方 docs/13 标【待补】，不外放。
// 客户页只渲染与本白名单的交集；未列入的事件保持只读。
export const CUSTOMER_INTAKE_EVENTS = [
  "submit",
  "params_completed",
  "quota_confirmed",
  "resubmit",
] as const;

export type CustomerIntakeEvent = (typeof CUSTOMER_INTAKE_EVENTS)[number];

export function isCustomerIntakeEvent(event: string): event is CustomerIntakeEvent {
  return (CUSTOMER_INTAKE_EVENTS as readonly string[]).includes(event);
}

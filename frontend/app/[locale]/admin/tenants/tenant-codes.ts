// Q105：租户四档套餐 / 三态注册表状态（Q95 后端 PLANS + 生命周期派生状态）。
// 枚举码原样展示不翻译；付费档月额度【原文未给出，待补】，仅 trial 有数值。
export const TENANT_PLANS = ["trial", "basic", "pro", "enterprise"] as const;

export const TENANT_STATUSES = ["trial", "active", "paused"] as const;

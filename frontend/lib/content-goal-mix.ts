// Q44：内容目的配比健康度的纯类型（无服务端 env，可供 client 组件 type-only 引用）。
export type GoalMixHealth =
  | "no_data"
  | "unconfigured"
  | "below"
  | "within"
  | "above";

export interface ContentGoalMixRow {
  code: string;
  count: number;
  actual_ratio: number;
  ratio_min: number | null;
  ratio_max: number | null;
  health: GoalMixHealth;
}

export interface ContentGoalMixAlert {
  code: string;
  health: "below" | "above";
  actual_ratio: number;
  bound: number | null;
}

export interface ContentGoalMix {
  window: { date_from: string; date_to: string; days: number };
  tenant_id: string;
  product_space_id: string | null;
  total: number;
  unmapped_count: number;
  goals: ContentGoalMixRow[];
  alerts: ContentGoalMixAlert[];
}

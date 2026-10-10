"""§C2 标量配置项种子（迁移与测试单一事实源）。

只收"标量决策值"；自带 CRUD 表的 C2 项不收（行业阈值/信号权重/Q48 词库/
CP-LAW/contentGoals/发布位/PCP 模板/slotType 默认值/模型注册表/套餐/语言清单/
降级动作字典/17 池选项字典）。段 12/13 与 Agent 等尚未落地的段，C2 已决策的
数值也先登记（Q56 明确要求配置页面先行），出处逐条可溯。
"""

# (key, category, value_type, value, source_ref, validation)
CONFIG_SEEDS: list[tuple[str, str, str, object, str, dict | None]] = [
    # ---- 段2 C1 识别（Q1/Q3/Q4/Q6）----
    ("c1.cold_start_floor", "c1", "float", 0.6, "Q1", {"min": 0.0, "max": 1.0}),
    ("c1.mid_confidence_top_gap", "c1", "float", 0.1, "Q3", {"min": 0.0, "max": 1.0}),
    ("c1.ops_assist_sla_hours", "c1", "int", 72, "Q4", {"min": 1}),
    ("c1.layer3_coverage_floor", "c1", "float", 0.6, "Q6", {"min": 0.0, "max": 1.0}),
    # ---- 段3 字段池（Q9/Q10/Q12/Q15）----
    ("fieldpool.needs_detail_conf", "fieldpool", "float", 0.85, "Q9", {"min": 0.0, "max": 1.0}),
    ("fieldpool.dup_similarity_line", "fieldpool", "float", 0.9, "Q10", {"min": 0.0, "max": 1.0}),
    ("fieldpool.dim_min", "fieldpool", "int", 3, "PT-FP-PLAN", {"min": 1}),
    ("fieldpool.dim_max", "fieldpool", "int", 8, "PT-FP-PLAN", {"min": 1}),
    ("fieldpool.target_atom_min", "fieldpool", "int", 15, "Q15", {"min": 1}),
    ("fieldpool.target_atom_max", "fieldpool", "int", 30, "Q15", {"min": 1}),
    # ---- 段4 原子（Q14/Q16/Q18）----
    ("atom.batch_size_sensitive", "atom", "int", 20, "Q14", {"min": 1}),
    ("atom.batch_size_default", "atom", "int", 50, "Q14", {"min": 1}),
    ("atom.low_affinity_line", "atom", "float", 0.5, "Q16", {"min": 0.0, "max": 1.0}),
    ("atom.cluster_line", "atom", "float", 0.9, "Q86（借 Q10 0.9 同义线，原文未给）", {"min": 0.0, "max": 1.0}),
    ("atom.evidence_timeout_days", "atom", "int", 7, "Q18", {"min": 1}),
    # ---- 段5 PWC（Q21/Q22/Q22a/Q23/Q24/Q27/Q71，line 1451）----
    ("pwc.funnel_batch_limit", "pwc", "int", 50, "Q21", {"min": 1}),
    ("pwc.pool_target", "pwc", "int", 100, "line1451", {"min": 1}),
    ("pwc.pool_min", "pwc", "int", 70, "line1451", {"min": 0}),
    ("pwc.pool_critical", "pwc", "int", 50, "line1451", {"min": 0}),
    ("pwc.restock_cooldown_minutes", "pwc", "int", 5, "Q71", {"min": 0}),
    ("pwc.default_capacity", "pwc", "int", 100, "Q27", {"min": 1}),
    ("pwc.reasonableness_weight", "pwc", "float", 0.6, "Q22", {"min": 0.0, "max": 1.0}),
    ("pwc.diversity_weight", "pwc", "float", 0.4, "Q22", {"min": 0.0, "max": 1.0}),
    ("pwc.w_logic", "pwc", "float", 0.5, "Q22a", {"min": 0.0, "max": 1.0}),
    ("pwc.w_fit", "pwc", "float", 0.5, "Q22a", {"min": 0.0, "max": 1.0}),
    ("pwc.category_multiplier", "pwc", "float", 1.0, "Q22", {"min": 0.0}),
    ("pwc.dup_overlap_line", "pwc", "float", 0.8, "Q23", {"min": 0.0, "max": 1.0}),
    ("pwc.cooldown_window_days", "pwc", "int", 7, "Q24", {"min": 1}),
    ("pwc.cooldown_hits", "pwc", "int", 3, "Q24", {"min": 1}),
    ("pwc.cooldown_duration_days", "pwc", "int", 14, "Q24", {"min": 1}),
    # ---- 段6 PWS（Q28，line 2634 就绪门）----
    ("pws.min_approved_atoms", "pws", "int", 3, "line2634", {"min": 0}),
    ("pws.min_active_pwcs", "pws", "int", 1, "line2634", {"min": 0}),
    ("pws.ready_todo_due_days", "pws", "int", 7, "Q28", {"min": 1}),
    # ---- 段10 合规 / 横切 SLA（Q49）----
    ("ccr.law_review_due_hours", "sla", "int", 48, "Q49", {"min": 1}),
    ("sla.yellow_hours", "sla", "int", 24, "Q49", {"min": 1}),
    ("sla.red_hours", "sla", "int", 48, "Q49", {"min": 1}),
    # ---- 段11 FCW（Q54，仅排序）----
    ("fcw.w_pwc_skeleton", "fcw", "float", 0.4, "Q54", {"min": 0.0, "max": 1.0}),
    ("fcw.w_slot_fit", "fcw", "float", 0.3, "Q54", {"min": 0.0, "max": 1.0}),
    ("fcw.w_package_conf", "fcw", "float", 0.3, "Q54", {"min": 0.0, "max": 1.0}),
    # ---- 段12 内容（先登记，Q56/Q57）----
    ("content.ai_quality_threshold", "content", "float", 0.85, "Q57/line5196", {"min": 0.0, "max": 1.0}),
    ("content.regen_limit", "content", "int", 3, "Q56", {"min": 1}),
    # Q187/C4：discarded 终态成品的保留窗口（天）。Q124 只裁"作废回池"、未给清理
    # 口径（docs/20 §6.5 C4 明列"归档策略未定义"），180 天为工程甲案推荐值、原文
    # 未给出；甲案已经负责人 2026-09-25 追认（02 C1.134），调值走配置中心热更不改码。
    # 注：source_ref 只在播种时写入，存量库里那行仍显示旧文案"待追认"，属可见陈旧，
    # 不经数据订正不会自愈（本仓无种子回写机制，故在此留痕而非补迁移）。
    ("content.discard_retention_days", "content", "int", 180,
     "Q187/C4 甲案（原文未给出，2026-09-25 负责人追认）", {"min": 1}),
    # ---- 段13 反馈/KUP/校准（Q61/Q63/Q65）----
    ("hot.median_multiplier", "feedback", "float", 5.0, "Q61", {"min": 1.0}),
    ("hot.window_days", "feedback", "int", 90, "Q61", {"min": 1}),
    ("kup.min_samples", "feedback", "int", 30, "Q63", {"min": 1}),
    ("kup.min_lift_pct", "feedback", "float", 0.5, "Q63", {"min": 0.0}),
    ("kup.consecutive_periods", "feedback", "int", 2, "Q63", {"min": 1}),
    ("calibration.min_sample", "feedback", "int", 50, "Q65", {"min": 1}),
    # ---- 段8/9 平台（Q42/Q45，动态能力 V2，先登记）----
    ("pcp.recalc_step", "platform", "float", 0.05, "Q42", {"min": 0.0, "max": 1.0}),
    ("package.reuse_threshold", "platform", "int", 20, "Q45", {"min": 1}),
    # ---- Agent 三上限（line 2115/2119；注册表本体在 M12）----
    ("agent.review_copilot_max_turns", "agent", "int", 10, "line2119", {"min": 1}),
    ("agent.review_copilot_max_tokens", "agent", "int", 8000, "line2119", {"min": 1}),
    ("agent.pm_audit_max_turns", "agent", "int", 6, "line2119", {"min": 1}),
    ("agent.pm_audit_max_tokens", "agent", "int", 6000, "line2119", {"min": 1}),
    ("agent.support_max_turns", "agent", "int", 20, "line2119", {"min": 1}),
    ("agent.support_max_tokens", "agent", "int", 4000, "line2119", {"min": 1}),
    # ---- M12 统一审核工作台（Q70 一期③批量通过阈值；Q93 不挪用 fieldpool 命名空间）----
    ("review.batch_pass_confidence", "review", "float", 0.85, "Q70/Q9", {"min": 0.0, "max": 1.0}),
    # ---- M12 统一审核工作台（Q70②各审核类型挂通用 SLA；五型小时数 Q114 决策 V1 统一 72h 占位，业务方给数后热更）----
    ("review.sla_hours.pwc_combo", "review", "float", 72, "Q70②/Q114", {"min": 1}),
    ("review.sla_hours.field_plan", "review", "float", 72, "Q70②/Q114", {"min": 1}),
    ("review.sla_hours.c1_recognition", "review", "float", 72, "Q70②/Q114", {"min": 1}),
    ("review.sla_hours.atom_batch", "review", "float", 72, "Q70②/Q114", {"min": 1}),
    ("review.sla_hours.c7_layer4", "review", "float", 72, "Q70②/Q114", {"min": 1}),
    ("review.sla_hours.package_draft", "review", "float", 72, "Q328 WF-07 AI 选包", {"min": 1}),
    # ---- 段7/8 动态信号与 PCP 重算（Q42 单项单次幅度上限，Q259 起消费）----
    ("platform.recalc_step", "platform", "float", 0.05, "Q42", {"min": 0.001}),
    # Q294：PCP 每周重算**提醒**的周节奏（段8 PT-PCP-V1.5「动态信号每周更新触发重算」的
    # V2 第一切片）。原文只给「每周」二字，星期几/钟点/时区【原文未给出，待补】，默认值为
    # 工程甲案推荐（周一 02:00、UTC+8＝Asia/Shanghai），业务方定值后走配置中心热更，不改码。
    # 时区用**固定 UTC 偏移**而非 IANA 名：中国自 1991 年起无夏令时，固定偏移与具名时区
    # 恒等，且免引 tzdata 依赖（Q294 刻意不做：镜像 python:3.12-slim 无系统 tz 数据库）。
    ("platform.recalc_weekday", "platform", "int", 0, "Q294 甲案（原文未给出）", {"min": 0, "max": 6}),
    ("platform.recalc_hour", "platform", "int", 2, "Q294 甲案（原文未给出）", {"min": 0, "max": 23}),
    ("platform.recalc_tz_offset_hours", "platform", "int", 8, "Q294 甲案（原文未给出）", {"min": -12, "max": 14}),
    # 提醒待办的截止时长（天）：与 PWS 就绪提醒同型（pws.ready_todo_due_days=7），到期经
    # sweep 置 escalated（审计动作沿用默认 sla.todo_escalated，docs/10 §4）。
    ("platform.recalc_todo_due_days", "platform", "int", 7, "Q294 甲案（原文未给出）", {"min": 1}),
    # ---- 计费与订阅（D3.11-6 展示价，Q335；仅展示不扣费，改价走 config.update 审计）----
    # agency 档价格原文未给【待业务方回填】，不播种子（SEED 缺位即「待补」展示口径）。
    ("billing.price_monthly_usd.basic", "billing", "int", 999, "docs/09 D3.11-6", {"min": 0}),
    ("billing.price_monthly_usd.pro", "billing", "int", 2999, "docs/09 D3.11-6", {"min": 0}),
    ("billing.price_monthly_usd.enterprise", "billing", "int", 9999, "docs/09 D3.11-6", {"min": 0}),
]

SEED_BY_KEY = {row[0]: row for row in CONFIG_SEEDS}

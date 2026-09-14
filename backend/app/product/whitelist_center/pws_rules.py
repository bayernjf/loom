"""段6 PWS 冻结纯规则：pwsReadiness 5 项（line 2634）、版本号（Q31）、重冻三档（Q29）、同租户查重提示（Q33）。

数值依据：docs/01 §3 段6、docs/02 Q28-Q33、docs/13 §1.6。
"""

import hashlib

from app.core.config_center.knobs import knob


def ready_todo_due_days() -> int:
    # Q28：就绪门全绿出待办，7 天（配置项）未冻结升级提醒。
    return knob("pws.ready_todo_due_days")


def min_approved_atoms() -> int:
    # line 2634：≥3 个已批准原子。
    return knob("pws.min_approved_atoms")


def min_active_pwcs() -> int:
    # line 2634：≥1 个 active PWC。
    return knob("pws.min_active_pwcs")

# Q31：大版本递增 v1.0→v2.0。
VERSION_PREFIX = "v"
VERSION_MAJOR_STEP = 1.0

# BO-07 角色 id 原文未给英文码【实现补】，沿用既有 snake_case 命名。
ROLE_PWS_OWNER = "whitelist_owner"

# Q29 重冻三档。
REFREEZE_FORCED = "forced"
REFREEZE_SUGGESTED = "suggested"
REFREEZE_NONE = "none"

# Q29 触发原因码 → 档位。
# 强制：原子被合规暂停/废弃、词表更新命中快照内原子（Q51）、产品事实变更。
# 建议：普通增量（新增已批准原子/PWC）。
# 免：与快照资产无关的变更。
# 三档触发清单按 Q29 配置化，M10 配置中心前为代码常量。
REASON_REFREEZE_TIER = {
    "atom_compliance_suspend": REFREEZE_FORCED,
    "atom_deprecated": REFREEZE_FORCED,
    "wordlist_hit": REFREEZE_FORCED,
    "product_fact_change": REFREEZE_FORCED,
    "asset_increment": REFREEZE_SUGGESTED,
    "unrelated_change": REFREEZE_NONE,
}

# 快照状态（05 §2.5）：frozen 可消费（同刻仅 1 个 active）/ superseded 只读 / revoked 急停断消费。
PWS_FROZEN = "frozen"
PWS_SUPERSEDED = "superseded"
PWS_REVOKED = "revoked"


def all_green(checks: dict[str, bool]) -> bool:
    """pwsReadiness 5 项与门（line 2634，顺序固定）。"""
    return all(
        checks[key]
        for key in (
            "approved_field_pool",
            "enough_approved_atoms",
            "active_pwc",
            "no_unresolved_blocked_conflict",
            "no_pending_gate_fields",
        )
    )


def version_major(version: str) -> int:
    """提取 vN.0 的主版本号；非本形态记 0。"""
    if version.startswith(VERSION_PREFIX):
        head = version[len(VERSION_PREFIX) :].split(".", 1)[0]
        if head.isdigit():
            return int(head)
    return 0


def next_version(existing_versions: list[str]) -> str:
    """Q31：大版本递增，首个 v1.0。仅识别 vN.0 形态。"""
    major = max((version_major(raw) for raw in existing_versions), default=0)
    return f"{VERSION_PREFIX}{major + 1}.0"


def refreeze_tier(reason_code: str) -> str:
    """Q29：原因码 → 强制/建议/免；未知原因不放行（避免静默当增量）。"""
    if reason_code not in REASON_REFREEZE_TIER:
        raise ValueError(f"unknown refreeze reason: {reason_code}")
    return REASON_REFREEZE_TIER[reason_code]


def snapshot_fingerprint(atom_ids: list[str], pwc_ids: list[str]) -> str:
    """Q33 同租户查重指纹（排序后哈希，顺序无关）。仅提示，永不驳回。"""
    material = ",".join(sorted(atom_ids)) + "|" + ",".join(sorted(pwc_ids))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def same_tenant_duplicates(fingerprint: str, others: list[dict]) -> list[dict]:
    """Q33：仅在同租户内做指纹比对，返回命中版本清单（跨租户不调用本函数）。"""
    return [row for row in others if row["fingerprint"] == fingerprint]

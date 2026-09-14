"""C7 模板四层兜底的纯逻辑（line 708，Q6/Q68）。

Layer1 缓存命中（类目已有 approved 模板）
Layer2 相邻兄弟继承（同父叶子中 product_count 最大且模板 approved，Q6）
Layer3 从 G2 挑选（必填字段覆盖率 <60% 降级 Layer4，Q6；禁止发明新字段）
Layer4 大模型新生成 → g2_field_candidates（深度审核 Gate，段3 落）
"""

from app.core.config_center.knobs import knob


def layer3_coverage_floor() -> float:
    # Q6 拍板值经配置中心热更（02 §C2；M10c 接入）。
    return knob("c1.layer3_coverage_floor")


FORBIDDEN_FID = "-"  # Q68：fid:'-' 黑户字段禁止落库


class IllegalFid(Exception):
    """Q68：进入 field_list 的字段必须持合法 G2 fid，禁止 fid:'-'。"""


def validate_fids(fids: list[str]) -> None:
    for fid in fids:
        if not fid or fid == FORBIDDEN_FID:
            raise IllegalFid(f"illegal fid {fid!r}: every field must carry a real G2 fid")


def coverage(required_fids: list[str], available_fids: list[str]) -> float:
    """Layer3 必填字段覆盖率：G2 active 字段能满足多少必填位。"""
    if not required_fids:
        return 1.0
    available = set(available_fids)
    return round(sum(1 for fid in required_fids if fid in available) / len(required_fids), 4)


def pick_sibling(siblings: list[dict]) -> dict | None:
    """Q6：兄弟 = 同父叶子中 product_count 最大且 template 状态 approved 者。"""
    approved = [s for s in siblings if s.get("template_status") == "approved"]
    if not approved:
        return None
    return max(approved, key=lambda s: s.get("product_count", 0))

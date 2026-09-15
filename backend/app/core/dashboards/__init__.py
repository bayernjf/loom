"""M12 驾驶舱只读聚合（Q92）：Token 成本（Q67 单位经济）+ 人工审核工作量（Q70 SLA/积压）。

平台管理面实时聚合视图：不落表、不物化、无调度；append-only 源表
（skill_runs/skill_candidates/ops_todos）只读，不产生任何业务写入。
"""

from app.core.dashboards import service

__all__ = ["service"]

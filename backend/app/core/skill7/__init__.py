"""skill7 AI 候选通道（M10 切片 e，Q76）。

横切最小集：YAML 注册表驱动 + SkillRunLog 不可变日志 + 候选状态机
（ai_suggested→pending_review→confirmed/modified/rejected→applied/archived，
05 §2.3 / line 11314）。V1 只接外部投递（不建模型注册表/LLM 客户端，Q76-2），
WF-04 为首个试点（Q76-1）。
"""

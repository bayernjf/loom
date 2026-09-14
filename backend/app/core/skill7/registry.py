"""runtime/ YAML 注册表加载（14 §2.2 自研注册表驱动编排器最小集，15 §2）。

只加载与校验 Skill/WF 声明；顺序执行与人工 Gate 插槽的演绎在 service 层
按 WF 定义引用，复杂 DAG 二期（可迁 LangGraph）。路径可用环境变量
LOOM_RUNTIME_DIR 覆盖（测试指向临时目录）。
"""

import os
from functools import lru_cache
from pathlib import Path

import yaml

# app/core/skill7/registry.py → parents[4] = 仓库根（runtime/ 在根）。
DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parents[4] / "runtime"


class RegistryError(KeyError):
    """引用了未注册的 Skill / Workflow。"""


def runtime_dir() -> Path:
    return Path(os.environ.get("LOOM_RUNTIME_DIR", DEFAULT_RUNTIME_DIR))


def load_registry() -> tuple[dict[str, dict], dict[str, dict]]:
    skills: dict[str, dict] = {}
    for path in sorted((runtime_dir() / "skills").glob("*/skill.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        skills[data["skill_id"]] = data
    workflows: dict[str, dict] = {}
    for path in sorted((runtime_dir() / "workflows").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        workflows[data["wf_id"]] = data
    return skills, workflows


@lru_cache(maxsize=1)
def _cached() -> tuple[dict[str, dict], dict[str, dict]]:
    return load_registry()


def reload() -> None:
    _cached.cache_clear()


def all_skills() -> dict[str, dict]:
    return _cached()[0]


def all_workflows() -> dict[str, dict]:
    return _cached()[1]


def get_skill(skill_id: str) -> dict:
    try:
        return all_skills()[skill_id]
    except KeyError as exc:
        raise RegistryError(skill_id) from exc


def get_workflow(wf_id: str) -> dict:
    try:
        return all_workflows()[wf_id]
    except KeyError as exc:
        raise RegistryError(wf_id) from exc


def review_role(wf_id: str) -> str:
    """WF 定义中 skill7 通道 Gate 插槽的裁决角色。"""
    wf = get_workflow(wf_id)
    for gate in wf.get("gates", []):
        if gate.get("channel") == "skill7":
            return gate["role"]
    raise RegistryError(f"workflow {wf_id} has no skill7 gate slot")


def producer_step_for(wf_id: str, skill_id: str) -> dict | None:
    """WF 中该 Skill 步骤的完整声明（非候选产出者返回 None，Q79）。"""
    wf = get_workflow(wf_id)
    for step in wf.get("skills", []):
        if step.get("skill_id") == skill_id:
            return step if step.get("produces_candidates") else None
    return None


def candidate_target_for(wf_id: str, skill_id: str) -> str | None:
    """WF 中该 Skill 步骤声明的 candidate_target（Q78：投递校验按 WF 泛化）。"""
    step = producer_step_for(wf_id, skill_id)
    return step.get("candidate_target") if step else None

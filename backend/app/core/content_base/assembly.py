"""内容底座约束检查与确定性组装（M4 纯函数，无 IO）。

内存与持久后端共用：banned 命中检查 + 由请求确定性组装候选 body。
T-M4-02 阶段不调模型，真实模型产出在 T-M4-03 替换 ``assemble_body``。
"""

from __future__ import annotations

from typing import Any

from app.core.content_base.errors import ContentRequestInvalid
from app.core.content_base.types import ContentRequest


def iter_input_texts(value: Any) -> list[str]:
    """收集 inputs 中所有字符串，用于 banned 命中检查。"""
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            texts.extend(iter_input_texts(nested))
    elif isinstance(value, list):
        for nested in value:
            texts.extend(iter_input_texts(nested))
    return texts


def check_banned(request: ContentRequest) -> None:
    """命中任一 banned 词即 fail-closed 拒绝产出。"""
    for banned in request.constraints.banned:
        if not banned:
            continue
        for text in iter_input_texts(request.inputs):
            if banned in text:
                raise ContentRequestInvalid(f"content input hits banned word: {banned!r}")


def assemble_body(request: ContentRequest) -> dict[str, Any]:
    """由请求确定性组装候选 body（占位产出，T-M4-03 替换为模型产出）。"""
    title = request.inputs.get("title", request.product_id)
    return {
        "content_type": request.content_type,
        "channel": request.channel,
        "product_id": request.product_id,
        "title": title,
        "text": (
            f"[deterministic] {request.content_type} for {request.product_id} on {request.channel}"
        ),
        "inputs": request.inputs,
    }

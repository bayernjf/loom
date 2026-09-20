"""Q132/Q142 导出渲染纯函数单测：JSON envelope（含分页元数据）/ 双格式 payload。"""

import json

from app.core.exports import service
from app.core.exports.models import FORMAT_CSV, FORMAT_JSON


def test_render_json_empty_envelope():
    payload = service.render_json("ghost", None, [])
    assert payload == {
        "tenant_id": "ghost",
        "product_space_id": None,
        "count": 0,
        "total": 0,
        "limit": 0,
        "offset": 0,
        "has_more": False,
        "final_ids": [],
    }


def test_render_json_carries_ids_and_count():
    payload = service.render_json("t1", "ps-1", ["f1", "f2", "f3"])
    assert payload["count"] == 3
    assert payload["final_ids"] == ["f1", "f2", "f3"]
    assert payload["tenant_id"] == "t1"
    assert payload["product_space_id"] == "ps-1"
    # 未提供分页信息时按"本页即全部"退化。
    assert payload["total"] == 3
    assert payload["has_more"] is False


def test_render_json_page_metadata_flags_has_more():
    # Q142：总数 10、取首页 2 条 → has_more True；尾页取尽 → False。
    first = service.render_json(
        "t1", None, ["f1", "f2"], total=10, limit=2, offset=0
    )
    assert first["count"] == 2
    assert first["total"] == 10
    assert first["limit"] == 2
    assert first["offset"] == 0
    assert first["has_more"] is True

    last = service.render_json(
        "t1", None, ["f9", "f10"], total=10, limit=2, offset=8
    )
    assert last["has_more"] is False


def test_render_payload_csv_matches_render_csv():
    media, body = service.render_payload("t1", None, FORMAT_CSV, ["f1", "f2"])
    assert media == "text/csv; charset=utf-8"
    assert body == "final_id\nf1\nf2\n"


def test_render_payload_json_is_parseable_envelope():
    media, body = service.render_payload(
        "t1", "ps-9", FORMAT_JSON, ["f1"]
    )
    assert media == "application/json; charset=utf-8"
    parsed = json.loads(body)
    assert parsed["count"] == 1
    assert parsed["final_ids"] == ["f1"]
    assert parsed["product_space_id"] == "ps-9"


def test_render_payload_json_embeds_page_metadata():
    # Q142：page 透传进 JSON envelope；CSV 不消费 page。
    page = {"total": 5, "limit": 2, "offset": 0, "has_more": True}
    _media, body = service.render_payload(
        "t1", None, FORMAT_JSON, ["f1", "f2"], page=page
    )
    parsed = json.loads(body)
    assert parsed["total"] == 5
    assert parsed["limit"] == 2
    assert parsed["has_more"] is True


def test_file_name_for_uses_format_extension():
    assert service.file_name_for("t1", FORMAT_CSV) == "fcw-t1.csv"
    assert service.file_name_for("t1", FORMAT_JSON) == "fcw-t1.json"

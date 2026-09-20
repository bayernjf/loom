"""Q132 导出渲染纯函数单测：JSON envelope / 双格式 payload / 文件名。"""

import json

from app.core.exports import service
from app.core.exports.models import FORMAT_CSV, FORMAT_JSON


def test_render_json_empty_envelope():
    payload = service.render_json("ghost", None, [])
    assert payload == {
        "tenant_id": "ghost",
        "product_space_id": None,
        "count": 0,
        "final_ids": [],
    }


def test_render_json_carries_ids_and_count():
    payload = service.render_json("t1", "ps-1", ["f1", "f2", "f3"])
    assert payload["count"] == 3
    assert payload["final_ids"] == ["f1", "f2", "f3"]
    assert payload["tenant_id"] == "t1"
    assert payload["product_space_id"] == "ps-1"


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


def test_file_name_for_uses_format_extension():
    assert service.file_name_for("t1", FORMAT_CSV) == "fcw-t1.csv"
    assert service.file_name_for("t1", FORMAT_JSON) == "fcw-t1.json"

"""Q156 客户效果批量回填 CSV 服务端解析（销 Q136「服务端上传端点」挂账）。

纯函数、不碰库：把上传的 CSV 文本解析成 Q128 通道的 ``EffectRecordIn`` 列表，
整份文件挂同一个成品 ``content_id``（与 Q136 前端批量岛挂内容详情页一致）。

表头固定 9 列、按**表头名**定位（与前端 backfill-batch-island 完全同构）：

    platform_post_id, captured_at,
    plays, likes, comments, shares, inquiries, conversions, read_rate

纪律（与 service 层一致）：
- 指标列留空＝未采集，键缺席（绝不补 0）；计数须非负整数字面量，read_rate 0..1。
- captured_at 必须**带时区**（Z 或偏移）；服务端没有客户本地时区，naive/纯日期
  一律逐行报错（不臆造时区，守 Q128 tz-aware 铁律）。
- 一次性收集全部坏行（不在首个错误即停），交路由回 422 逐行回执；结构全合法才
  交由 Q128 整批 all-or-nothing 持久化（客户通道绝不产生孤儿）。
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from app.core.effects.models import METRIC_COUNTERS, METRIC_RATE_KEYS
from app.core.effects.schemas import EffectRecordIn

POST_ID_COLUMN = "platform_post_id"
CAPTURED_AT_COLUMN = "captured_at"
HEADER_COLUMNS = (
    POST_ID_COLUMN,
    CAPTURED_AT_COLUMN,
    *METRIC_COUNTERS,
    *METRIC_RATE_KEYS,
)

_INT_RE = re.compile(r"^\d+$")


class CsvValidationError(Exception):
    """CSV 结构/行级校验失败；errors 为逐行回执（header 错误 index=-1）。"""

    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        super().__init__(f"CSV validation failed with {len(errors)} error(s)")


@dataclass
class ParsedUpload:
    records: list[EffectRecordIn]
    rows: list[dict] = field(default_factory=list)


def _parse_counter(raw: str, *, column: str, errors: list[dict], index: int, line: int) -> int | None:
    value = raw.strip()
    if value == "":
        return None
    if not _INT_RE.match(value):
        errors.append(
            {
                "index": index,
                "line": line,
                "field": f"metrics.{column}",
                "message": "counter must be a non-negative integer",
            }
        )
        return None
    return int(value)


def _parse_rate(raw: str, *, errors: list[dict], index: int, line: int) -> float | None:
    value = raw.strip()
    if value == "":
        return None
    try:
        rate = float(value)
    except ValueError:
        rate = float("nan")
    if not 0 <= rate <= 1:  # NaN 比较恒 False，天然被拒
        errors.append(
            {
                "index": index,
                "line": line,
                "field": "metrics.read_rate",
                "message": "read_rate must be a number in [0, 1]",
            }
        )
        return None
    return rate


def _parse_captured_at(
    raw: str, *, errors: list[dict], index: int, line: int
) -> datetime | None:
    value = raw.strip()
    if not value:
        errors.append(
            {"index": index, "line": line, "field": "captured_at",
             "message": "captured_at is required"}
        )
        return None
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(
            {"index": index, "line": line, "field": "captured_at",
             "message": "captured_at must be an ISO 8601 timestamp"}
        )
        return None
    if dt.tzinfo is None:
        errors.append(
            {"index": index, "line": line, "field": "captured_at",
             "message": "captured_at must include a timezone (use Z or ±HH:MM)"}
        )
        return None
    return dt


def parse_backfill_csv(
    content_id: str, text: str, *, max_rows: int
) -> ParsedUpload:
    """解析整份回填 CSV；任何结构/行错误聚合抛 CsvValidationError。"""

    if not text or not text.strip():
        raise CsvValidationError(
            [{"index": -1, "line": 1, "field": "csv", "message": "CSV is empty"}]
        )
    text = text.removeprefix("\ufeff")  # 容忍 Excel 导出的 UTF-8 BOM

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise CsvValidationError(
            [{"index": -1, "line": 1, "field": "header", "message": "missing header row"}]
        ) from None

    header = [cell.strip() for cell in header]
    errors: list[dict] = []

    # 表头按名定位：必须 9 列齐全、无重复、无未知列。
    col_index: dict[str, int] = {}
    for pos, name in enumerate(header):
        if name in col_index:
            errors.append(
                {"index": -1, "line": 1, "field": "header",
                 "message": f"duplicate header column: {name}"}
            )
        elif name in HEADER_COLUMNS:
            col_index[name] = pos
        else:
            errors.append(
                {"index": -1, "line": 1, "field": "header",
                 "message": f"unknown header column: {name}"}
            )
    missing = [c for c in HEADER_COLUMNS if c not in col_index]
    if missing:
        errors.append(
            {"index": -1, "line": 1, "field": "header",
             "message": f"missing header columns: {','.join(missing)}"}
        )
    if errors:
        raise CsvValidationError(errors)

    def cell(row: list[str], column: str) -> str:
        pos = col_index[column]
        return row[pos] if pos < len(row) else ""

    records: list[EffectRecordIn] = []
    rows_meta: list[dict] = []
    data_index = -1
    for raw_row in reader:
        line = reader.line_num  # 物理行号（含空行/字段内换行，表头占第 1 行）
        if not any(cell.strip() for cell in raw_row):
            continue  # 跳过纯空行（不计数据行/不计上限）
        data_index += 1
        if data_index >= max_rows:
            raise CsvValidationError(
                [{"index": data_index, "line": line, "field": "rows",
                  "message": f"too many rows (limit {max_rows})"}]
            )
        if len(raw_row) != len(HEADER_COLUMNS):
            errors.append(
                {"index": data_index, "line": line, "field": "columns",
                 "message": f"expected {len(HEADER_COLUMNS)} columns, got {len(raw_row)}"}
            )
            continue

        post_id = cell(raw_row, POST_ID_COLUMN).strip()
        if not post_id:
            errors.append(
                {"index": data_index, "line": line, "field": "platform_post_id",
                 "message": "platform_post_id is required"}
            )
        captured_at = _parse_captured_at(
            cell(raw_row, CAPTURED_AT_COLUMN), errors=errors,
            index=data_index, line=line,
        )

        metrics: dict[str, object] = {}
        for column in METRIC_COUNTERS:
            parsed = _parse_counter(
                cell(raw_row, column), column=column,
                errors=errors, index=data_index, line=line,
            )
            if parsed is not None:
                metrics[column] = parsed
        for column in METRIC_RATE_KEYS:
            parsed = _parse_rate(
                cell(raw_row, column), errors=errors, index=data_index, line=line
            )
            if parsed is not None:
                metrics[column] = parsed

        if post_id and captured_at is not None:
            records.append(
                EffectRecordIn(
                    content_id=content_id,
                    platform_post_id=post_id,
                    captured_at=captured_at,
                    metrics=metrics or None,
                )
            )
            rows_meta.append(
                {
                    "index": data_index,
                    "line": line,
                    "platform_post_id": post_id,
                    "captured_at": captured_at.isoformat(),
                }
            )

    if data_index < 0:
        errors.append(
            {"index": -1, "line": 1, "field": "rows", "message": "no data rows"}
        )
    if errors:
        raise CsvValidationError(errors)
    return ParsedUpload(records=records, rows=rows_meta)

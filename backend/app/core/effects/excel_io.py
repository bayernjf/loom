"""Q160 客户效果批量回填 Excel（.xlsx）服务端解析。

与 Q156 CSV 上传同契约：整份工作簿挂同一个成品 ``content_id``，首行表头固定
9 列、按表头名定位，逐行校验、全合法才整批 all-or-nothing（绝不产生孤儿）。

载体差异全部收敛在本模块：openpyxl 以 ``read_only`` 流式读取**活动工作表**
（V1 只认第一个 sheet），把每个单元格值归一化成字符串后，交给
``csv_io.parse_backfill_table`` 做与 CSV 完全一致的严格校验。归一化规则：

- 空单元格 → ""（指标列留空＝未采集，绝不补 0）；
- 整数 → 整数字面量；浮点若为整数值（Excel 计数列常存成 100.0）→ 整数字面量，
  其余原样（read_rate 0.12 正常通过）；布尔 → true/false（计数列自然报错）；
- 日期/时间单元格 → ``isoformat()``：Excel 日期单元格**不带时区**，归一化后是
  naive ISO 串，会被 tz-aware 铁律逐行拒绝（不臆造客户时区）。要导入带时区的
  captured_at，请把该列存为文本并写 ``2026-09-20T12:00:00+08:00`` 这类 ISO 串。

列宽由表头固定为 9：数据行尾部的空单元格是 Excel 天然的"缺席"（不像 CSV 要显式
写逗号），故尾部空列补齐到 9 列而不是裁掉；仅当某行在第 10 列之后出现非空值才
按"多列"交核心报错。

只支持现代 ``.xlsx``（OOXML）；旧 ``.xls``（BIFF）/CSV/损坏文件在加载期即转成
:class:`CsvValidationError`（field="file"），由路由回 422。
"""

import datetime as dt
import io

from openpyxl import load_workbook

from app.core.effects.csv_io import (
    HEADER_COLUMNS,
    CsvValidationError,
    ParsedUpload,
    parse_backfill_table,
)

TABLE_WIDTH = len(HEADER_COLUMNS)


def _file_error(message: str) -> CsvValidationError:
    return CsvValidationError(
        [{"index": -1, "line": 1, "field": "file", "message": message}]
    )


def normalize_cell(value: object) -> str:
    """把一个 openpyxl 单元格值归一化为校验核心可消费的字符串。"""

    if value is None:
        return ""
    if isinstance(value, bool):
        # 必须在 int 之前判（bool 是 int 子类）；指标列遇 true/false 自然报错。
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # 计数列在 Excel 里常是数值型整数（100.0）：归一为整数字面量以通过 ^\d+$。
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, dt.datetime | dt.date):
        # naive datetime/date 的 isoformat 不带时区，随后被 tz-aware 铁律拒绝。
        return value.isoformat()
    return str(value)


def _effective_width(cells: list[str]) -> int:
    """最后一个非空单元格的位置 +1；整行空返回 0。"""

    for pos in range(len(cells) - 1, -1, -1):
        if cells[pos].strip():
            return pos + 1
    return 0


def _trim_trailing_empty(cells: list[str]) -> list[str]:
    """裁掉尾部空单元格（用于表头按名定位）；保留中间空列以触发缺失/重复校验。"""

    return cells[:_effective_width(cells)]


def parse_backfill_excel(
    content_id: str, payload: bytes, *, max_rows: int
) -> ParsedUpload:
    """解析 .xlsx 字节；加载失败/结构或行错误统一抛 :class:`CsvValidationError`。"""

    if not payload:
        raise _file_error("workbook is empty")
    try:
        workbook = load_workbook(
            io.BytesIO(payload), read_only=True, data_only=True
        )
    except Exception as exc:  # openpyxl 对非 xlsx/损坏文件抛 InvalidFileException 等
        raise _file_error(
            "invalid .xlsx workbook (only modern .xlsx is supported)"
        ) from exc

    worksheet = workbook.active
    if worksheet is None:
        raise _file_error("workbook has no active worksheet")

    row_iter = worksheet.iter_rows(values_only=True)
    try:
        first = next(row_iter)
    except StopIteration:
        raise _file_error("workbook is empty") from None

    header = _trim_trailing_empty([normalize_cell(v) for v in first])
    if not any(cell.strip() for cell in header):
        raise CsvValidationError(
            [{"index": -1, "line": 1, "field": "header", "message": "missing header row"}]
        )
    header = [cell.strip() for cell in header]

    def _rows():
        # first 占第 1 行（表头），其后从第 2 行起，物理行号与 CSV line 语义一致。
        for line, raw in enumerate(row_iter, start=2):
            cells = [normalize_cell(v) for v in raw]
            width = _effective_width(cells)
            if width > TABLE_WIDTH:
                # 第 10 列之后出现非空值：保留真实宽度，交核心报 expected 9 got N。
                yield line, cells[:width]
            else:
                # 尾部空单元格＝缺席：补齐到固定 9 列（含整行空，交由核心跳过）。
                row = cells[:TABLE_WIDTH]
                if len(row) < TABLE_WIDTH:
                    row = row + [""] * (TABLE_WIDTH - len(row))
                yield line, row

    try:
        return parse_backfill_table(
            content_id, header, _rows(), max_rows=max_rows
        )
    finally:
        workbook.close()

"值转换：把钉钉表格/多维表里五花八门的单元格，转成能入库的类型。"

from __future__ import annotations

import datetime as dt
import json
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

EMPTY_TOKENS = {
    "",
    "-",
    "--",
    "—",
    "——",
    "/",
    "\\",
    "无",
    "暂无",
    "空",
    "n/a",
    "na",
    "null",
    "none",
    "nil",
    "nan",
}

_CURRENCY = "¥￥$₩€£元人民币"
_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_AMBIGUOUS_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

_TRUE_TOKENS = {"1", "y", "yes", "true", "t", "是", "对", "有", "√", "✓", "已"}
_FALSE_TOKENS = {"0", "n", "no", "false", "f", "否", "不", "没", "×", "x", "✗"}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y%m%d",
    "%y-%m-%d",
    "%y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
)

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y%m%d%H%M%S",
)

_EXCEL_EPOCH = dt.datetime(1899, 12, 30)

_EXCEL_MIN = 20000


class ConvertError(ValueError):
    """这一格转不成目标类型。"""


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in EMPTY_TOKENS
    return False


_INVISIBLE_CHARS = "\u200b\u200c\u200d\u2060\ufeff" "\u200e\u200f\u202a\u202b\u202c\u202d\u202e"

_INNER_NEWLINE = re.compile(r"\r\n?|\n")


def clean_text(value: Any) -> str | None:
    if is_empty(value):
        return None
    if isinstance(value, str):
        text = value.translate({ord(ch): None for ch in _INVISIBLE_CHARS})
        return _INNER_NEWLINE.sub(" ", text).strip()
    return str(value)


def to_text(value: Any, *, fullwidth_to_half: bool = False, max_length: int | None = None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    if fullwidth_to_half:
        text = fullwidth_to_half_width(text)
    if max_length is not None and len(text) > max_length:
        text = text[:max_length]
    return text


def fullwidth_to_half_width(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def to_number(value: Any) -> float | None:
    """数字。会剔掉千分位、货币符号、空格、百分号。"""
    if is_empty(value):
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float | Decimal):
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ConvertError(f"数值超出范围：{value!r}") from exc
        if not math.isfinite(number):
            raise ConvertError(f"数值超出范围：{value!r}")
        return number

    text = str(value).strip()

    text = fullwidth_to_half_width(text)
    text = text.replace(",", "").replace("，", "").replace(" ", "").replace("\u00a0", "")
    for sym in _CURRENCY:
        text = text.replace(sym, "")
    if not text:
        return None
    if not _NUM_RE.match(text):
        raise ConvertError(f"不是数字：{value!r}")
    number = float(text)
    if not math.isfinite(number):
        raise ConvertError(f"数值超出范围：{value!r}")
    return number


def to_int(value: Any) -> int | None:
    number = to_number(value)
    if number is None:
        return None
    if abs(number - round(number)) > 1e-9:
        raise ConvertError(f"不是整数：{value!r}")
    return int(round(number))


def to_decimal(value: Any) -> Decimal | None:
    number = to_number(value)
    if number is None:
        return None
    try:
        return Decimal(str(number))
    except InvalidOperation as exc:  # pragma: no cover — to_number 已经筛过一遍
        raise ConvertError(f"不是金额：{value!r}") from exc


def to_unit_number(value: Any) -> float | None:
    "`5 个` / `12 台` / `1,234.56 元` → 数字。不是这个形状就返回 None。"
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    for unit in _UNIT_WORDS:
        if not text.endswith(unit):
            continue
        head = text[: -len(unit)].strip()
        if not head:
            continue
        return to_number(head)
    return None


_UNIT_WORDS: tuple[str, ...] = (
    "个",
    "只",
    "件",
    "台",
    "套",
    "箱",
    "包",
    "瓶",
    "袋",
    "张",
    "条",
    "支",
    "块",
    "枚",
    "片",
    "颗",
    "株",
    "头",
    "尾",
    "次",
    "人次",
    "单",
    "笔",
    "户",
    "人",
    "米",
    "厘米",
    "毫米",
    "公里",
    "千米",
    "克",
    "千克",
    "公斤",
    "斤",
    "吨",
    "毫升",
    "升",
    "瓦",
    "千瓦",
    "度",
    "元",
    "美元",
    "日元",
    "韩元",
    "卢布",
)


def to_percent(value: Any) -> float | None:
    """百分比：``12.5%`` → 0.125，``12.5`` 原样返回。"""
    if is_empty(value):
        return None
    text = str(value).strip()
    if text.endswith("%") or text.endswith("％"):
        number = to_number(text[:-1])
        return None if number is None else number / 100
    return to_number(value)


def _parse_datetime_text(text: str) -> dt.datetime | None:
    for fmt in _DATETIME_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def to_datetime(value: Any) -> dt.datetime | None:
    if is_empty(value):
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            serial = float(value)
        except OverflowError as exc:
            raise ConvertError(f"日期数值超出范围：{value!r}") from exc
        if not math.isfinite(serial):
            raise ConvertError(f"日期数值超出范围：{value!r}")
        try:
            if serial >= 1_000_000_000_000:
                return dt.datetime.fromtimestamp(serial / 1000)
            if serial >= 1_000_000_000:
                return dt.datetime.fromtimestamp(serial)
        except (OverflowError, OSError, ValueError) as exc:
            raise ConvertError(f"时间戳超出范围：{value!r}") from exc
        if serial >= _EXCEL_MIN:
            try:
                return _EXCEL_EPOCH + dt.timedelta(days=serial)
            except OverflowError as exc:
                raise ConvertError(f"日期序列号超出范围：{value!r}") from exc
        raise ConvertError(f"不是日期：{value!r}")

    text = str(value).strip()
    slash_date = _AMBIGUOUS_SLASH_DATE.fullmatch(text)
    if (
        slash_date
        and all(1 <= int(part) <= 12 for part in slash_date.groups()[:2])
        and slash_date.group(1) != slash_date.group(2)
    ):
        raise ConvertError(f"日期的月/日顺序不明确：{value!r}")
    text = text.replace("/", "-") if text.count("-") >= 2 else text
    parsed = _parse_datetime_text(text)
    if parsed is None:
        parsed = _parse_datetime_text(str(value).strip())
        if parsed is None:
            raise ConvertError(f"认不出的日期格式：{value!r}")
    return parsed


def to_date(value: Any) -> dt.date | None:
    parsed = to_datetime(value)
    return parsed.date() if parsed else None


def to_bool(value: Any) -> bool | None:
    if is_empty(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        if value == 1:
            return True
        if value == 0:
            return False
        raise ConvertError(f"不是是否值：{value!r}")

    text = str(value).strip().lower()
    if text in _TRUE_TOKENS:
        return True
    if text in _FALSE_TOKENS:
        return False
    raise ConvertError(f"不是是否值：{value!r}")


def to_json_text(value: Any) -> str | None:
    if is_empty(value):
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


CONVERTERS = {
    "text": to_text,
    "int": to_int,
    "float": to_number,
    "decimal": to_decimal,
    "date": to_date,
    "datetime": to_datetime,
    "bool": to_bool,
    "json": to_json_text,
}


def convert(
    value: Any,
    col_type: str,
    *,
    transform: str | None = None,
    max_length: int | None = None,
) -> Any:
    """按列配置把一格转成能入库的值。转不了抛 ConvertError。"""
    if transform == "percent":
        return to_percent(value)

    if transform == "json_stringify":
        return to_json_text(value)

    if col_type == "text":
        return to_text(
            value,
            fullwidth_to_half=(transform == "fullwidth_to_half"),
            max_length=max_length,
        )

    if transform == "number":
        value = to_number(value)
    elif transform == "strip_unit":
        value = to_unit_number(value)
    elif transform == "date":
        return to_date(value)

    converter = CONVERTERS.get(col_type)
    if converter is None:
        raise ConvertError(f"不认识的列类型：{col_type}")

    result = converter(value)

    if isinstance(result, str):
        if transform == "trim":
            result = result.strip()
        elif transform == "upper":
            result = result.upper()
        elif transform == "lower":
            result = result.lower()

    return result


def _looks_like_int(samples: list[Any]) -> bool:
    for value in samples:
        number = to_number(value)
        if number is None:
            continue
        if abs(number - round(number)) > 1e-9:
            return False
    return True


def looks_like_identifier(values: list[Any]) -> bool:
    "整列都是数字串、而且**有值带前导零** → 这是编码/工号/邮编，不是数值。"
    if not values:
        return False
    texts: list[str] = []
    for value in values:
        if not isinstance(value, str):
            return False
        texts.append(value.strip())
    if not all(text.isdigit() for text in texts if text):
        return False
    return any(text.startswith("0") and len(text) > 1 for text in texts)


def infer_type(samples: list[Any]) -> str:
    """从若干样例值猜列类型。猜错了用户在向导里能改，所以宁可保守。"""
    values = [v for v in samples if not is_empty(v)]
    if not values:
        return "text"

    if looks_like_identifier(values):
        return "text"

    probes = {
        "bool": to_bool,
        "int": to_int,
        "float": to_number,
        "datetime": to_datetime,
    }
    hits = {name: 0 for name in probes}
    for value in values:
        for name, func in probes.items():
            try:
                func(value)
                hits[name] += 1
            except (ConvertError, ValueError):
                pass

    total = len(values)
    if hits["datetime"] == total:
        for value in values:
            try:
                moment = to_datetime(value)
            except (ConvertError, ValueError):
                continue
            if moment and (moment.hour or moment.minute or moment.second):
                return "datetime"
        return "date"
    if hits["bool"] == total:
        has_text_token = any(
            isinstance(v, str) and v.strip().lower() in _TRUE_TOKENS | _FALSE_TOKENS for v in values
        )
        if has_text_token:
            return "bool"
    if hits["float"] == total:
        return "float"
    return "text"


def format_temporal(value: Any) -> Any:
    "把日期/时间统一成给人看的样子。"
    if isinstance(value, dt.datetime):
        if value.hour or value.minute or value.second:
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    return value


_SERIAL_MIN = 20000
_SERIAL_MAX = 60000


def looks_like_date_serial(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and _SERIAL_MIN <= float(value) <= _SERIAL_MAX
    )


def _parses_as_number(text: str) -> bool:
    "能不能当数字看。**失败就是 False，不抛异常。**"
    try:
        return to_number(text) is not None
    except (ConvertError, ValueError, TypeError):
        return False


def _parses_as_unit_number(text: str) -> bool:
    "是不是「数字 + 白名单单位」。**失败就是 False，不抛** —— 理由同上。"
    try:
        return to_unit_number(text) is not None
    except (ConvertError, ValueError, TypeError):
        return False


def infer_transform(samples: list[Any]) -> str | None:
    """带百分号、带千分位这类需要额外转换的，顺手推出来。"""
    texts = [str(v).strip() for v in samples if not is_empty(v)]

    if any(t.endswith(("%", "％")) for t in texts):
        return "percent"
    if any("," in t for t in texts) and all(
        _parses_as_number(t) for t in texts if any(ch.isdigit() for ch in t)
    ):
        return "number"

    if texts and all(_parses_as_unit_number(t) for t in texts):
        return "strip_unit"
    return None


def column_profile(samples: list[Any], *, name: str = "") -> dict[str, Any]:
    "给一列做个体检：有多少空、像什么类型、值有什么特征。"
    values = [v for v in samples if not is_empty(v)]
    total = len(samples)
    non_empty = len(values)

    looks_like_media = bool(values) and all(
        isinstance(v, str)
        and (v.startswith("[") and v.endswith("]") or "图片" in v or "附件" in v or v.startswith("http"))
        for v in values
    )

    profile: dict[str, Any] = {
        "name": name,
        "total": total,
        "non_empty": non_empty,
        "empty": total - non_empty,
        "empty_ratio": round((total - non_empty) / total, 3) if total else 1.0,
        "inferred_type": infer_type(samples),
        "suggested_transform": infer_transform(samples),
        "looks_like_media": looks_like_media,
        "is_empty_column": non_empty == 0,
    }
    profile["suggestion"] = "drop" if profile["is_empty_column"] or profile["empty_ratio"] >= 0.9 else "keep"
    return profile

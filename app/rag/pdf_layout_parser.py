from __future__ import annotations

import logging
import math
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HEADING_MARKER_RE = re.compile(r"^\[\[PDF_HEADING:([1-6])\]\]\s*(.+)$")
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:第?\s*\d+\s*页|\d+\s*/\s*\d+|\d+[.]?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*•●▪◦■○]|\d+[)）]|[a-zA-Z][)）])\s*")
_CODE_RE = re.compile(
    r"(?:[={}<>]|https?://|\b(?:while|return|for|if|else|public|private|protected|"
    r"class|def|import|new|void|static)\b)",
    re.IGNORECASE,
)
_SENTENCE_ENDINGS = ("。", "！", "？", "；", ".", "!", "?", ";")
_BOLD_NAMES = ("bold", "semibold", "demibold", "heavy", "black", "w6", "w7", "w8", "w9")


@dataclass
class _LayoutLine:
    page: int
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    fontname: str
    page_width: float
    page_height: float
    kind: str = "text"


def _clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(char for char in text if char >= " " or char == "\t")
    return re.sub(r"\s+", " ", text).strip()


def _join_words(words: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    previous: dict[str, Any] | None = None
    for word in sorted(words, key=lambda item: float(item.get("x0") or 0)):
        text = _clean_text(word.get("text"))
        if not text:
            continue
        if previous is not None and parts:
            gap = float(word.get("x0") or 0) - float(previous.get("x1") or 0)
            prev_text = parts[-1]
            both_ascii_words = (
                prev_text[-1:].isascii()
                and prev_text[-1:].isalnum()
                and text[:1].isascii()
                and text[:1].isalnum()
            )
            size = min(float(previous.get("size") or 10), float(word.get("size") or 10))
            if both_ascii_words or gap > max(3.0, size * 0.45):
                parts.append(" ")
        parts.append(text)
        previous = word
    return "".join(parts).strip()


def _group_words(page_number: int, page: Any, words: list[dict[str, Any]]) -> list[_LayoutLine]:
    if not words:
        return []
    ordered = sorted(words, key=lambda item: (float(item.get("top") or 0), float(item.get("x0") or 0)))
    groups: list[list[dict[str, Any]]] = []
    for word in ordered:
        top = float(word.get("top") or 0)
        size = float(word.get("size") or 10)
        if groups:
            group_top = statistics.median(float(item.get("top") or 0) for item in groups[-1])
            group_size = max(float(item.get("size") or 10) for item in groups[-1])
            if abs(top - group_top) <= max(3.0, size * 0.3, group_size * 0.3):
                groups[-1].append(word)
                continue
        groups.append([word])

    lines: list[_LayoutLine] = []
    for group in groups:
        text = _join_words(group)
        if not text:
            continue
        lines.append(
            _LayoutLine(
                page=page_number,
                text=text,
                x0=min(float(item.get("x0") or 0) for item in group),
                x1=max(float(item.get("x1") or 0) for item in group),
                top=min(float(item.get("top") or 0) for item in group),
                bottom=max(float(item.get("bottom") or 0) for item in group),
                size=max(float(item.get("size") or 10) for item in group),
                fontname=" ".join(sorted({str(item.get("fontname") or "") for item in group})),
                page_width=float(page.width),
                page_height=float(page.height),
            )
        )
    return lines


def _table_to_markdown(rows: list[list[Any]]) -> str:
    cleaned = [[_clean_text(cell).replace("|", "\\|") for cell in row] for row in rows]
    width = max((len(row) for row in cleaned), default=0)
    if width < 2:
        return ""
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header = cleaned[0]
    body = cleaned[1:]
    return "\n".join(
        [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
            *("| " + " | ".join(row) + " |" for row in body),
        ]
    )


def _extract_tables(page_number: int, page: Any) -> tuple[list[_LayoutLine], list[tuple[float, float, float, float]]]:
    lines: list[_LayoutLine] = []
    boxes: list[tuple[float, float, float, float]] = []
    try:
        tables = page.find_tables()
    except Exception:
        return lines, boxes
    for table in tables:
        rows = table.extract() or []
        column_count = max((len(row) for row in rows), default=0)
        non_empty = sum(bool(_clean_text(cell)) for row in rows for cell in row)
        x0, top, x1, bottom = (float(value) for value in table.bbox)
        area_ratio = ((x1 - x0) * (bottom - top)) / max(float(page.width * page.height), 1.0)
        if len(rows) < 2 or column_count < 2 or non_empty < 4 or area_ratio > 0.8:
            continue
        text = _table_to_markdown(rows)
        if not text:
            continue
        boxes.append((x0, top, x1, bottom))
        lines.append(
            _LayoutLine(
                page=page_number,
                text=text,
                x0=x0,
                x1=x1,
                top=top,
                bottom=bottom,
                size=0,
                fontname="",
                page_width=float(page.width),
                page_height=float(page.height),
                kind="table",
            )
        )
    return lines, boxes


def _inside_table(word: dict[str, Any], boxes: list[tuple[float, float, float, float]]) -> bool:
    center_x = (float(word.get("x0") or 0) + float(word.get("x1") or 0)) / 2
    center_y = (float(word.get("top") or 0) + float(word.get("bottom") or 0)) / 2
    return any(x0 <= center_x <= x1 and top <= center_y <= bottom for x0, top, x1, bottom in boxes)


def _body_font_size(lines: list[_LayoutLine]) -> float:
    weighted: list[float] = []
    for line in lines:
        if line.kind != "text" or not line.text:
            continue
        weighted.extend([line.size] * min(max(len(line.text), 1), 80))
    return float(statistics.median(weighted)) if weighted else 11.0


def _repeated_margin_lines(lines: list[_LayoutLine], page_count: int) -> set[tuple[int, str]]:
    occurrences: dict[str, set[int]] = defaultdict(set)
    candidates: dict[tuple[int, str], str] = {}
    for line in lines:
        if line.kind != "text":
            continue
        in_margin = line.top <= line.page_height * 0.08 or line.bottom >= line.page_height * 0.92
        if not in_margin or len(line.text) > 120:
            continue
        normalized = re.sub(r"\d+", "#", _clean_text(line.text)).casefold()
        if not normalized:
            continue
        occurrences[normalized].add(line.page)
        candidates[(line.page, line.text)] = normalized
    threshold = max(2, math.ceil(page_count * 0.5))
    repeated = {text for text, pages in occurrences.items() if len(pages) >= threshold}
    return {key for key, normalized in candidates.items() if normalized in repeated}


def _is_layout_heading(line: _LayoutLine, body_size: float) -> bool:
    text = line.text.strip()
    if (
        line.kind != "text"
        or not text
        or len(text) > 64
        or _PAGE_NUMBER_RE.match(text)
        or _LIST_RE.match(text)
        or _CODE_RE.search(text)
        or text.endswith(_SENTENCE_ENDINGS)
    ):
        return False
    if len(text) > 36 and any(mark in text for mark in (":", "：", ",", "，", ";", "；")):
        return False
    if len(text) > 48 and line.size < body_size * 1.5:
        return False
    font = line.fontname.casefold()
    bold = any(marker in font for marker in _BOLD_NAMES)
    return line.size >= body_size * 1.18 or (bold and line.size >= body_size * 1.08)


def _heading_levels(lines: list[_LayoutLine], body_size: float) -> dict[float, int]:
    sizes = sorted(
        {round(line.size, 1) for line in lines if _is_layout_heading(line, body_size)},
        reverse=True,
    )
    return {size: min(index + 1, 6) for index, size in enumerate(sizes)}


def _render_layout_text(lines: list[_LayoutLine], body_size: float, page_count: int) -> str:
    ignored = _repeated_margin_lines(lines, page_count)
    levels = _heading_levels(lines, body_size)
    page_lines: dict[int, list[_LayoutLine]] = defaultdict(list)
    for line in lines:
        if (line.page, line.text) not in ignored and not _PAGE_NUMBER_RE.match(line.text):
            page_lines[line.page].append(line)

    output: list[str] = []
    for page_number in range(1, page_count + 1):
        previous: _LayoutLine | None = None
        for line in sorted(page_lines.get(page_number, []), key=lambda item: (item.top, item.x0)):
            if line.kind == "table":
                if output and output[-1] != "":
                    output.append("")
                output.extend(line.text.splitlines())
                output.append("")
                previous = None
                continue
            if _is_layout_heading(line, body_size):
                if output and output[-1] != "":
                    output.append("")
                level = levels.get(round(line.size, 1), 6)
                output.extend([f"[[PDF_HEADING:{level}]] {line.text}", ""])
                previous = None
                continue

            if previous is not None:
                gap = line.top - previous.bottom
                indent = line.x0 - previous.x0
                starts_list = bool(_LIST_RE.match(line.text))
                previous_list = bool(_LIST_RE.match(previous.text))
                paragraph_break = (
                    gap > body_size * 0.9
                    or (indent > body_size * 1.2 and previous.text.endswith(_SENTENCE_ENDINGS))
                    or (starts_list and not previous_list)
                )
                if paragraph_break and output and output[-1] != "":
                    output.append("")
            output.append(line.text)
            previous = line
        if output and output[-1] != "":
            output.append("")

    compact: list[str] = []
    for line in output:
        if line or (compact and compact[-1] != ""):
            compact.append(line)
    return "\n".join(compact).strip()


def extract_pdf_text(path: str | Path) -> str:
    """Extract layout-aware PDF text with explicit heading markers."""
    import pdfplumber

    logger = logging.getLogger("pdfminer")
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        all_lines: list[_LayoutLine] = []
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            for page_number, page in enumerate(pdf.pages, 1):
                table_lines, table_boxes = _extract_tables(page_number, page)
                words = page.extract_words(
                    x_tolerance=2,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=False,
                    extra_attrs=["fontname", "size"],
                )
                words = [word for word in words if not _inside_table(word, table_boxes)]
                all_lines.extend(_group_words(page_number, page, words))
                all_lines.extend(table_lines)
        body_size = _body_font_size(all_lines)
        return _render_layout_text(all_lines, body_size, page_count)
    finally:
        logger.setLevel(previous_level)

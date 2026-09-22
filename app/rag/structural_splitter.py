from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.pdf_layout_parser import HEADING_MARKER_RE


_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:第?\s*\d+\s*页|\d+\s*/\s*\d+|\d+[.]?)\s*$", re.IGNORECASE
)
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_DECIMAL_HEADING_RE = re.compile(r"^(\d+\.(?:\d+\.?)*)(?:\s*)(.{1,48})$")
_CHINESE_HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百零〇\d]+[章节部分篇]|"
    r"[一二三四五六七八九十百零〇]+[、.．])\s*(.{1,60})$"
)
_LIST_PREFIX_RE = re.compile(
    r"^\s*(?:[-*•●▪◦]|\d+[)）]|[a-zA-Z][)）]|\([一二三四五六七八九十\d]+\))\s*"
)
_TITLE_ENDINGS = (
    "背景",
    "目标",
    "概述",
    "简介",
    "介绍",
    "说明",
    "调研",
    "原理",
    "架构",
    "设计",
    "方案",
    "流程",
    "步骤",
    "任务",
    "阶段",
    "部分",
    "实现",
    "实践",
    "配置",
    "能力",
    "模块",
    "模型",
    "职责",
    "场景",
    "机制",
    "接口",
    "策略",
    "规范",
    "问题",
    "分析",
    "优化",
    "规划",
    "思考",
    "总结",
    "展望",
    "参考",
)
_SENTENCE_ENDINGS = (
    "。",
    "！",
    "？",
    "；",
    "，",
    "：",
    ".",
    "!",
    "?",
    ";",
    ",",
    ":",
)
_CODE_LIKE_RE = re.compile(
    r"(?:[={}<>]|https?://|\b(?:while|return|for|if|else|public|private|protected|"
    r"class|def|import|new|void|static)\b)",
    re.IGNORECASE,
)
_CODE_COMMENT_RE = re.compile(r"^(?://|/\*|\*\s|--\s)")
_FIGURE_CAPTION_RE = re.compile(r"^[图表]\s*\d+", re.IGNORECASE)


@dataclass
class _Section:
    path: tuple[str, ...]
    level: int
    body: str


def _compact_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip(" #\t")


def _heading(
    line: str,
    *,
    is_first_content_line: bool = False,
    allow_plain_heading: bool = True,
) -> tuple[int, str] | None:
    value = _compact_title(line)
    if not value or _PAGE_NUMBER_RE.match(value) or len(value) > 64:
        return None

    match = HEADING_MARKER_RE.match(value)
    if match:
        level, title = match.groups()
        return int(level), _compact_title(title)

    match = _MARKDOWN_HEADING_RE.match(value)
    if match:
        return None

    if _CODE_COMMENT_RE.match(value) or _FIGURE_CAPTION_RE.match(value):
        return None

    match = _CHINESE_HEADING_RE.match(value)
    if match:
        prefix, title = match.groups()
        level = 1 if prefix.startswith("第") else 2
        return level, _compact_title(f"{prefix}{title}")

    match = _DECIMAL_HEADING_RE.match(value)
    if (
        match
        and not _LIST_PREFIX_RE.match(value)
        and not match.group(2).endswith(_SENTENCE_ENDINGS)
    ):
        number, title = match.groups()
        title = _compact_title(title)
        meaningful = re.sub(r"[\W\d_]+", "", title, flags=re.UNICODE)
        single_level = number.rstrip(".").count(".") == 0
        table_like = len(title.split()) >= 3 and all(
            len(part) <= 8 for part in title.split()
        )
        if (
            len(meaningful) < 2
            or _CODE_LIKE_RE.search(title)
            or table_like
            or (single_level and not title.endswith(_TITLE_ENDINGS))
        ):
            return None
        level = min(number.rstrip(".").count(".") + 2, 6)
        return level, _compact_title(f"{number} {title}")

    if not allow_plain_heading:
        return None

    if is_first_content_line:
        return 1, value

    if (
        _LIST_PREFIX_RE.match(value)
        or _CODE_LIKE_RE.search(value)
        or value.endswith(_SENTENCE_ENDINGS)
    ):
        return None
    table_like = len(value.split()) >= 3 and all(len(part) <= 8 for part in value.split())
    if len(value) <= 32 and not table_like and value.endswith(_TITLE_ENDINGS):
        return 2, value
    return None


def _normalise_text(text: str) -> str:
    lines: list[str] = []
    blank = False
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = "".join(char for char in raw_line if char >= " " or char == "\t").strip()
        if _PAGE_NUMBER_RE.match(line):
            continue
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    return "\n".join(lines).strip()


def _extract_sections(document_title: str, text: str) -> list[_Section]:
    root_title = document_title.rsplit(".", 1)[0]
    lines = _normalise_text(text).split("\n")
    has_layout_headings = any(
        HEADING_MARKER_RE.match(_compact_title(line)) for line in lines if line
    )
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = [(0, root_title)]
    current_path = (root_title,)
    current_level = 0
    body_lines: list[str] = []
    first_content_seen = False

    def flush() -> None:
        body = "\n".join(body_lines).strip()
        if body:
            sections.append(_Section(current_path, current_level, body))
        body_lines.clear()

    for line in lines:
        if not line:
            if body_lines and body_lines[-1] != "":
                body_lines.append("")
            continue

        detected = _heading(
            line,
            is_first_content_line=not first_content_seen and not has_layout_headings,
            allow_plain_heading=not has_layout_headings,
        )
        first_content_seen = True
        if detected:
            level, heading_title = detected
            if heading_title.casefold() == root_title.casefold():
                continue
            flush()
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_title))
            current_path = tuple(item[1] for item in stack)
            current_level = level
            continue
        body_lines.append(line)

    flush()
    return sections or [_Section((root_title,), 0, _normalise_text(text))]


def _merge_sections(left: _Section, right: _Section) -> _Section:
    common_length = 0
    for left_part, right_part in zip(left.path, right.path):
        if left_part != right_part:
            break
        common_length += 1
    common = left.path[: max(1, common_length)]
    left_title = left.path[-1]
    right_title = right.path[-1]
    merged_title = left_title if left_title == right_title else f"{left_title} / {right_title}"
    body = f"{left.body}\n\n{right_title}\n{right.body}".strip()
    return _Section(common + (merged_title,), left.level, body)


def _merge_short_sections(sections: list[_Section], min_chars: int) -> list[_Section]:
    merged: list[_Section] = []
    index = 0
    while index < len(sections):
        section = sections[index]
        if len(section.body) < min_chars:
            if merged and merged[-1].level == section.level:
                merged[-1] = _merge_sections(merged[-1], section)
                index += 1
                continue
            if index + 1 < len(sections) and sections[index + 1].level == section.level:
                merged.append(_merge_sections(section, sections[index + 1]))
                index += 2
                continue
        merged.append(section)
        index += 1
    return merged


def _render_chunk(document_title: str, path: tuple[str, ...], body: str) -> Document:
    section_path = " > ".join(path)
    content = f"[文档] {document_title}\n[章节] {section_path}\n\n{body.strip()}"
    return Document(
        page_content=content,
        metadata={
            "source": document_title,
            "section": path[-1],
            "section_path": list(path),
            "structural": True,
        },
    )


def _merge_short_bodies(
    bodies: list[str], min_chars: int, max_chars: int
) -> list[str]:
    merged: list[str] = []
    for body in bodies:
        if (
            len(body) < min_chars
            and merged
            and len(merged[-1]) + len(body) + 2 <= max_chars
        ):
            merged[-1] = f"{merged[-1]}\n\n{body}"
        else:
            merged.append(body)
    if (
        len(merged) > 1
        and len(merged[0]) < min_chars
        and len(merged[0]) + len(merged[1]) + 2 <= max_chars
    ):
        merged[1] = f"{merged[0]}\n\n{merged[1]}"
        merged.pop(0)
    return merged


def split_pdf_text(
    document_title: str,
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 80,
    max_section_chars: int = 1000,
    min_section_chars: int = 150,
) -> list[Document]:
    """Split PDF text by inferred sections, with length splitting scoped per section."""
    sections = _merge_short_sections(
        _extract_sections(document_title, text), min_section_chars
    )
    documents: list[Document] = []
    for section in sections:
        if len(section.body) <= max_section_chars:
            bodies = [section.body]
        else:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
            )
            bodies = splitter.split_text(section.body)
            bodies = _merge_short_bodies(
                bodies, min_chars=min_section_chars, max_chars=max_section_chars
            )
        documents.extend(
            _render_chunk(document_title, section.path, body)
            for body in bodies
            if body.strip()
        )
    return documents

from app.rag.pdf_layout_parser import (
    _LayoutLine,
    _render_layout_text,
    _table_to_markdown,
)
from app.rag.structural_splitter import split_pdf_text


def _line(text, top, size, fontname="Helvetica", page=1):
    return _LayoutLine(
        page=page,
        text=text,
        x0=72,
        x1=420,
        top=top,
        bottom=top + size,
        size=size,
        fontname=fontname,
        page_width=595,
        page_height=842,
    )


def test_layout_headings_feed_structural_splitter():
    lines = [
        _line("Layout Guide", 40, 24, "Helvetica-Bold"),
        _line("Architecture Overview", 100, 18, "Helvetica-Bold"),
        _line("This paragraph describes the architecture and its components.", 135, 11),
        _line("It remains part of the same section in the extracted document.", 151, 11),
        _line("Deployment Process", 210, 18, "Helvetica-Bold"),
        _line("This paragraph describes how the service is deployed safely.", 245, 11),
    ]
    text = _render_layout_text(lines, body_size=11, page_count=1)
    chunks = split_pdf_text("Layout Guide.pdf", text, min_section_chars=0)

    assert "[[PDF_HEADING:1]] Layout Guide" in text
    assert "Architecture Overview" in text
    assert "Deployment Process" in text
    assert [chunk.metadata["section"] for chunk in chunks] == [
        "Architecture Overview",
        "Deployment Process",
    ]
    assert "same section" in chunks[0].page_content


def test_table_rows_render_as_markdown():
    markdown = _table_to_markdown(
        [["parameter", "description"], ["timeout", "request timeout"]]
    )

    assert "| parameter | description |" in markdown
    assert "| timeout | request timeout |" in markdown


def test_long_definition_is_not_treated_as_layout_heading():
    definition = (
        "Domain Service: a stateless responsibility that coordinates several "
        "domain objects and resources"
    )
    lines = [
        _line("Domain Design", 40, 24, "Helvetica-Bold"),
        _line("Key Concepts", 100, 18, "Helvetica-Bold"),
        _line(definition, 135, 13.5, "Helvetica-Bold"),
        _line("The explanation continues in ordinary body text.", 155, 11),
    ]

    text = _render_layout_text(lines, body_size=11, page_count=1)

    assert f"]] {definition}" not in text
    assert definition in text


def test_layout_markers_disable_plain_heading_guessing():
    text = "\n".join(
        [
            "[[PDF_HEADING:1]] Architecture",
            "The platform needs automatic recovery capabilities",
            "This sentence explains the requirement in detail.",
        ]
    )

    chunks = split_pdf_text("guide.pdf", text, min_section_chars=0)

    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "Architecture"
    assert "automatic recovery capabilities" in chunks[0].page_content

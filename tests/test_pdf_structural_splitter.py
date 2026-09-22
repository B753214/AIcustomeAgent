from app.rag.structural_splitter import split_pdf_text


def _body(document):
    return document.page_content.split("\n\n", 1)[1]


def test_short_section_stays_whole_and_has_heading():
    text = "测试文档\n\n1. 架构设计\n\n" + "这是架构正文。" * 40

    chunks = split_pdf_text("测试文档.pdf", text)

    assert len(chunks) == 1
    assert "[章节] 测试文档 > 1. 架构设计" in chunks[0].page_content
    assert "这是架构正文" in chunks[0].page_content


def test_long_section_splits_only_inside_its_section():
    first = "第一章节内容。" * 180
    second = "第二章节内容。" * 30
    text = f"测试文档\n\n1. 第一部分\n\n{first}\n\n2. 第二部分\n\n{second}"

    chunks = split_pdf_text("测试文档.pdf", text)
    first_chunks = [chunk for chunk in chunks if "1. 第一部分" in chunk.metadata["section_path"]]
    second_chunks = [chunk for chunk in chunks if "2. 第二部分" in chunk.metadata["section_path"]]

    assert len(first_chunks) > 1
    assert len(second_chunks) == 1
    assert all("第二章节内容" not in _body(chunk) for chunk in first_chunks)
    assert "第一章节内容" not in _body(second_chunks[0])


def test_adjacent_short_sections_at_same_level_are_merged():
    text = (
        "测试文档\n\n"
        "1. 背景介绍\n\n短背景。\n\n"
        "2. 目标说明\n\n短目标。\n\n"
        "3. 完整方案\n\n" + "完整方案内容。" * 30
    )

    chunks = split_pdf_text("测试文档.pdf", text, min_section_chars=150)

    assert any("背景介绍 / 2. 目标说明" in chunk.metadata["section"] for chunk in chunks)
    assert any("短背景" in chunk.page_content and "短目标" in chunk.page_content for chunk in chunks)


def test_table_list_and_code_remain_whole_when_section_is_under_limit():
    text = """测试文档

配置说明

| 参数 | 说明 |
| timeout | 超时时间 |

1）第一步
2）第二步

```python
def run():
    return True
```
"""

    chunks = split_pdf_text("测试文档.pdf", text)

    assert len(chunks) == 1
    assert "| timeout | 超时时间 |" in chunks[0].page_content
    assert "1）第一步\n2）第二步" in chunks[0].page_content
    assert "def run():\nreturn True" in chunks[0].page_content


def test_every_chunk_contains_document_and_section_headers():
    text = "测试文档\n\n方案设计\n\n" + "一段完整内容。" * 200

    chunks = split_pdf_text("测试文档.pdf", text)

    assert len(chunks) > 1
    assert all(chunk.page_content.startswith("[文档] 测试文档.pdf\n[章节] ") for chunk in chunks)


def test_year_and_numbered_list_are_not_mistaken_for_headings():
    text = (
        "测试文档\n\n架构设计\n\n"
        "2019 年开始建设业务平台。\n"
        "1）建立模型\n"
        "2）完成迁移\n"
    )

    chunks = split_pdf_text("测试文档.pdf", text)

    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "架构设计"
    assert "2019 年开始建设业务平台" in chunks[0].page_content


def test_page_number_control_character_and_compatible_title_are_normalised():
    text = "测试文档\n1.\n\n测\x01试说明\n\n这是正文。" * 20

    chunks = split_pdf_text("测试文档.pdf", text)

    assert all("\x01" not in chunk.page_content for chunk in chunks)
    assert all("\n1.\n" not in chunk.page_content for chunk in chunks)


def test_numeric_code_steps_and_table_header_stay_in_section_body():
    text = """测试文档

方案设计

对比项 原方案 新方案
1. 初始化 executed = {}
2. while remaining 非空:
3. return layers
"""

    chunks = split_pdf_text("测试文档.pdf", text)

    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "方案设计"
    assert "1. 初始化 executed = {}" in chunks[0].page_content
    assert "对比项 原方案 新方案" in chunks[0].page_content


def test_short_tail_from_long_section_is_merged_within_same_section():
    text = "测试文档\n\n方案设计\n\n" + ("完整句子。" * 240) + "短尾巴。"

    chunks = split_pdf_text("测试文档.pdf", text)
    bodies = [_body(chunk) for chunk in chunks]

    assert len(chunks) > 1
    assert all(len(body) >= 150 for body in bodies)
    assert sum("短尾巴" in body for body in bodies) == 1


def test_code_comments_and_figure_captions_are_not_headings():
    text = """测试文档

代码实现

// 无过期时间点，使用全局配置
public Result getResult() { return cachedResult; }

图 12 BFF 在支付域的实践和规划
图表对应的正文说明。
"""

    chunks = split_pdf_text("测试文档.pdf", text)

    assert len(chunks) == 1
    assert chunks[0].metadata["section"] == "代码实现"
    assert "// 无过期时间点" in chunks[0].page_content
    assert "图 12 BFF" in chunks[0].page_content

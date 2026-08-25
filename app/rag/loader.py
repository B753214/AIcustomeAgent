from pathlib import Path


def _parse_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(p.strip() for p in pages if p.strip())


def _parse_docx(path):
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())


def parse_file(path: Path):
    suffix = path.suffix.lower()
    print(f"suffix: {suffix}")
    if suffix == ".pdf":
        return _parse_pdf(path)
    elif suffix == ".docx":
        return _parse_docx(path)
    elif suffix in (".txt", ".md", ".markdown"):
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

if __name__ == "__main__":
    path = Path("../db/knowledge_base.md")
    content = parse_file(path)


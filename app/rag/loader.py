import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def _parse_pdf(path):
    try:
        from app.rag.pdf_layout_parser import extract_pdf_text

        text = extract_pdf_text(path)
        if text.strip():
            return text
    except (ImportError, ModuleNotFoundError):
        logger.info("pdfplumber is unavailable; falling back to pypdf for %s", path)
    except Exception as exc:
        logger.warning("pdfplumber failed for %s; falling back to pypdf: %s", path, exc)

    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


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
    print(content)


"""Extracting text from a document for `summarize_document`.

`pypdf` (new dependency - pure Python, no C extension) reads a PDF's text
layer. It cannot do anything with a *scanned* PDF (a photograph of a page
with no text layer at all, common for old paperwork) - there is no OCR
here, and adding one (Tesseract, a real system dependency) is a bigger step
than a "resume ce PDF" feature needs today. `extract_text` returns "" for
that case the same way it does for a genuinely empty document; the caller
(`main.py`) cannot tell the difference and says the same honest "nothing to
summarize" either way, which is the truthful thing to say in both cases -
there is nothing this code found to read.
"""

from pathlib import Path

# Bounds extraction, not what reaches the model - that is
# NemotronClient.SUMMARIZE_MAX_CHARS's job, on the text this returns. A
# genuinely huge document (hundreds of pages) would otherwise cost real time
# just to *extract* text nobody is going to hear read back anyway, before
# the character cap downstream ever gets a chance to matter.
MAX_PAGES = 30


def extract_text(path: Path) -> str:
    """The text content of the document at `path`, or "" if there is none
    to extract (a scanned PDF with no text layer, a corrupt file, an empty
    document) - never raises for a file that exists but yields nothing."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    if suffix in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def _extract_pdf_text(path: Path) -> str:
    import pypdf

    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return ""  # not a valid PDF, or password-protected - nothing readable either way
    pages = reader.pages[:MAX_PAGES]
    texts = []
    for page in pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue  # one malformed page must not lose the rest of the document
    return "\n".join(texts).strip()

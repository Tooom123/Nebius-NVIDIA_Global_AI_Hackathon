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

# A ceiling on extraction, not on what gets summarised. It used to be 30,
# which combined with the character cap downstream meant "resume ce PDF" on
# a sixty-page report answered from its first few pages and said nothing
# about the rest - a wrong answer presented as a complete one, which is
# worse than either reading it all or admitting the limit.
#
# Long documents are now read in full and summarised in chunks (see
# `NemotronClient.summarize_long_text`), so this exists only to stop a
# pathological file - a thousand-page scan - spending minutes in extraction
# before anything is spoken. When it does bite, the caller is told, so the
# user hears that it read part of the document rather than being left to
# assume otherwise.
MAX_PAGES = 300


def extract_text(path: Path) -> str:
    """The text content of the document at `path`, or "" if there is none
    to extract (a scanned PDF with no text layer, a corrupt file, an empty
    document) - never raises for a file that exists but yields nothing."""
    return extract(path).text


class Extraction:
    """Extracted text, plus whether it is the whole document.

    `complete` is False when `MAX_PAGES` cut the document short. It exists
    so the caller can say so out loud: silently summarising part of a
    document as though it were all of it is the exact failure this replaced.
    """

    __slots__ = ("text", "complete", "pages_read", "pages_total")

    def __init__(self, text: str, complete: bool = True,
                 pages_read: int = 0, pages_total: int = 0) -> None:
        self.text = text
        self.complete = complete
        self.pages_read = pages_read
        self.pages_total = pages_total


def extract(path: Path) -> Extraction:
    """`extract_text`, plus whether anything was left unread."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in (".txt", ".md"):
        try:
            return Extraction(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return Extraction("")
    return Extraction("")


def _extract_pdf(path: Path) -> Extraction:
    import pypdf

    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return Extraction("")  # not a valid PDF, or password-protected
    total = len(reader.pages)
    pages = reader.pages[:MAX_PAGES]
    texts = []
    for page in pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue  # one malformed page must not lose the rest of the document
    return Extraction(
        "\n".join(texts).strip(),
        complete=total <= MAX_PAGES,
        pages_read=min(total, MAX_PAGES),
        pages_total=total,
    )

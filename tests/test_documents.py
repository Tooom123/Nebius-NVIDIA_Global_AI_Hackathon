"""Tests for extracting text out of a document for "summarize_document".

pypdf itself is well-established and not what's being tested here - what
matters is this module's own contract: "" (never an exception) for anything
that yields no readable text, whether that's a genuinely empty file, a
scanned PDF with no text layer, or a corrupt one, since the caller cannot
tell those apart and says the same honest thing regardless.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from heypeer.executor.documents import extract_text


def test_extracts_text_from_a_plain_text_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("Facture de 42 euros pour mars.", encoding="utf-8")

    assert extract_text(path) == "Facture de 42 euros pour mars."


def test_extracts_text_from_a_markdown_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Titre\n\nUn paragraphe.", encoding="utf-8")

    assert "Un paragraphe." in extract_text(path)


def test_an_unsupported_extension_returns_empty_rather_than_guessing(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0not a real jpeg but not text either")

    assert extract_text(path) == ""


def test_a_missing_file_returns_empty_rather_than_raising(tmp_path: Path) -> None:
    assert extract_text(tmp_path / "does_not_exist.txt") == ""


def test_a_blank_pdf_page_extracts_no_text(tmp_path: Path) -> None:
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "blank.pdf"
    with open(path, "wb") as f:
        writer.write(f)

    assert extract_text(path) == ""


def test_a_corrupt_pdf_extracts_no_text_rather_than_raising(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4\nnot actually a valid pdf body")

    assert extract_text(path) == ""


def test_one_malformed_page_does_not_lose_the_rest_of_the_document() -> None:
    """A page whose extract_text() itself raises must not abort the whole
    document - the other pages are still worth reading."""
    good_page = MagicMock()
    good_page.extract_text.return_value = "Page utile."
    bad_page = MagicMock()
    bad_page.extract_text.side_effect = Exception("malformed content stream")

    fake_reader = MagicMock()
    fake_reader.pages = [good_page, bad_page]

    with patch("pypdf.PdfReader", return_value=fake_reader):
        result = extract_text(Path("whatever.pdf"))

    assert result == "Page utile."


def test_pages_beyond_the_cap_are_not_extracted() -> None:
    pages = [MagicMock(extract_text=MagicMock(return_value=f"p{i}")) for i in range(40)]
    fake_reader = MagicMock()
    fake_reader.pages = pages

    with patch("pypdf.PdfReader", return_value=fake_reader):
        from heypeer.executor.documents import MAX_PAGES

        extract_text(Path("big.pdf"))

    for page in pages[:MAX_PAGES]:
        page.extract_text.assert_called_once()
    for page in pages[MAX_PAGES:]:
        page.extract_text.assert_not_called()

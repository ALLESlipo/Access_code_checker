"""Extract access codes from an uploaded PDF.

Two PDF types are supported and detected automatically:

1. Kit insert ("kit_insert"), e.g. testpdf.pdf
       One kit per page; the access code (e.g. ABC234XYZ) is printed 3 times
       per page. Every 9-character token from the code alphabet is taken as a
       code. A code on two different pages is reported as a duplicate.

2. Lab report ("lab_report"), e.g. KIT000012345_XYZ789ABC.pdf
       The laboratory result (Russian IAT report) shows a sample ID
       "<kit ID>_<access code>", e.g. "KIT000012345_XYZ789ABC" in the
       "Пациент:" field. The access code is the part AFTER the underscore
       (XYZ789ABC). Only these sample IDs are used for this type; the rest of
       the report text is ignored, so lab values or Latin species names can
       never be mistaken for codes. The same sample ID repeats on several
       pages of one report; that is normal and NOT reported as a duplicate.
       Several reports merged into one PDF work too (one code per sample ID);
       the same access code under two DIFFERENT kit IDs is reported.

   Detection: if at least one sample ID is found anywhere in the PDF, the PDF
   is treated as a lab report, otherwise as a kit insert.

How the text is read:
    `pdftotext` (package "poppler-utils", already installed) converts the PDF
    to plain text; pages are separated by a form-feed character (\f), which
    gives the page number of each code. No pip is available and the standard
    library cannot read PDFs, hence the external tool. Scanned (image-only)
    PDFs contain no text and would need OCR, which is not supported.

The code alphabet:
    Access codes are 9 characters from 2-9 and A-Z without I and O (the
    generator leaves those out because they look like 1 and 0).
"""

import os
import re
import shutil
import subprocess
import tempfile

# One access code: 9 characters of the code alphabet.
_CODE = r"[2-9A-HJ-NP-Z]{9}"

# Kit insert: a code standing alone (not glued to other letters/digits).
# "_" is deliberately NOT part of the look-behind, see SAMPLE_ID_PATTERN.
CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(%s)(?![A-Za-z0-9_])" % _CODE)

# Lab report: "<kit ID>_<access code>", e.g. KIT000012345_XYZ789ABC.
# Kit IDs seen so far are 10-14 uppercase letters/digits (KIT000012345,
# KIT00000000123). Group 1 = kit ID, group 2 = access code.
SAMPLE_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([A-Z0-9]{10,14})_(%s)(?![A-Za-z0-9_])" % _CODE)

# Lab-report sample IDs whose part after "_" is NOT a 9-character access code,
# e.g. older reports like KIT000067890_0000AAAA1111BBBB (16 characters).
# They are not checked, only reported so the user knows why no code was found.
OTHER_SAMPLE_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([A-Z0-9]{10,14})_([A-Z0-9]{10,20})(?![A-Za-z0-9_])")

# Uppercase 9-letter words that could appear in kit-insert templates and
# would otherwise look like codes. Extend if a new template causes false hits.
IGNORE_WORDS = {"TESTKITID"}

# PDF types returned by extract_codes().
TYPE_KIT_INSERT = "kit_insert"
TYPE_LAB_REPORT = "lab_report"

# Safety limit so a broken PDF cannot hang the server.
PDFTOTEXT_TIMEOUT_SECONDS = 60


class PdfError(Exception):
    """Raised when the PDF cannot be converted to text (tool missing, corrupt file, timeout)."""


def pdf_to_pages(pdf_bytes):
    """Convert PDF bytes to a list of page texts using pdftotext.

    Args:
        pdf_bytes: The raw content of the uploaded PDF file.

    Returns:
        list[str]: One string per page (index 0 = page 1).

    Raises:
        PdfError: If pdftotext is not installed, fails, or times out.
    """
    if shutil.which("pdftotext") is None:
        raise PdfError("pdftotext is not installed (install the 'poppler-utils' package)")
    if not pdf_bytes.startswith(b"%PDF"):
        raise PdfError("the uploaded file is not a PDF")

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
        proc = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", tmp_path, "-"],
            capture_output=True,
            timeout=PDFTOTEXT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfError("reading the PDF took too long") from exc
    finally:
        os.unlink(tmp_path)

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise PdfError("could not read the PDF" + (f": {detail[-1]}" if detail else ""))
    text = proc.stdout.decode("utf-8", "replace")
    pages = text.split("\f")
    # pdftotext ends the output with a form feed -> drop the empty last "page".
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _add(found, code, page, sample_id=None):
    """Record one occurrence of `code` in the `found` dict (helper for the extractors).

    Args:
        found: {code: {"code", "pages": [..], "sample_ids": [..]}} being built.
        code: The access code.
        page: 1-based page number.
        sample_id: Full lab-report sample ID ("KIT000012345_XYZ789ABC") or None.
    """
    entry = found.setdefault(code, {"code": code, "pages": [], "sample_ids": []})
    if page not in entry["pages"]:
        entry["pages"].append(page)
    if sample_id and sample_id not in entry["sample_ids"]:
        entry["sample_ids"].append(sample_id)


def codes_from_pages(pages):
    """Detect the PDF type and extract the access codes from already-extracted page texts.

    Separated from extract_codes() so it can be tested with plain strings.

    Args:
        pages: list of page texts (index 0 = page 1).

    Returns:
        dict:
            "type":  TYPE_LAB_REPORT or TYPE_KIT_INSERT,
            "codes": list of {"code", "pages", "sample_ids"} in order of first
                     appearance. "sample_ids" is empty for kit inserts.
            "unsupported_ids": lab-report sample IDs whose suffix is not a
                     9-character access code (see OTHER_SAMPLE_ID_PATTERN).
                     If any exist, the PDF counts as a lab report.
    """
    found = {}
    unsupported = []
    for page_number, text in enumerate(pages, start=1):
        for match in SAMPLE_ID_PATTERN.finditer(text):
            _add(found, match.group(2), page_number, f"{match.group(1)}_{match.group(2)}")
        for match in OTHER_SAMPLE_ID_PATTERN.finditer(text):
            if match.group(0) not in unsupported:
                unsupported.append(match.group(0))
    if found or unsupported:
        return {"type": TYPE_LAB_REPORT, "codes": list(found.values()), "unsupported_ids": unsupported}

    for page_number, text in enumerate(pages, start=1):
        for match in CODE_PATTERN.finditer(text):
            if match.group(1) not in IGNORE_WORDS:
                _add(found, match.group(1), page_number)
    return {"type": TYPE_KIT_INSERT, "codes": list(found.values()), "unsupported_ids": []}


def extract_codes(pdf_bytes):
    """Read a PDF and return its type and access codes.

    Args:
        pdf_bytes: The raw content of the uploaded PDF file.

    Returns:
        dict: {"pages": number of pages, "type": ..., "codes": [...]}
              (see codes_from_pages() for "type" and "codes").

    Raises:
        PdfError: See pdf_to_pages().
    """
    pages = pdf_to_pages(pdf_bytes)
    result = codes_from_pages(pages)
    result["pages"] = len(pages)
    return result

"""Minimal .xlsx reader/writer built only on the Python standard library.

Why not openpyxl?
    The machine Booty runs on has no pip, so third-party packages cannot be
    installed. An .xlsx file is a ZIP archive of XML files, so the two things
    Booty needs (read the first sheet as a table, change a few cells) can be
    done with `zipfile` + `xml.etree` / `re`.

What this module guarantees when writing:
    * Only the cells you ask to change are touched; every other byte of the
      sheet XML and every other file inside the archive is copied unchanged,
      so formatting, column widths, other sheets etc. are preserved.
    * Changed cells keep their style index (`s="..."`) and are written as
      inline strings (`t="inlineStr"`), which Excel and LibreOffice both read.
      This avoids having to edit the shared-strings table.
    * The file is written to a temporary file in the same folder and then
      atomically renamed over the original, so a crash never leaves a
      half-written workbook.

Limitations (fine for the access-code exports, document if that changes):
    * Only the FIRST worksheet of a workbook is read/written.
    * The first row is treated as the header row.
"""

import os
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

# XML namespaces used inside .xlsx files.
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_M = "{%s}" % NS_MAIN

# Splits a cell reference such as "AB12" into ("AB", "12").
_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")


class XlsxError(Exception):
    """Raised when a workbook cannot be read or updated (corrupt file, missing sheet, missing row...)."""


def column_letter_to_index(letters):
    """Convert a column name to a 1-based index.

    Args:
        letters: Column letters as used in cell references, e.g. "A", "Z", "AA".

    Returns:
        int: 1 for "A", 26 for "Z", 27 for "AA", ...
    """
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def column_index_to_letter(index):
    """Convert a 1-based column index back to its letters (inverse of column_letter_to_index).

    Args:
        index: 1-based column number.

    Returns:
        str: e.g. "A" for 1, "AA" for 27.
    """
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _first_sheet_part(zf):
    """Find the archive path of the first worksheet in the workbook.

    The order of sheets is defined in xl/workbook.xml; each <sheet> points via
    a relationship id (r:id) to a target in xl/_rels/workbook.xml.rels.

    Args:
        zf: An open zipfile.ZipFile of the .xlsx.

    Returns:
        str: Path inside the archive, e.g. "xl/worksheets/sheet1.xml".

    Raises:
        XlsxError: If the workbook has no sheets.
    """
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets = workbook.find(_M + "sheets")
    if sheets is None or len(sheets) == 0:
        raise XlsxError("workbook contains no sheets")
    rel_id = sheets[0].get("{%s}id" % NS_REL_DOC)

    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("{%s}Relationship" % NS_REL_PKG):
        if rel.get("Id") == rel_id:
            target = rel.get("Target")
            # Targets are relative to xl/ unless they start with "/".
            if target.startswith("/"):
                return target.lstrip("/")
            return posixpath.normpath(posixpath.join("xl", target))
    # Fallback used by most generators.
    return "xl/worksheets/sheet1.xml"


def _shared_strings(zf):
    """Load the shared-strings table (strings referenced by index from cells with t="s").

    Args:
        zf: An open zipfile.ZipFile of the .xlsx.

    Returns:
        list[str]: The table; empty if the workbook has no shared strings.
        Rich-text entries (<r><t>..</t></r>) are flattened to plain text.
    """
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(_M + "t")) for si in root.findall(_M + "si")]


def _cell_value(cell, shared):
    """Return the displayed value of one <c> element as a string.

    Handles shared strings (t="s"), inline strings (t="inlineStr"),
    booleans (t="b") and plain numbers/formula results.

    Args:
        cell: The <c> XML element.
        shared: Shared-strings table from _shared_strings().

    Returns:
        str: The value, or "" for an empty cell.
    """
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(_M + "t"))
    v = cell.find(_M + "v")
    if v is None or v.text is None:
        return ""
    if cell_type == "s":
        return shared[int(v.text)]
    if cell_type == "b":
        return "TRUE" if v.text == "1" else "FALSE"
    return v.text


def read_first_sheet(path):
    """Read the first worksheet of an .xlsx file as a table.

    Args:
        path: Filesystem path of the .xlsx file.

    Returns:
        dict with keys:
            "sheet_part": archive path of the sheet (needed later by update_cells),
            "header":     {column_name: column_letter} from the first row,
            "rows":       list of dicts {column_name: value, "_row": excel_row_number}
                          for every data row (row 2 onwards).

    Raises:
        XlsxError: If the file is not a valid workbook.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            sheet_part = _first_sheet_part(zf)
            shared = _shared_strings(zf)
            sheet = ET.fromstring(zf.read(sheet_part))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise XlsxError(f"cannot read {os.path.basename(path)}: {exc}") from exc

    sheet_data = sheet.find(_M + "sheetData")
    header = {}
    rows = []
    if sheet_data is None:
        return {"sheet_part": sheet_part, "header": header, "rows": rows}

    for row_index, row in enumerate(sheet_data.findall(_M + "row"), start=1):
        row_number = int(row.get("r", row_index))
        values = {}
        for col_pos, cell in enumerate(row.findall(_M + "c"), start=1):
            ref = cell.get("r")
            letters = _CELL_REF_RE.match(ref).group(1) if ref else column_index_to_letter(col_pos)
            values[letters] = _cell_value(cell, shared)
        if not header:
            # First row = header: map name -> column letter.
            header = {name.strip(): letters for letters, name in values.items() if name.strip()}
            continue
        record = {name: values.get(letters, "") for name, letters in header.items()}
        record["_row"] = row_number
        rows.append(record)
    return {"sheet_part": sheet_part, "header": header, "rows": rows}


def _xml_escape(text):
    """Escape &, < and > so text can be placed inside an XML element."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_cell(ref, style_attr, value):
    """Build the XML of a cell holding an inline string.

    Args:
        ref: Cell reference, e.g. "F12".
        style_attr: The original ` s="N"` attribute (or "") so formatting is kept.
        value: The new text.

    Returns:
        str: e.g. '<c r="F12" s="1" t="inlineStr"><is><t>Used</t></is></c>'.
    """
    return f'<c r="{ref}"{style_attr} t="inlineStr"><is><t>{_xml_escape(value)}</t></is></c>'


def _set_cell(sheet_xml, ref, value):
    """Replace (or insert) a single cell inside the raw sheet XML text.

    Args:
        sheet_xml: The whole worksheet XML as a str.
        ref: Cell reference to set, e.g. "E2296".
        value: New string value.

    Returns:
        str: The updated worksheet XML.

    Raises:
        XlsxError: If the row of the cell does not exist in the sheet.
    """
    # 1) Cell exists: either <c r="E5" .../> or <c r="E5" ...>...</c>
    cell_re = re.compile(r'<c r="%s"(?=[\s>/])([^>]*?)(?:/>|>.*?</c>)' % re.escape(ref), re.S)
    match = cell_re.search(sheet_xml)
    if match:
        style = re.search(r'\ss="\d+"', match.group(1))
        new_cell = _inline_cell(ref, style.group(0) if style else "", value)
        return sheet_xml[: match.start()] + new_cell + sheet_xml[match.end():]

    # 2) Cell missing: insert it into its row, keeping cells in column order.
    letters, row_number = _CELL_REF_RE.match(ref).groups()
    row_re = re.compile(r'(<row r="%s"(?=[\s>/])[^>]*?)(/>|>(.*?)</row>)' % row_number, re.S)
    row_match = row_re.search(sheet_xml)
    if not row_match:
        raise XlsxError(f"row {row_number} not found while setting {ref}")
    new_cell = _inline_cell(ref, "", value)
    if row_match.group(2) == "/>":  # empty self-closing row
        new_row = f"{row_match.group(1)}>{new_cell}</row>"
    else:
        body = row_match.group(3)
        target = column_letter_to_index(letters)
        insert_at = len(body)
        for cell in re.finditer(r'<c r="([A-Z]+)\d+"', body):
            if column_letter_to_index(cell.group(1)) > target:
                insert_at = cell.start()
                break
        new_row = f"{row_match.group(1)}>{body[:insert_at]}{new_cell}{body[insert_at:]}</row>"
    return sheet_xml[: row_match.start()] + new_row + sheet_xml[row_match.end():]


def update_cells(path, sheet_part, updates):
    """Write new string values into specific cells of an .xlsx file, in place.

    Args:
        path: Filesystem path of the .xlsx file.
        sheet_part: Archive path of the sheet, as returned by read_first_sheet().
        updates: {cell_ref: new_value}, e.g. {"E2296": "t", "F2296": "Used"}.

    The archive is rebuilt entry by entry: the sheet gets the modified XML, all
    other entries are copied byte-for-byte with their original compression.
    The result is written to a temp file and atomically moved over `path`.

    Raises:
        XlsxError: If a target row does not exist.
    """
    if not updates:
        return
    with zipfile.ZipFile(path) as src:
        sheet_xml = src.read(sheet_part).decode("utf-8")
        for ref, value in updates.items():
            sheet_xml = _set_cell(sheet_xml, ref, value)

        folder = os.path.dirname(os.path.abspath(path))
        fd, tmp_path = tempfile.mkstemp(prefix=".booty_tmp_", suffix=".xlsx", dir=folder)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp_path, "w") as dst:
                for info in src.infolist():
                    data = sheet_xml.encode("utf-8") if info.filename == sheet_part else src.read(info.filename)
                    dst.writestr(info, data, compress_type=info.compress_type)
        except Exception:
            os.unlink(tmp_path)
            raise
    os.chmod(tmp_path, os.stat(path).st_mode & 0o777)
    os.replace(tmp_path, path)

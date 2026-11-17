"""Reference data for Booty: every .xlsx / .csv in the existing_access_codes folder.

The reference folder holds exports of generated access codes. All files must
have the same columns as the original export:

    id, code, generated_by, created_at, used, status, batch_id, printed_at

Check rules (agreed with the product owner):

    * Code NOT in any reference file
          -> message "Code not found in the reference files", nothing is changed.
    * Code found and its status is still "Not Used"
          -> message "Code already generated before"
          -> the row is updated to used="t", status="Used" in EVERY reference
             file that contains the code (the file on disk is changed).
    * Code found and its status is already "Used"
          -> message "Code already checked and exists", nothing is changed
             (status stays "Used").

Safety:
    * Before a reference file is modified for the first time while the server
      is running, a timestamped copy is saved to
      existing_access_codes/.booty_backups/.
    * All checks go through one lock, so two browser tabs checking at the same
      time cannot interleave reads and writes.
    * Files are re-read on every check, so new exports dropped into the folder
      (or edits made in Excel) are picked up without restarting Booty.
"""

import csv
import datetime
import os
import re
import shutil
import threading

from . import xlsx_io

# Columns every reference file must contain (others are allowed and ignored).
REQUIRED_COLUMNS = ("code", "used", "status")

# Values written when a code is marked as used. They match what the export
# system itself writes for used codes (used = "t", status = "Used").
USED_FLAG_VALUE = "t"
USED_STATUS_VALUE = "Used"

# User-facing messages. Keep in sync with static/app.js and the documentation.
MSG_GENERATED_BEFORE = "Code already generated before"
MSG_ALREADY_CHECKED = "Code already checked and exists"
MSG_NOT_FOUND = "Code not found in the reference files"

# Outcome identifiers sent to the browser (used for colours/icons there).
OUTCOME_GENERATED_BEFORE = "generated_before"
OUTCOME_ALREADY_CHECKED = "already_checked"
OUTCOME_NOT_FOUND = "not_found"

# Shape of a "normal" access code; anything else gets a format warning
# (it is still looked up, the warning is only informative).
CODE_FORMAT_RE = re.compile(r"^[A-Z0-9]{9}$")

BACKUP_DIR_NAME = ".booty_backups"


def normalize_code(raw):
    """Normalise user input to the canonical code form.

    Args:
        raw: A code as typed or extracted, possibly with spaces / lowercase.

    Returns:
        str: The code stripped of surrounding whitespace and upper-cased.
    """
    return raw.strip().upper()


def is_used(record):
    """Decide whether a reference row is already marked as used.

    A row counts as used if `status` is "Used" OR `used` is a truthy flag
    ("t", "true", "1", "yes"). Both are checked because the two columns
    could drift apart if someone edits a file by hand.

    Args:
        record: Row dict with at least "used" and "status".

    Returns:
        bool
    """
    status = record.get("status", "").strip().lower()
    flag = record.get("used", "").strip().lower()
    return status == "used" or flag in ("t", "true", "1", "yes")


def within_one_edit(a, b):
    """True if `a` and `b` differ by exactly one substituted, inserted or deleted character.

    Used to suggest "Did you mean ...?" for codes that were not found.
    Access codes in the export never differ from each other by a single
    character, so a hit here is a strong hint of a typo.

    Args:
        a, b: Two codes.

    Returns:
        bool
    """
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(x != y for x, y in zip(a, b)) == 1
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


class ReferenceFile:
    """One reference file (.xlsx or .csv) loaded into memory.

    Attributes:
        path:    Absolute path of the file.
        name:    File name shown to users.
        kind:    "xlsx" or "csv".
        rows:    list of row dicts (column name -> value). Each row also has
                 "_row": the spreadsheet row number (header = row 1).
        header:  xlsx: {column name: column letter}; csv: list of column names
                 in file order.
        error:   None if the file loaded fine, otherwise a human-readable reason
                 (the file is then skipped by the checker).
    """

    def __init__(self, path):
        """Create the object and immediately load the file (see load())."""
        self.path = path
        self.name = os.path.basename(path)
        self.kind = "xlsx" if path.lower().endswith(".xlsx") else "csv"
        self.rows = []
        self.header = {}
        self.error = None
        self._sheet_part = None   # xlsx only: archive path of the sheet
        self._csv_dialect = None  # csv only: detected delimiter etc.
        self.load()

    def load(self):
        """(Re)read the file from disk into self.rows / self.header.

        Sets self.error instead of raising, so one broken file does not stop
        Booty from checking against the others.
        """
        self.error = None
        try:
            if self.kind == "xlsx":
                table = xlsx_io.read_first_sheet(self.path)
                self._sheet_part = table["sheet_part"]
                self.header = table["header"]
                self.rows = table["rows"]
                columns = list(self.header)
            else:
                with open(self.path, newline="", encoding="utf-8-sig") as fh:
                    sample = fh.read(4096)
                    fh.seek(0)
                    try:
                        self._csv_dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                    except csv.Error:
                        self._csv_dialect = csv.excel

                    # Keep the file's own line endings when we write it back
                    # (the sniffer always reports "\r\n").
                    class _Dialect(self._csv_dialect):
                        lineterminator = "\r\n" if "\r\n" in sample else "\n"
                    self._csv_dialect = _Dialect
                    reader = csv.DictReader(fh, dialect=self._csv_dialect)
                    self.header = [c.strip() for c in (reader.fieldnames or [])]
                    reader.fieldnames = self.header
                    self.rows = []
                    for line_no, row in enumerate(reader, start=2):
                        row = {k: (v or "") for k, v in row.items() if k is not None}
                        row["_row"] = line_no
                        self.rows.append(row)
                columns = self.header
        except (OSError, UnicodeDecodeError, csv.Error, xlsx_io.XlsxError) as exc:
            self.rows, self.header = [], {}
            self.error = f"could not be read: {exc}"
            return

        missing = [c for c in REQUIRED_COLUMNS if c not in columns]
        if missing:
            self.rows = []
            self.error = f"missing required column(s): {', '.join(missing)}"

    def find(self, code):
        """Return all rows of this file whose `code` equals `code` (already normalised)."""
        return [r for r in self.rows if normalize_code(r.get("code", "")) == code]

    def mark_used(self, rows):
        """Set used="t" and status="Used" for the given rows and save the file.

        Args:
            rows: Row dicts previously returned by find() on this object.

        The in-memory rows are updated too, so later checks in the same
        request see the new status.
        """
        if not rows:
            return
        if self.kind == "xlsx":
            updates = {}
            for r in rows:
                updates[f"{self.header['used']}{r['_row']}"] = USED_FLAG_VALUE
                updates[f"{self.header['status']}{r['_row']}"] = USED_STATUS_VALUE
            xlsx_io.update_cells(self.path, self._sheet_part, updates)
        for r in rows:
            r["used"] = USED_FLAG_VALUE
            r["status"] = USED_STATUS_VALUE
        if self.kind == "csv":
            self._write_csv()

    def _write_csv(self):
        """Rewrite the whole CSV from self.rows (column order and delimiter preserved).

        Written to a temporary file first and then renamed over the original.
        """
        tmp_path = os.path.join(os.path.dirname(self.path), f".booty_tmp_{self.name}")
        with open(tmp_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.header, dialect=self._csv_dialect,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)
        os.replace(tmp_path, self.path)


class ReferenceStore:
    """All reference files in one folder, plus the code-checking logic.

    Typical use (this is what server.py does):

        store = ReferenceStore("/path/to/existing_access_codes")
        report = store.check([("ABC234XYZ", ["typed"]), ...])

    Attributes:
        data_dir: Folder that is scanned for *.xlsx and *.csv files.
    """

    def __init__(self, data_dir):
        """Remember the folder; files are loaded lazily on every check/summary."""
        self.data_dir = os.path.abspath(data_dir)
        self._lock = threading.Lock()
        self._backed_up = set()  # paths already backed up during this server run

    def _discover(self):
        """List the reference files in data_dir.

        Ignored: sub-folders, hidden files (".booty_backups", ".~lock..." files
        created by LibreOffice), Office temp files ("~$..."), other extensions.

        Returns:
            list[ReferenceFile]: Loaded files, sorted by name.
        """
        files = []
        for name in sorted(os.listdir(self.data_dir)):
            full = os.path.join(self.data_dir, name)
            if name.startswith((".", "~$")) or not os.path.isfile(full):
                continue
            if name.lower().endswith((".xlsx", ".csv")):
                files.append(ReferenceFile(full))
        return files

    def _backup(self, ref_file):
        """Copy a reference file to .booty_backups/ once per server run, before its first change.

        Backup name: <original name>.<YYYYmmdd-HHMMSS>.bak
        """
        if ref_file.path in self._backed_up:
            return
        backup_dir = os.path.join(self.data_dir, BACKUP_DIR_NAME)
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(ref_file.path, os.path.join(backup_dir, f"{ref_file.name}.{stamp}.bak"))
        self._backed_up.add(ref_file.path)

    def summary(self):
        """Describe the reference files for the web page header.

        Returns:
            dict: {"folder": ..., "files": [{"name", "codes", "used", "error"}, ...]}
        """
        with self._lock:
            files = self._discover()
        return {
            "folder": self.data_dir,
            "files": [
                {
                    "name": f.name,
                    "codes": len(f.rows),
                    "used": sum(is_used(r) for r in f.rows),
                    "error": f.error,
                }
                for f in files
            ],
        }

    def check(self, items):
        """Check codes against all reference files and apply the status rules.

        Args:
            items: list of (code, sources) tuples. `code` is raw input (it is
                normalised here); `sources` is a list of strings describing
                where the code came from, e.g. ["typed", "PDF page 2"].
                The same code may appear several times; occurrences are merged
                and the code is processed once.

        Returns:
            dict:
                "results": one entry per distinct code, in first-seen order:
                    {
                      "code": "ABC234XYZ",
                      "outcome": "generated_before" | "already_checked" | "not_found",
                      "message": user-facing text (see MSG_* constants),
                      "sources": ["PDF page 1", ...],
                      "times_in_input": int,
                      "format_warning": bool,   # not a normal 9-char code
                      "matches": [ {file, row, batch_id, status_before, status_after}, ... ],
                      "suggestions": ["BLQETESQN", ...]  # only for not_found
                    }
                "files": the summary of reference files after the check,
                "counts": {outcome: number of codes}.
        """
        # Merge duplicates while keeping the order in which codes were seen.
        merged = {}
        for raw, sources in items:
            code = normalize_code(raw)
            if not code:
                continue
            entry = merged.setdefault(code, {"sources": [], "times": 0})
            entry["times"] += 1
            for s in sources:
                if s not in entry["sources"]:
                    entry["sources"].append(s)

        with self._lock:
            files = [f for f in self._discover() if f.error is None]
            all_codes = None  # built lazily, only needed for suggestions
            results = []

            for code, info in merged.items():
                hits = [(f, f.find(code)) for f in files]
                hits = [(f, rows) for f, rows in hits if rows]
                result = {
                    "code": code,
                    "sources": info["sources"],
                    "times_in_input": info["times"],
                    "format_warning": not CODE_FORMAT_RE.match(code),
                    "matches": [],
                    "suggestions": [],
                }

                if not hits:
                    if all_codes is None:
                        all_codes = {normalize_code(r.get("code", "")) for f in files for r in f.rows}
                    result["outcome"] = OUTCOME_NOT_FOUND
                    result["message"] = MSG_NOT_FOUND
                    result["suggestions"] = sorted(c for c in all_codes if within_one_edit(code, c))[:3]
                    results.append(result)
                    continue

                any_unused = any(not is_used(r) for _, rows in hits for r in rows)
                for f, rows in hits:
                    before = {id(r): ("Used" if is_used(r) else r.get("status", "") or "Not Used") for r in rows}
                    to_mark = [r for r in rows if not is_used(r)]
                    if to_mark:
                        self._backup(f)
                        f.mark_used(to_mark)
                    for r in rows:
                        result["matches"].append({
                            "file": f.name,
                            "row": r["_row"],
                            "batch_id": r.get("batch_id", ""),
                            "status_before": before[id(r)],
                            "status_after": r.get("status", ""),
                        })

                if any_unused:
                    result["outcome"] = OUTCOME_GENERATED_BEFORE
                    result["message"] = MSG_GENERATED_BEFORE
                else:
                    result["outcome"] = OUTCOME_ALREADY_CHECKED
                    result["message"] = MSG_ALREADY_CHECKED
                results.append(result)

        counts = {OUTCOME_GENERATED_BEFORE: 0, OUTCOME_ALREADY_CHECKED: 0, OUTCOME_NOT_FOUND: 0}
        for r in results:
            counts[r["outcome"]] += 1
        return {"results": results, "counts": counts, "files": self.summary()["files"]}

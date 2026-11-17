"""Booty's local web server (Python standard library only).

Start:   python3 -m booty  [--port 8777] [--data-dir PATH] [--no-browser]
Open:    http://127.0.0.1:8777

The server only listens on 127.0.0.1, so it is reachable from this computer
only, never from the network.

Endpoints:
    GET  /                 The web page (booty/static/index.html).
    GET  /static/<file>    CSS / JavaScript / images of the page.
    GET  /api/status       Summary of the reference files (names, counts, errors).
    POST /api/check        Check codes. JSON body:
                               {
                                 "use_text": true|false,
                                 "text": "CODE1, CODE2",           # used if use_text
                                 "use_pdf": true|false,
                                 "pdfs": [{"name": "x.pdf",        # used if use_pdf; one or more
                                           "data_base64": "..."}, ...]
                               }
                               (a single "pdf": {...} object is still accepted)
                           Response: ReferenceStore.check() output plus
                               "pdfs": [{"name", "pages", "type", "codes_found"} | {"name", "error"}, ...]
                                       (type = "kit_insert" | "lab_report", see pdf_codes.py)
                               "warnings": [str, ...]
                           Errors: HTTP 400 {"error": "..."}.
"""

import argparse
import base64
import binascii
import json
import mimetypes
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import pdf_codes
from .reference_store import ReferenceStore

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(PACKAGE_DIR, "static")
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(PACKAGE_DIR), "existing_access_codes")
DEFAULT_PORT = 8777

# Upload limit for the JSON body (PDFs are base64-encoded, ~1.33x their size),
# i.e. roughly 75 MB of PDFs per check, and at most MAX_PDFS files.
MAX_BODY_BYTES = 100 * 1024 * 1024
MAX_PDFS = 200

# Typed codes may be separated by commas, semicolons, whitespace or new lines.
TYPED_SEPARATORS = re.compile(r"[,;\s]+")


def parse_typed_codes(text):
    """Split the text box content into individual codes.

    Args:
        text: Raw text, e.g. "abc234xyz, ABC234XYZ;KLM567PQR".

    Returns:
        list[str]: Non-empty tokens in input order (not yet normalised).
    """
    return [t for t in TYPED_SEPARATORS.split(text or "") if t]


class BootyHandler(BaseHTTPRequestHandler):
    """Handles one HTTP request. A new instance is created per request by http.server.

    Class attributes (set once in main()):
        store: The shared ReferenceStore used by every request.
    """

    store = None
    server_version = "Booty/1.0"

    # ---------- helpers ----------

    def _send_json(self, payload, status=200):
        """Serialise `payload` as JSON and send it with the given HTTP status."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        """Send a static file; responds 404 if it does not exist or lies outside STATIC_DIR."""
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(real):
            self.send_error(404)
            return
        with open(real, "rb") as fh:
            body = fh.read()
        ctype = mimetypes.guess_type(real)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Shorter console log line than the http.server default."""
        print(f"[booty] {self.address_string()} {fmt % args}")

    # ---------- routes ----------

    def do_GET(self):
        """Serve the page, static assets and /api/status."""
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_file(os.path.join(STATIC_DIR, "index.html"))
        elif path.startswith("/static/"):
            self._send_file(os.path.join(STATIC_DIR, path[len("/static/"):]))
        elif path == "/api/status":
            self._send_json(self.store.summary())
        else:
            self.send_error(404)

    def do_POST(self):
        """Handle /api/check (see module docstring for the request format)."""
        if self.path.split("?", 1)[0] != "/api/check":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json({"error": "Request is empty or too large (max ~75 MB of PDFs per check)."}, 400)
            return
        try:
            request = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "Invalid request."}, 400)
            return

        try:
            response = self.handle_check(request)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json(response)

    @staticmethod
    def collect_pdf_codes(pdfs, items, warnings):
        """Read several uploaded PDFs and add their codes to `items`.

        Every PDF is processed on its own: a damaged or unreadable file adds a
        warning (and an entry with "error") but does not stop the other files.

        Duplicate detection across ALL uploaded PDFs:
            * kit insert: the same code on two pages (of one file or of
              different files) -> warning;
            * lab report: the same access code under two different kit IDs
              (in one file or across files) -> warning. The same sample ID in
              two files (e.g. the same report uploaded twice) -> warning;
            * a code that also appears in a second file is merged by
              ReferenceStore.check() (listed once, with all its sources).

        Args:
            pdfs: list of {"name": str, "data_base64": str} from the request.
            items: list to append (code, [sources]) tuples to (modified in place).
            warnings: list to append user-facing warning strings to (modified in place).

        Returns:
            list[dict]: One entry per PDF, in upload order:
                {"name", "pages", "type", "codes_found"} or {"name", "error"}.

        Raises:
            ValueError: If NONE of the PDFs could be read.
        """
        infos = []
        seen = {}  # code -> {"places": ["file p.1", ...], "sample_ids": {sid: [file, ...]}}

        for pdf in pdfs:
            name = str(pdf.get("name") or "uploaded.pdf")
            try:
                pdf_bytes = base64.b64decode(pdf["data_base64"], validate=True)
                extracted = pdf_codes.extract_codes(pdf_bytes)
            except (binascii.Error, ValueError):
                infos.append({"name": name, "error": "upload was damaged"})
                warnings.append(f"{name}: the upload was damaged, please add it again.")
                continue
            except pdf_codes.PdfError as exc:
                infos.append({"name": name, "error": str(exc)})
                warnings.append(f"{name}: {exc}.")
                continue

            infos.append({
                "name": name,
                "pages": extracted["pages"],
                "type": extracted["type"],
                "codes_found": len(extracted["codes"]),
            })
            for sid in extracted["unsupported_ids"]:
                warnings.append(f"{name}: lab report ID {sid} – the part after '_' is not a 9-character "
                                f"access code, so it cannot be checked.")
            if not extracted["codes"] and not extracted["unsupported_ids"]:
                warnings.append(f"{name}: no access codes found (is it a scanned image?).")

            for entry in extracted["codes"]:
                code, pages, sample_ids = entry["code"], entry["pages"], entry["sample_ids"]
                pages_txt = ", ".join(map(str, pages))
                info = seen.setdefault(code, {"places": [], "sample_ids": {}})
                if extracted["type"] == pdf_codes.TYPE_LAB_REPORT:
                    # Lab report: the sample ID repeats on several pages, that is normal.
                    sources = [f"Lab report {sid} – {name} (page {pages_txt})" for sid in sample_ids]
                    for sid in sample_ids:
                        info["sample_ids"].setdefault(sid, []).append(name)
                    info["places"].append(name)
                else:
                    sources = [f"{name} – page {p}" for p in pages]
                    info["places"].extend(f"{name} page {p}" for p in pages)
                items.append((code, sources))

        # Cross-file duplicate warnings (computed once all PDFs are read).
        for code, info in seen.items():
            if len(info["sample_ids"]) > 1:
                warnings.append(f"{code} is used by more than one kit ID: {', '.join(info['sample_ids'])}.")
            for sid, files in info["sample_ids"].items():
                if len(files) > 1:
                    warnings.append(f"Sample {sid} is in more than one uploaded PDF: {', '.join(files)}.")
            if not info["sample_ids"] and len(info["places"]) > 1:
                warnings.append(f"{code} appears more than once: {', '.join(info['places'])}.")

        if all("error" in i for i in infos):
            raise ValueError("None of the PDFs could be read: " + " ".join(warnings))
        return infos

    def handle_check(self, request):
        """Collect codes from the selected methods and run the reference check.

        Args:
            request: Parsed JSON body of /api/check.

        Returns:
            dict: Response payload (see module docstring).

        Raises:
            ValueError: With a user-facing message for invalid input
                (no method selected, no codes, unreadable PDF...).
        """
        use_text = bool(request.get("use_text"))
        use_pdf = bool(request.get("use_pdf"))
        if not use_text and not use_pdf:
            raise ValueError("Please tick at least one method: upload a PDF or type codes.")

        items = []      # (code, [sources]) for ReferenceStore.check
        warnings = []
        pdf_infos = []

        if use_pdf:
            # "pdfs" is a list; a single "pdf" object (older page version) is accepted too.
            pdfs = request.get("pdfs")
            if pdfs is None and request.get("pdf"):
                pdfs = [request["pdf"]]
            pdfs = [p for p in (pdfs or []) if isinstance(p, dict) and p.get("data_base64")]
            if not pdfs:
                raise ValueError("'Upload PDF' is ticked but no PDF was chosen.")
            if len(pdfs) > MAX_PDFS:
                raise ValueError(f"Please upload at most {MAX_PDFS} PDFs at once.")
            pdf_infos = self.collect_pdf_codes(pdfs, items, warnings)

        if use_text:
            typed = parse_typed_codes(request.get("text", ""))
            if not typed and not use_pdf:
                raise ValueError("'Type codes' is ticked but the text box is empty.")
            for code in typed:
                items.append((code, ["typed"]))

        if not items and not warnings:
            raise ValueError("No codes to check.")
        # With warnings but no codes (e.g. an old-format lab report) we still
        # return a normal (empty) report so the page can show the warnings.

        report = self.store.check(items)
        report["pdfs"] = pdf_infos
        report["warnings"] = warnings
        return report


def main():
    """Parse command-line options, create the ReferenceStore and run the server until Ctrl+C."""
    parser = argparse.ArgumentParser(description="Booty - local access-code checker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="folder with the reference .xlsx/.csv files (default: existing_access_codes)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    if not os.path.isdir(args.data_dir):
        parser.error(f"reference folder not found: {args.data_dir}")

    BootyHandler.store = ReferenceStore(args.data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), BootyHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Booty is running at {url}  (reference folder: {BootyHandler.store.data_dir})")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBooty stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

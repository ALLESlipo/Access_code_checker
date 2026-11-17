"""Booty - local access-code checker for mimatest kits.

Package layout (see docs/BOOTY_DOCUMENTATION.md for the full description):

    booty/xlsx_io.py          Read and update .xlsx files using only the Python standard library.
    booty/reference_store.py  Loads every reference file (.xlsx/.csv) and performs the code check.
    booty/pdf_codes.py        Extracts access codes from an uploaded PDF.
    booty/server.py           Local HTTP server: serves the web page and the JSON API.
    booty/static/             The web page (HTML, CSS, JavaScript incl. the voiced tutorial).

Run with:  python3 -m booty   (or ./run_booty.sh)
"""

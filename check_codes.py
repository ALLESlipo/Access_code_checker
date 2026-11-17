#!/usr/bin/env python3
"""Check whether mimatest access codes have already been used.

A code counts as "used" when it appears in a report filename under the
report_generator output folder (e.g. mimatest_KIT000011111_de-DE.pdf),
including files inside .zip archives.

Usage:
    check_codes.py CODE [CODE ...]        check specific codes
    check_codes.py -f codes.txt           check codes from a file (one per line / any separators)
    echo "CODE1 CODE2" | check_codes.py -  check codes from stdin
    check_codes.py --report               list codes generated in more than one output folder
    check_codes.py --list                 list every known code
Options:
    --root PATH   output folder to scan (default: ../report_generator/output)
    --json        machine-readable output
"""
import argparse
import json
import os
import re
import sys
import zipfile
from collections import defaultdict

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "report_generator", "output")
CODE_RE = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9]{10,16}$")
LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def codes_in_name(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    parts = stem.split("_")
    codes = [p for p in parts if CODE_RE.match(p)]
    locale = next((p for p in parts if LOCALE_RE.match(p)), None)
    return codes, locale


def build_index(root):
    """Return {code: [ {folder, file, locale} ... ]}."""
    index = defaultdict(list)
    for dirpath, _, files in os.walk(root):
        folder = os.path.relpath(dirpath, root)
        for f in files:
            names = [(f, f)]
            if f.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(os.path.join(dirpath, f)) as z:
                        names += [(n, f"{f}!{n}") for n in z.namelist() if not n.endswith("/")]
                except zipfile.BadZipFile:
                    pass
            for name, shown in names:
                codes, locale = codes_in_name(name)
                for c in codes:
                    index[c].append({"folder": folder, "file": shown, "locale": locale})
    return index


def one_char_off(a, b):
    """True if a and b differ by exactly one inserted/deleted character.

    Single-character substitutions are NOT flagged: codes are issued in
    sequences (KIT000011111, KIT000011112, ...) so those are normal.
    """
    la, lb = len(a), len(b)
    if abs(la - lb) != 1:
        return False
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def summarize(hits):
    folders = sorted({h["folder"] for h in hits})
    locales = sorted({h["locale"] for h in hits if h["locale"]})
    return {"folders": folders, "locales": locales, "files": len(hits)}


def parse_codes(raw):
    return [t.upper() for t in re.split(r"[\s,;]+", raw) if t.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("codes", nargs="*", help="codes to check, or '-' for stdin")
    ap.add_argument("-f", "--file", help="file containing codes")
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--report", action="store_true", help="codes found in more than one output folder")
    ap.add_argument("--list", action="store_true", help="list all known codes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.exit(f"Output folder not found: {root}")
    index = build_index(root)

    if args.list or args.report:
        rows = {c: summarize(h) for c, h in sorted(index.items())}
        if args.report:
            rows = {c: s for c, s in rows.items() if len(s["folders"]) > 1}
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            label = "used in multiple folders" if args.report else "known codes"
            print(f"{len(rows)} {label} (scanned {root})")
            for c, s in rows.items():
                print(f"  {c}  folders={len(s['folders'])} files={s['files']}  {', '.join(s['folders'])}")
        return

    raw = " ".join(c for c in args.codes if c != "-")
    if "-" in args.codes:
        raw += " " + sys.stdin.read()
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            raw += " " + fh.read()
    queries = parse_codes(raw)
    if not queries:
        ap.error("no codes given (pass codes, -f FILE, '-' for stdin, --report or --list)")

    seen_in_input = defaultdict(int)
    for q in queries:
        seen_in_input[q] += 1

    results = []
    for q in dict.fromkeys(queries):  # unique, keep order
        hits = index.get(q, [])
        similar = sorted(c for c in index if one_char_off(q, c))
        results.append({
            "code": q,
            "status": "USED" if hits else "NEW",
            "repeated_in_input": seen_in_input[q] > 1,
            "valid_format": bool(CODE_RE.match(q)),
            **summarize(hits),
            "similar_known_codes": similar,
        })

    if args.json:
        print(json.dumps({"root": root, "known_codes": len(index), "results": results}, indent=2))
        return

    used = sum(r["status"] == "USED" for r in results)
    print(f"Scanned {len(index)} known codes in {root}")
    print(f"Checked {len(results)} codes: {used} USED, {len(results) - used} NEW\n")
    for r in results:
        line = f"{r['status']:4}  {r['code']}"
        if r["status"] == "USED":
            line += f"  ({r['files']} files; locales {', '.join(r['locales']) or '-'}; folders {', '.join(r['folders'])})"
        flags = []
        if r["repeated_in_input"]:
            flags.append("listed more than once in input")
        if not r["valid_format"]:
            flags.append("unusual format")
        if r["similar_known_codes"]:
            flags.append("similar to " + ", ".join(r["similar_known_codes"]))
        if flags:
            line += "  ⚠ " + "; ".join(flags)
        print(line)
    sys.exit(1 if used else 0)


if __name__ == "__main__":
    main()

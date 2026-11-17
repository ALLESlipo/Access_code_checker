# Booty: Access Code Checker

This AI agent checks whether we have already used certain access codes from the mimatest.

Booty is a local web page. You give it codes, either by uploading a kit-insert PDF (the default) or by typing them
separated by commas. Booty looks for each code in **every** Excel/CSV export in `existing_access_codes/`:

| Result | Meaning |
|---|---|
| **Code already generated before** | The code was in the export as *Not Used*. Booty marks it as **Used** in the file. |
| **Code already checked and exists** | The code was already *Used*; it stays *Used*. |
| **Code not found in the reference files** | The code isn't in any export. |

## Start

```bash
./run_booty.sh        # opens http://127.0.0.1:8777
```

On the first visit, Booty's voiced tutorial explains everything. You can reopen it with the **Tutorial** button and mute
the voice with 🔊.

Full technical documentation: [docs/BOOTY_DOCUMENTATION.md](docs/BOOTY_DOCUMENTATION.md)

## Legacy

`check_codes.py` and `.claude/agents/access-code-checker.md` are an earlier tool. They look for codes in the
**report_generator output filenames** (IDs like `KIT000011111`), not in the access-code exports.

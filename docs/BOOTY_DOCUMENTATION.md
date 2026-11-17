# Booty: Technical Documentation

Booty is a local web tool that checks mimatest **access codes** against the reference exports in
`existing_access_codes/`. When a code is found for the first time, Booty marks it as **Used** in the reference file,
so the same code can't be handed out twice.

- **Runs locally only.** The server listens on `127.0.0.1` and can't be reached from the network.
- **No installation needed.** Booty uses only the Python 3 standard library plus the `pdftotext` command, which is already installed.
- **Tutorial included.** A voiced, step-by-step popup in Booty's own voice. The voice is on by default and can be muted.

---

## 1. Starting Booty

```bash
cd /home/cts/Git/src/Access_Code_checker
./run_booty.sh                 # same as: python3 -m booty
```

This starts the server and opens <http://127.0.0.1:8777> in the browser. Press **Ctrl+C** in the terminal to stop it.

| Option | Default | Meaning |
|---|---|---|
| `--port N` | `8777` | Port of the local web server |
| `--data-dir PATH` | `existing_access_codes/` | Folder holding the reference `.xlsx` / `.csv` files |
| `--no-browser` | off | Don't open the browser automatically |

**Requirements:** Python ≥ 3.8 and `pdftotext` from the `poppler-utils` package (`sudo apt install poppler-utils` if it's
missing). Use a recent Chrome, Edge or Firefox for the voice.

---

## 2. How to use it (user view)

1. **Choose the method** with the checkboxes:
   - **Upload PDFs** is ticked by default. Drop **one or more** PDFs on the box or click to choose them.
     - You can add more in several rounds. The chosen files are listed below the box, and each has a **×** to remove it
       (or use **Remove all**).
     - The same file (same name and size) isn't added twice.
     - Limits per check: up to 200 PDFs and about 75 MB in total.
     - Each file's type is detected separately, so kit inserts and lab reports can be mixed
       (see [PDF types](#pdf-types)):
     - **Kit insert** (like `testpdf.pdf`): one access code per page.
     - **Lab report** (like `KIT000012345_XYZ789ABC.pdf`): Booty takes the sample ID `KIT000012345_XYZ789ABC` and
       checks the part after the underscore, `XYZ789ABC`.
   - **Type codes**: type or paste codes separated by commas. Spaces, semicolons and new lines also work, and case doesn't matter.
   - Both can be ticked at once, and all codes are then checked together.
2. Click **Check codes**.
3. Read the result for each code:

| Result | When | What Booty does to the file |
|---|---|---|
| 🔴 **Code already generated before** | The code is in a reference file with status *Not Used* | Sets `used = t` and `status = Used` in **every** reference file that contains it |
| 🟠 **Code already checked and exists** | The code is in a reference file and is already *Used* | Nothing; it stays *Used* |
| ⚪ **Code not found in the reference files** | The code is in no reference file | Nothing. If a known code differs by one character, Booty shows *"Did you mean …?"* |

Booty also adds these notes:
- One info line per PDF: its name, its type, the number of pages and the number of codes found.
- A PDF that can't be read (damaged, not a PDF) is reported by name. The other PDFs are still checked.
- The code was entered more than once in the same check. It's processed once.
- Kit insert: the code appears more than once, on several pages or in several uploaded PDFs.
- Lab report: the same access code appears under two different kit IDs, even across different uploaded PDFs.
- Lab report: the same sample ID appears in more than one uploaded PDF, for example the same report uploaded twice.
- Lab report: the part after `_` isn't a 9-character access code (older reports such as
  `KIT000067890_0000AAAA1111BBBB`), so it can't be checked.
- The code has an unusual format (not 9 characters).
- A reference file was skipped (unreadable, or missing a required column).

The header shows how many codes and used codes the reference files contain. Hover over it to see each file.

---

## 3. The rules in detail

- **Code normalisation:** surrounding spaces are removed and the code is upper-cased (`qrs234tuv` becomes `QRS234TUV`).
- **Which rows count as used:** a row is *used* if `status` is `Used` **or** `used` is `t` / `true` / `1` / `yes`.
- **More than one file:** a code is looked up in all reference files.
  - If at least one matching row is still *Not Used*, the result is "generated before" and all unused matching rows are marked.
  - If every matching row is already *Used*, the result is "already checked".
- **Duplicates in one check:** a code entered twice, or found in the PDF and typed, is processed once. The result lists all its sources.
- **Checking again:** a code that was marked in an earlier check is already *Used*, so it always returns
  "Code already checked and exists" afterwards, whichever method is used.

---

## 4. Reference files (`existing_access_codes/`)

- Every `*.xlsx` and `*.csv` file directly in this folder is used. Adding a new export is enough, with no restart needed,
  because the files are re-read on every check.
- Ignored:
  - Sub-folders.
  - Hidden files, such as `.booty_backups/` and LibreOffice lock files `.~lock…#`.
  - Office temp files `~$…`.
  - Any other file type.
- **Columns:** all files must use the same columns as the original export:

  ```
  id, code, generated_by, created_at, used, status, batch_id, printed_at
  ```

  `code`, `used` and `status` are required; a file without them is skipped and a warning is shown.
  `batch_id` is displayed in the results when it's there.
- **.xlsx:** only the **first sheet** is read, and its **first row** is the header.
- **.csv:** the delimiter (`,` `;` or tab) and the line endings are detected and kept when the file is written back.
  The file must be UTF-8 (a BOM is fine).

### Backups

Before Booty changes a reference file for the first time after it starts, it saves a copy to
`existing_access_codes/.booty_backups/<file name>.<YYYYmmdd-HHMMSS>.bak`. To undo changes, stop Booty and copy a backup back
over the file. You can delete old backups whenever you like.

> Close the reference file in Excel/LibreOffice while checking. Booty saves straight to disk, and saving the file from an
> office program that still has the old version open would overwrite Booty's changes.

---

## 5. Architecture

```
Access_Code_checker/
├── run_booty.sh                 start script (python3 -m booty)
├── existing_access_codes/       reference exports (.xlsx/.csv) + .booty_backups/ (not in git)
├── testpdf.pdf                  sample kit-insert PDF (local only, not in git)
├── docs/BOOTY_DOCUMENTATION.md  this file
└── booty/
    ├── __init__.py              package overview
    ├── __main__.py              entry point → server.main()
    ├── server.py                HTTP server + JSON API
    ├── reference_store.py       loading reference files + check rules + marking codes Used
    ├── xlsx_io.py               stdlib .xlsx reader / in-place cell writer
    ├── pdf_codes.py             PDF → text (pdftotext) → access codes
    └── static/
        ├── index.html           page structure
        ├── style.css            styling (light + dark mode, mobile)
        └── app.js               UI logic, voice, tutorial
```

### Request flow

```
Browser (app.js)                         server.py                     reference_store.py / pdf_codes.py
────────────────                         ─────────                     ─────────────────────────────────
Check codes ──POST /api/check──────────► handle_check()
  {use_pdf, pdf:{base64}, use_text, text}   ├─ PDF → pdf_codes.extract_codes() → [(code, pages)]
                                            ├─ text → parse_typed_codes()      → [code]
                                            └─ ReferenceStore.check(items)
                                                 ├─ re-read all .xlsx/.csv
                                                 ├─ per code: find rows, decide outcome
                                                 ├─ backup file (first change only)
                                                 └─ mark_used() → xlsx_io.update_cells() / CSV rewrite
render(results) ◄──────── JSON ──────────┘
Voice.speak(summary)
```

### Modules

**`booty/server.py`**
- `BootyHandler` serves `/`, `/static/*`, `GET /api/status` and `POST /api/check`.
- `handle_check()` gathers the codes from the selected methods, validates the input with clear error messages, and calls the store.
- `collect_pdf_codes()` reads each uploaded PDF on its own. An unreadable file becomes a warning instead of stopping
  the check. Once every file is read, it warns about duplicates across files: the same code in several files, the same
  code under different kit IDs, or the same sample ID in two files.
- Static files are only served from `booty/static`; paths that try to leave that folder get a 404.
- The request body is limited to 100 MB (`MAX_BODY_BYTES`), which allows about 75 MB of PDFs. A check can include
  at most 200 PDFs (`MAX_PDFS`).

**`booty/reference_store.py`**
- `ReferenceFile` is one loaded `.xlsx` or `.csv` file. It provides `load()`, `find(code)` and `mark_used(rows)`; `_write_csv()` saves CSV files.
- `ReferenceStore` finds the files (`_discover`), makes the backups (`_backup`), produces the header summary (`summary`), and implements the rules (`check`).
- All checks run under one lock, so two browser tabs can't write the same file at the same time.
- The message texts and the values written to the file are constants at the top of the file:
  `MSG_*`, `USED_FLAG_VALUE = "t"` and `USED_STATUS_VALUE = "Used"`.

**`booty/xlsx_io.py`**
- `read_first_sheet()` reads the sheet using the shared strings, inline strings, booleans and numbers.
- `update_cells()` changes only the requested cells in the sheet XML and copies every other part of the archive unchanged.
  - The changed cells keep their style and are written as inline strings.
  - The file is written to a temporary file first and then swapped in with an atomic rename.
  - Tested: LibreOffice opens the modified export correctly.

**`booty/pdf_codes.py`**
- `pdf_to_pages()` runs `pdftotext -layout` and splits the output into pages at the form-feed character.
- `codes_from_pages()` detects the PDF type and extracts the codes (see [PDF types](#pdf-types)).
- `extract_codes()` combines the two and adds the page count.
- Words that only look like codes can be added to `IGNORE_WORDS`.
- Scanned PDFs, which contain only images, contain no text; Booty then warns that no codes were found.

<a id="pdf-types"></a>
#### PDF types

| Type | Example | How it's recognised | What is checked |
|---|---|---|---|
| `lab_report` | `KIT000012345_XYZ789ABC.pdf` (IAT lab result, Russian) | The text contains a sample ID `<kit ID>_<code>`: a 10–14 character kit ID, `_`, then a 9-character access code (`SAMPLE_ID_PATTERN`) | Only the part after `_`. The rest of the report is ignored, so lab values and species names are never taken for codes. |
| `kit_insert` | `testpdf.pdf` | No sample ID is found | Every 9-character token from the code alphabet (`2-9`, `A-Z` without `I`/`O`), counted once per page (each code is printed 3 times per page) |

How lab reports are handled:
- The sample ID appears on several pages of one report (pages 1 and 2). That's normal and isn't reported as a duplicate.
- A merged PDF with several reports gives one code per sample ID.
- The same access code under two **different** kit IDs is reported as a warning.
- Older reports have a 16-character part after `_`, for example `KIT000067890_0000AAAA1111BBBB` (`OTHER_SAMPLE_ID_PATTERN`).
  They're recognised as lab reports and reported as *"not a 9-character access code"*, and nothing is checked.
- Tested against every PDF in `report_generator/input/`. All lab reports gave exactly their one code; the
  16-character ones gave the warning.

**`booty/static/app.js`**
- `Store`: wraps localStorage in try/catch. It remembers whether the voice is on and whether the tutorial has been seen.
- `Voice`: Web Speech API (see section 6).
  - On by default; the header button toggles it and the choice is remembered.
  - The voice dropdown (`refresh()` fills it) lets the user pick and preview any English voice.
  - `pickVoice()` with "Auto" chooses a female voice that is **not** the one Botty uses (`bottyVoice()`).
- `Tour`: the 7 tutorial steps.
  - Each step has a `title`, popup text (`html`), spoken text (`say`) and an element to highlight (`target`).
  - It opens automatically on the first visit and later through the **Tutorial** button.
  - It has Back/Next/Replay buttons, and Esc or the × closes it.
- `Checker`: the method checkboxes, drag-and-drop or file picker, input validation, the `fetch` call, results rendering
  and the spoken summary.
- `renderRefSummary()`: the reference-file info in the header.

### API reference

`GET /api/status`

```json
{"folder": "/…/existing_access_codes",
 "files": [{"name": "access_codes_export_2026-11-17.xlsx", "codes": 3000, "used": 3, "error": null}]}
```

`POST /api/check`

Request:

```json
{"use_pdf": true,  "pdfs": [{"name": "testpdf.pdf", "data_base64": "JVBERi0x…"},
                            {"name": "KIT000012345_XYZ789ABC.pdf", "data_base64": "JVBERi0x…"}],
 "use_text": true, "text": "QRS234TUV, TUV567WXY"}
```

Response (abridged):

```json
{"counts": {"generated_before": 1, "already_checked": 1, "not_found": 2},
 "results": [
   {"code": "QRS234TUV", "outcome": "generated_before", "message": "Code already generated before",
    "sources": ["typed"], "times_in_input": 1, "format_warning": false, "suggestions": [],
    "matches": [{"file": "access_codes_export_2026-11-17.xlsx", "row": 2, "batch_id": "2",
                 "status_before": "Not Used", "status_after": "Used"}]},
   {"code": "ABC234XYZ", "outcome": "not_found", "message": "Code not found in the reference files",
    "sources": ["PDF page 1"], "matches": [], "suggestions": []}
 ],
 "pdfs": [{"name": "testpdf.pdf", "pages": 2, "type": "kit_insert", "codes_found": 2},
          {"name": "KIT000012345_XYZ789ABC.pdf", "pages": 6, "type": "lab_report", "codes_found": 1}],
 "warnings": [],
 "files": [ …same as /api/status… ]}
```

Errors come back as HTTP 400 with `{"error": "<message for the user>"}`.

---

## 6. Tutorial and voice

- The tutorial text is written in Booty's own voice: friendly, first person, like a woman of about 20.
  The text is in `Tour.steps` in `app.js`; edit `html` for the popup text and `say` for the spoken version.
- The voice is **on by default**. Users who only want to read the popup can click 🔊 in the header to mute it.
  The choice is remembered in that browser.
- **Different from Botty.** Botty (`Upload_tests_AI_agent`) uses the first British-English voice at a high pitch of 1.6.
  Booty's voice differs in three ways:
  - With **Voice: Auto**, she prefers American-English female voices.
  - She skips Botty's voice whenever any other English voice is installed.
  - She speaks lower and calmer: pitch 0.95, rate 0.95.
- **Voice picker.** The dropdown next to 🔊 lists every English voice the browser offers.
  - Choosing one plays a short sample and remembers the choice; **Auto** goes back to the rules above.
  - Chrome and Edge usually offer more and better voices than Firefox on Linux.
- Booty uses only the voices installed in the browser or OS. It can't imitate a specific real person's voice.
- Browsers block speech until the user has clicked or typed something on the page. On the very first load the
  welcome step may therefore be silent. **Replay** or **Next** starts the voice.
- After every check Booty speaks a short summary, for example "All done! 1 code was already generated before, I marked it as used."

---

## 7. Extending Booty

| Task | Where |
|---|---|
| Add a new reference export | Drop the `.xlsx`/`.csv` (same columns) into `existing_access_codes/`. That's all. |
| Change a result message | `MSG_*` in `reference_store.py`, then the tutorial text in `app.js` |
| Change what is written when a code is marked | `USED_FLAG_VALUE`, `USED_STATUS_VALUE` in `reference_store.py` |
| A new PDF layout produces false codes | Add the word to `IGNORE_WORDS` in `pdf_codes.py` |
| Codes get a different length/alphabet | `CODE_PATTERN` in `pdf_codes.py`, `CODE_FORMAT_RE` in `reference_store.py` |
| Prefer another voice | Users: the voice dropdown. Default: `Voice.PREFERRED_NAMES`, `PITCH`, `RATE` in `app.js` |
| Support another PDF type | Add a pattern and a branch in `codes_from_pages()` in `pdf_codes.py`, a source label in `server.handle_check()`, and the type name in `Checker.render()` (`app.js`) |
| Add a tutorial step | Add an object to `Tour.steps` in `app.js` |
| Translate the tutorial | Duplicate `Tour.steps` per language and choose by `navigator.language` |

### Testing without touching the real data

Copy the reference files to a temporary folder and point Booty at it:

```bash
mkdir /tmp/booty-test && cp existing_access_codes/*.xlsx /tmp/booty-test/
python3 -m booty --data-dir /tmp/booty-test --port 8799
```

---

## 8. Known limitations

- Only the first sheet of an `.xlsx` is used.
- Scanned (image-only) PDFs aren't supported, because that would need OCR.
- The voice depends on the voices installed on the computer or in the browser. On some Linux setups only robotic
  voices are available.
- Booty is meant for one person or a few people on the same computer. It isn't a multi-user server.

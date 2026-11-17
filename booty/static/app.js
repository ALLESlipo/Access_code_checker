/*
 * Booty - front-end logic.
 *
 * Sections of this file:
 *   1. Store      - safe wrapper around localStorage (remembers voice on/off and
 *                   whether the tutorial was already shown).
 *   2. Voice      - Booty's spoken voice (browser built-in speech synthesis,
 *                   female English voice, ON by default, toggle in the header).
 *   3. Tour       - the tutorial popup: steps written in Booty's voice, each
 *                   step is shown as text AND read aloud while the voice is on.
 *   4. Checker    - the form: method checkboxes (PDF ticked by default), PDF
 *                   upload, typed codes, calling POST /api/check, rendering
 *                   the results.
 *   5. Startup    - wires everything together when the page loads.
 *
 * No libraries / build step: plain browser JavaScript, served by booty/server.py.
 */
"use strict";

/* ===================================================================== */
/* 1. Store                                                               */
/* ===================================================================== */

/**
 * Tiny wrapper around localStorage.
 * localStorage can throw (private mode, blocked storage); every access is
 * wrapped so the page keeps working with defaults when storage is unavailable.
 */
const Store = {
  /**
   * Read a value.
   * @param {string} key      Storage key (prefixed with "booty." automatically).
   * @param {string} fallback Returned when the key is missing or storage fails.
   * @returns {string}
   */
  get(key, fallback) {
    try {
      const v = window.localStorage.getItem("booty." + key);
      return v === null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  },
  /**
   * Save a value; failures are ignored (the setting simply isn't remembered).
   * @param {string} key
   * @param {string} value
   */
  set(key, value) {
    try { window.localStorage.setItem("booty." + key, value); } catch (e) { /* ignore */ }
  },
};

/* ===================================================================== */
/* 2. Voice                                                               */
/* ===================================================================== */

/**
 * Booty's voice, built on the Web Speech API (window.speechSynthesis).
 *
 * - The voice is ON by default. The choice is remembered per browser.
 * - Booty must NOT sound like Botty (Upload_tests_AI_agent). Botty uses the
 *   first British-English (en-GB) voice with a high, chirpy pitch (1.6).
 *   Booty therefore:
 *     * prefers American-English female voices (PREFERRED_NAMES),
 *     * skips the voice Botty would pick (bottyVoice()) whenever another
 *       English voice exists,
 *     * speaks lower and calmer (PITCH 0.95, RATE 0.95): a smooth, confident
 *       young woman instead of a cheerful robot.
 * - Voice picker: the <select id="voice-select"> in the header lists all
 *   English voices installed in the browser/OS. "Auto" uses the rules above;
 *   choosing a voice remembers it (Store key "voiceName") and plays a sample.
 *   Which voices exist depends on the browser and operating system.
 * - Browsers only allow speech after the user has interacted with the page
 *   (a click/key press). Before that, speak() calls are silently ignored by
 *   the browser; the tutorial's first step therefore has a "Replay" button.
 */
const Voice = {
  /** Female voices tried first, in order (American English first, to differ from Botty). */
  PREFERRED_NAMES: [
    "Google US English", "Microsoft Ava", "Microsoft Jenny", "Microsoft Aria", "Microsoft Michelle",
    "Microsoft Zira", "Samantha", "Ava", "Allison", "Susan", "Karen", "Tessa", "Moira",
    "Microsoft Sonia", "Microsoft Libby", "Google UK English Female",
  ],
  /** Name fragments that indicate a female voice (e.g. Linux "English (America)+female2"). */
  FEMALE_HINT: /female|woman|girl|aria|jenny|zira|michelle|libby|sonia|hazel|susan|samantha|karen|tessa|moira|fiona|victoria|serena|ava|allison|emma|amy|joanna|salli|kendra|kimberly/i,
  /** Lower and slower than Botty (pitch 1.6, rate 1.05): smooth and confident. */
  PITCH: 0.95,
  RATE: 0.95,
  SAMPLE_TEXT: "Hey, I'm Booty. This is how I'll sound while I check your codes.",

  enabled: true,
  voice: null,
  supported: "speechSynthesis" in window,

  /**
   * Load the saved settings, pick a voice and connect the header controls.
   * Voices load asynchronously in some browsers, hence onvoiceschanged.
   */
  init() {
    this.enabled = Store.get("voice", "on") === "on";
    this.button = document.getElementById("voice-toggle");
    this.select = document.getElementById("voice-select");
    this.button.addEventListener("click", () => this.setEnabled(!this.enabled));
    this.select.addEventListener("change", () => {
      Store.set("voiceName", this.select.value);
      this.pickVoice();
      if (!this.enabled) this.setEnabled(true); // choosing a voice implies wanting to hear it
      this.speak(this.SAMPLE_TEXT);
    });
    if (this.supported) {
      this.refresh();
      window.speechSynthesis.onvoiceschanged = () => this.refresh();
    } else {
      this.enabled = false;
      this.button.disabled = true;
      this.select.hidden = true;
      this.button.title = "This browser cannot speak – the tutorial is text only";
    }
    this.renderButton();
  },

  /** All English voices the browser offers. @returns {SpeechSynthesisVoice[]} */
  englishVoices() {
    return window.speechSynthesis.getVoices().filter((v) => /^en([-_]|$)/i.test(v.lang));
  },

  /**
   * The voice Botty would use (first en-GB voice, else first English voice),
   * replicating Upload_tests_AI_agent's pickVoice(). Booty avoids it.
   * @returns {SpeechSynthesisVoice|undefined}
   */
  bottyVoice() {
    const voices = window.speechSynthesis.getVoices();
    return voices.find((v) => /^en[-_]GB/i.test(v.lang)) || voices.find((v) => /^en/i.test(v.lang));
  },

  /** Rebuild the voice dropdown and re-pick the voice (called when the voice list changes). */
  refresh() {
    const english = this.englishVoices();
    const saved = Store.get("voiceName", "auto");
    this.select.innerHTML = "";
    this.select.append(new Option("Voice: Auto", "auto"));
    english.forEach((v) => this.select.append(new Option(`${v.name} (${v.lang})`, v.name)));
    this.select.value = english.some((v) => v.name === saved) ? saved : "auto";
    this.select.hidden = english.length === 0;
    this.pickVoice();
  },

  /**
   * Choose the voice: the one picked in the dropdown, otherwise "Auto":
   * preferred female names, then any female-sounding English voice, then any
   * English voice, always skipping Botty's voice when possible.
   */
  pickVoice() {
    const english = this.englishVoices();
    const chosen = this.select.value;
    if (chosen && chosen !== "auto") {
      this.voice = english.find((v) => v.name === chosen) || null;
      if (this.voice) return;
    }
    const botty = this.bottyVoice();
    const candidates = english.filter((v) => v !== botty);
    const pool = candidates.length ? candidates : english;
    this.voice =
      this.PREFERRED_NAMES.map((n) => pool.find((v) => v.name.startsWith(n))).find(Boolean) ||
      pool.find((v) => this.FEMALE_HINT.test(v.name)) ||
      pool[0] ||
      null;
  },

  /**
   * Turn the voice on or off, remember it and update the button.
   * Turning it off stops any sentence currently being spoken.
   * @param {boolean} on
   */
  setEnabled(on) {
    this.enabled = on;
    Store.set("voice", on ? "on" : "off");
    if (!on) this.stop();
    this.renderButton();
  },

  /** Reflect the current state in the header button (icon, label, aria-pressed). */
  renderButton() {
    this.button.setAttribute("aria-pressed", String(this.enabled));
    this.button.querySelector(".icon").textContent = this.enabled ? "🔊" : "🔇";
    this.button.querySelector(".label").textContent = this.enabled ? "Voice on" : "Voice off";
    this.button.title = this.enabled ? "Booty's voice is on – click to mute" : "Booty's voice is off – click to turn it on";
  },

  /**
   * Speak a text (if the voice is on). Anything still being spoken is cut off
   * first, so clicking through the tutorial never queues up old sentences.
   * @param {string} text Plain text, without emoji/markup.
   */
  speak(text) {
    if (!this.enabled || !this.supported || !text) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    if (this.voice) { u.voice = this.voice; u.lang = this.voice.lang; } else { u.lang = "en-US"; }
    u.pitch = this.PITCH;
    u.rate = this.RATE;
    window.speechSynthesis.speak(u);
  },

  /** Stop speaking immediately. */
  stop() {
    if (this.supported) window.speechSynthesis.cancel();
  },
};

/* ===================================================================== */
/* 3. Tour (tutorial popup)                                               */
/* ===================================================================== */

/**
 * The tutorial. Each step has:
 *   title  - heading in the popup
 *   html   - text shown in the popup (Booty speaking in first person)
 *   say    - what Booty reads aloud (same message, written for the ear:
 *            no emoji, codes not spelled out)
 *   target - CSS selector of the page element to highlight (optional; the
 *            first visible match of a comma-separated list is used)
 *
 * The tour opens automatically on the first visit and can be reopened at any
 * time with the "Tutorial" button in the header.
 */
const Tour = {
  steps: [
    {
      title: "Hey, I'm Booty! 👋",
      html: "<p>I check access codes for you, so we never hand out the same code twice.</p>" +
            "<p>Let me show you around, it takes less than a minute. Click <b>Next</b> to start!</p>",
      say: "Hey, I'm Booty! I check access codes for you, so we never hand out the same code twice. " +
           "Let me show you around, it takes less than a minute. Click next to start!",
    },
    {
      title: "Pick how you want to check",
      target: "#methods",
      html: "<p>Up here you've got two checkboxes. <b>Upload PDF</b> is ticked by default, because that's what you'll use most.</p>" +
            "<p>Tick <b>Type codes</b> if you'd rather type or paste them. You can even tick both and I'll check everything together!</p>",
      say: "Up here you've got two checkboxes. Upload PDF is ticked by default, because that's what you'll use most. " +
           "Tick type codes if you'd rather type or paste them. You can even tick both, and I'll check everything together!",
    },
    {
      title: "Uploading PDFs",
      target: "#pdf-section, #methods",
      html: "<p>Drop your PDFs on the dashed box, or click it to pick them. One file or a whole bunch at once, both are fine! " +
            "Changed your mind? Click the <b>×</b> next to a file to take it off the list.</p>" +
            "<p>I understand two kinds:</p>" +
            "<p>📄 <b>Kit inserts</b>: I grab the access code from every page.<br>" +
            "🧪 <b>Lab reports</b>: I find the sample ID, like <code>KIT000012345_XYZ789ABC</code>, and check the part after the underscore, <code>XYZ789ABC</code>.</p>" +
            "<p>I figure out which kind it is all by myself.</p>",
      say: "Drop your PDFs on the dashed box, or click it to pick them. One file or a whole bunch at once, both are fine! " +
           "Changed your mind? Click the little cross next to a file to take it off the list. I understand two kinds. " +
           "Kit inserts: I grab the access code from every page. " +
           "And lab reports: I find the sample ID and check the part after the underscore. " +
           "I figure out which kind it is all by myself.",
    },
    {
      title: "Typing codes",
      target: "#text-section, #methods",
      html: "<p>With <b>Type codes</b> ticked, a text box shows up. Put your codes in and separate them with commas, like <code>ABC234XYZ, KLM567PQR</code>.</p>" +
            "<p>Capital letters or not, I don't mind.</p>",
      say: "With type codes ticked, a text box shows up. Put your codes in and separate them with commas. " +
           "Capital letters or not, I don't mind.",
    },
    {
      title: "Let me check!",
      target: ".actions",
      html: "<p>Hit <b>Check codes</b> and I'll look for every code in <i>all</i> the Excel and CSV files in the <code>existing_access_codes</code> folder, including new ones you add later.</p>",
      say: "Hit check codes, and I'll look for every code in all the Excel and CSV files in the existing access codes folder, including new ones you add later.",
    },
    {
      title: "What my answers mean",
      target: "#results-card",
      html: "<p>For every code you get one of these:</p>" +
            "<div class='legend'>" +
            "<span><span class='pill generated_before'>Code already generated before</span><span class='note'>I found it and it was still <i>Not Used</i>. I mark it as <b>Used</b> in the file right away.</span></span>" +
            "<span><span class='pill already_checked'>Code already checked and exists</span><span class='note'>Someone checked it before; it stays <b>Used</b>.</span></span>" +
            "<span><span class='pill not_found'>Code not found in the reference files</span><span class='note'>It's not in any file. If it looks like a typo, I'll suggest the closest code.</span></span>" +
            "</div>",
      say: "For every code, you get one of three answers. Code already generated before: I found it, and it was still not used, so I mark it as used in the file right away. " +
           "Code already checked and exists: someone checked it before, and it stays used. " +
           "And code not found: it's not in any file. If it looks like a typo, I'll suggest the closest code.",
    },
    {
      title: "That's it, you're ready! 🎉",
      target: ".topbar-actions",
      html: "<p>I talk you through things with my voice. Prefer to just read? Click the <b>speaker button</b> up top to mute me. " +
            "Want me to sound different? Pick another voice from the <b>Voice</b> list next to it.</p>" +
            "<p>Need this tour again? Click <b>Tutorial</b>. Have fun checking!</p>",
      say: "I talk you through things with my voice. Prefer to just read? Click the speaker button up top to mute me. " +
           "Want me to sound different? Pick another voice from the voice list next to it. " +
           "Need this tour again? Click tutorial. Have fun checking!",
    },
  ],

  index: 0,

  /** Cache DOM elements and connect the popup buttons. */
  init() {
    this.el = document.getElementById("tour");
    this.backdrop = document.getElementById("tour-backdrop");
    this.titleEl = document.getElementById("tour-title");
    this.bodyEl = document.getElementById("tour-body");
    this.progressEl = document.getElementById("tour-progress");
    this.backBtn = document.getElementById("tour-back");
    this.nextBtn = document.getElementById("tour-next");
    document.getElementById("tour-close").addEventListener("click", () => this.close());
    document.getElementById("tour-replay").addEventListener("click", () => Voice.speak(this.steps[this.index].say));
    this.backBtn.addEventListener("click", () => this.show(this.index - 1));
    this.nextBtn.addEventListener("click", () => {
      if (this.index < this.steps.length - 1) this.show(this.index + 1);
      else this.close();
    });
    this.backdrop.addEventListener("click", () => this.close());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.el.hidden) this.close();
    });
  },

  /** Open the tutorial at the first step. */
  open() {
    this.el.hidden = false;
    this.backdrop.hidden = false;
    this.show(0);
  },

  /** Close the tutorial, stop the voice, remember that it has been seen. */
  close() {
    this.el.hidden = true;
    this.backdrop.hidden = true;
    this.clearHighlight();
    Voice.stop();
    Store.set("tutorialSeen", "yes");
  },

  /**
   * Display one step: fill title/text, update buttons, highlight its target
   * element and read the step aloud.
   * @param {number} i Step index (clamped to the valid range).
   */
  show(i) {
    this.index = Math.max(0, Math.min(i, this.steps.length - 1));
    const step = this.steps[this.index];
    this.titleEl.textContent = step.title;
    this.bodyEl.innerHTML = step.html; // static, trusted text defined above
    this.progressEl.textContent = `${this.index + 1} / ${this.steps.length}`;
    this.backBtn.disabled = this.index === 0;
    this.nextBtn.textContent = this.index === this.steps.length - 1 ? "Done" : "Next";
    this.highlight(step.target);
    Voice.speak(step.say);
    this.nextBtn.focus({ preventScroll: true });
  },

  /**
   * Highlight the first visible element matching one of the selectors.
   * @param {string|undefined} selectors Comma-separated CSS selectors.
   */
  highlight(selectors) {
    this.clearHighlight();
    if (!selectors) return;
    const el = selectors.split(",")
      .map((s) => document.querySelector(s.trim()))
      .find((e) => e && e.offsetParent !== null);
    if (!el) return;
    el.classList.add("tour-highlight");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  },

  /** Remove the highlight from whatever element currently has it. */
  clearHighlight() {
    document.querySelectorAll(".tour-highlight").forEach((e) => e.classList.remove("tour-highlight"));
  },
};

/* ===================================================================== */
/* 4. Checker (form + results)                                            */
/* ===================================================================== */

/**
 * Escape text for safe insertion into HTML (codes and file names come from
 * user input / files and must never be interpreted as markup).
 * @param {*} value
 * @returns {string}
 */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Labels for the result counters, in display order. Keys = outcome ids from the server. */
const OUTCOMES = [
  ["generated_before", "already generated before (now marked Used)"],
  ["already_checked", "already checked"],
  ["not_found", "not found"],
];

/**
 * Everything about the check form and the results table.
 * State: `pdfFiles` holds the File objects chosen for upload (one or more).
 * Files can be added in several rounds (choose / drop again); a file with the
 * same name and size as one already in the list is ignored.
 */
const Checker = {
  pdfFiles: [],

  /** Cache elements and attach all event listeners. */
  init() {
    this.usePdf = document.getElementById("use-pdf");
    this.useText = document.getElementById("use-text");
    this.pdfSection = document.getElementById("pdf-section");
    this.textSection = document.getElementById("text-section");
    this.textStep = document.getElementById("text-step");
    this.dropzone = document.getElementById("dropzone");
    this.dropzoneText = document.getElementById("dropzone-text");
    this.fileInput = document.getElementById("pdf-input");
    this.fileListWrap = document.getElementById("file-list-wrap");
    this.fileList = document.getElementById("file-list");
    this.fileCount = document.getElementById("file-count");
    this.codesInput = document.getElementById("codes-input");
    this.checkBtn = document.getElementById("check-btn");
    this.errorEl = document.getElementById("form-error");

    this.usePdf.addEventListener("change", () => this.updateSections());
    this.useText.addEventListener("change", () => this.updateSections());
    this.fileInput.addEventListener("change", () => {
      this.addFiles(this.fileInput.files);
      this.fileInput.value = ""; // allow choosing the same file again after removing it
    });
    document.getElementById("clear-files").addEventListener("click", () => {
      this.pdfFiles = [];
      this.renderFiles();
    });
    // One listener for all "×" buttons in the list (event delegation).
    this.fileList.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-index]");
      if (!btn) return;
      this.pdfFiles.splice(Number(btn.dataset.index), 1);
      this.renderFiles();
    });
    this.dropzone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.fileInput.click(); }
    });
    ["dragenter", "dragover"].forEach((t) => this.dropzone.addEventListener(t, (e) => {
      e.preventDefault(); this.dropzone.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach((t) => this.dropzone.addEventListener(t, (e) => {
      e.preventDefault(); this.dropzone.classList.remove("dragover");
    }));
    this.dropzone.addEventListener("drop", (e) => this.addFiles(e.dataTransfer.files));
    this.checkBtn.addEventListener("click", () => this.submit());
    // Ctrl/Cmd+Enter in the text box runs the check.
    this.codesInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) this.submit();
    });
    this.updateSections();
  },

  /**
   * Show the PDF and/or text input depending on the ticked checkboxes, and
   * number the steps ("2 · Upload", "3 · Type") when both are visible.
   */
  updateSections() {
    this.pdfSection.hidden = !this.usePdf.checked;
    this.textSection.hidden = !this.useText.checked;
    this.textStep.textContent = this.usePdf.checked ? "3" : "2";
    this.errorEl.textContent = "";
  },

  /**
   * Add chosen/dropped files to the upload list.
   * Non-PDF files are skipped (with a message); files already in the list
   * (same name + size) are not added twice.
   * @param {FileList|File[]} files
   */
  addFiles(files) {
    const skipped = [];
    for (const file of Array.from(files || [])) {
      const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
      if (!isPdf) { skipped.push(file.name); continue; }
      const dup = this.pdfFiles.some((f) => f.name === file.name && f.size === file.size);
      if (!dup) this.pdfFiles.push(file);
    }
    this.renderFiles();
    this.errorEl.textContent = skipped.length ? `Skipped (not a PDF): ${skipped.join(", ")}` : "";
  },

  /** Show the list of chosen PDFs with a remove button each, and update the drop zone text. */
  renderFiles() {
    const n = this.pdfFiles.length;
    this.fileListWrap.hidden = n === 0;
    this.dropzone.classList.toggle("has-file", n > 0);
    this.dropzoneText.innerHTML = n
      ? "Drop more PDFs here or <u>click to add files</u>"
      : "Drop one or more PDFs here or <u>click to choose files</u>";
    const totalKb = Math.ceil(this.pdfFiles.reduce((s, f) => s + f.size, 0) / 1024);
    this.fileCount.textContent = `${n} PDF${n === 1 ? "" : "s"} selected (${totalKb.toLocaleString()} KB)`;
    this.fileList.innerHTML = this.pdfFiles.map((f, i) =>
      `<li><span aria-hidden="true">📄</span><span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>` +
      `<span class="fsize">${Math.ceil(f.size / 1024)} KB</span>` +
      `<button class="remove" type="button" data-index="${i}" aria-label="Remove ${esc(f.name)}">×</button></li>`
    ).join("");
  },

  /**
   * Read a File as base64 (without the "data:...;base64," prefix).
   * @param {File} file
   * @returns {Promise<string>}
   */
  readBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.onerror = () => reject(new Error("Could not read the file."));
      reader.readAsDataURL(file);
    });
  },

  /**
   * Validate the form, send it to POST /api/check and render the answer.
   * Validation messages mirror the server's, so the user gets instant
   * feedback without a round-trip.
   */
  async submit() {
    const usePdf = this.usePdf.checked;
    const useText = this.useText.checked;
    const text = this.codesInput.value.trim();
    this.errorEl.textContent = "";

    if (!usePdf && !useText) return this.fail("Please tick at least one method: Upload PDF or Type codes.");
    if (usePdf && !this.pdfFiles.length) return this.fail("'Upload PDF' is ticked – please choose at least one PDF first.");
    if (useText && !usePdf && !text) return this.fail("'Type codes' is ticked – please type at least one code.");

    this.checkBtn.disabled = true;
    this.checkBtn.textContent = "Checking…";
    try {
      const payload = { use_pdf: usePdf, use_text: useText, text };
      if (usePdf) {
        payload.pdfs = await Promise.all(this.pdfFiles.map(async (f) => ({
          name: f.name,
          data_base64: await this.readBase64(f),
        })));
      }
      const res = await fetch("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({ error: "Booty's server sent an unreadable answer." }));
      if (!res.ok || data.error) return this.fail(data.error || `Server error (${res.status}).`);
      this.render(data);
      renderRefSummary(data.files);
    } catch (e) {
      this.fail("Can't reach Booty's server. Is it still running in the terminal?");
    } finally {
      this.checkBtn.disabled = false;
      this.checkBtn.textContent = "Check codes";
    }
  },

  /**
   * Show an error message under the button and have Booty say it.
   * @param {string} message
   */
  fail(message) {
    this.errorEl.textContent = message;
    Voice.speak(message.replace(/'/g, ""));
  },

  /**
   * Render the /api/check response: counters, warnings and one table row per code.
   * @param {object} data Response from the server (see booty/server.py).
   */
  render(data) {
    const card = document.getElementById("results-card");
    card.hidden = false;

    document.getElementById("counters").innerHTML = OUTCOMES
      .map(([key, label]) => `<span class="counter ${key}"><b>${data.counts[key]}</b>${label}</span>`)
      .join("");

    const warnings = [...(data.warnings || [])];
    // One info line per readable PDF (unreadable ones already have a warning from the server).
    const pdfLines = (data.pdfs || []).filter((p) => !p.error).map((p) => {
      const kind = p.type === "lab_report" ? "lab report" : "kit insert";
      return `Read ${p.name} (${kind}, ${p.pages} page${p.pages === 1 ? "" : "s"}) – found ${p.codes_found} code${p.codes_found === 1 ? "" : "s"}.`;
    });
    warnings.unshift(...pdfLines);
    (data.files || []).filter((f) => f.error).forEach((f) => warnings.push(`Skipped ${f.name}: ${f.error}`));
    document.getElementById("warnings").innerHTML = warnings.map((w) => `<li>${esc(w)}</li>`).join("");

    const tbody = document.querySelector("#results-table tbody");
    tbody.innerHTML = data.results.map((r) => this.rowHtml(r)).join("") ||
      `<tr><td colspan="4" class="detail">No codes to show.</td></tr>`;

    card.scrollIntoView({ behavior: "smooth", block: "start" });
    Voice.speak(this.spokenSummary(data.counts));
  },

  /**
   * Build the HTML of one result row.
   * @param {object} r One entry of data.results.
   * @returns {string}
   */
  rowHtml(r) {
    const notes = [];
    if (r.times_in_input > 1) notes.push(`Entered ${r.times_in_input}× in this check`);
    if (r.format_warning) notes.push("Unusual format (normal codes have 9 characters)");
    if (r.suggestions.length) notes.push(`Did you mean ${r.suggestions.map(esc).join(", ")}?`);

    const where = r.matches.length
      ? r.matches.map((m) =>
          `<div>${esc(m.file)} · row ${esc(m.row)}${m.batch_id ? ` · batch ${esc(m.batch_id)}` : ""} · ` +
          (m.status_before === m.status_after ? esc(m.status_after) : `${esc(m.status_before)} → <b>${esc(m.status_after)}</b>`) +
          `</div>`).join("")
      : "–";

    return `<tr>
      <td class="code">${esc(r.code)}</td>
      <td><span class="pill ${esc(r.outcome)}">${esc(r.message)}</span>${notes.map((n) => `<span class="note">⚠ ${n}</span>`).join("")}</td>
      <td class="detail">${r.sources.map(esc).join("<br>")}</td>
      <td class="detail">${where}</td>
    </tr>`;
  },

  /**
   * Short sentence Booty says after a check, e.g.
   * "All done! 1 code was already generated before, I marked it as used. 2 codes weren't found."
   * @param {{generated_before:number, already_checked:number, not_found:number}} c
   * @returns {string}
   */
  spokenSummary(c) {
    const n = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
    const parts = [];
    if (c.generated_before) parts.push(`${n(c.generated_before, "code")} ${c.generated_before === 1 ? "was" : "were"} already generated before, I marked ${c.generated_before === 1 ? "it" : "them"} as used`);
    if (c.already_checked) parts.push(`${n(c.already_checked, "code")} ${c.already_checked === 1 ? "was" : "were"} already checked`);
    if (c.not_found) parts.push(`${n(c.not_found, "code")} ${c.not_found === 1 ? "wasn't" : "weren't"} found`);
    return "All done! " + (parts.join(". ") || "There was nothing to check") + ".";
  },
};

/**
 * Show "N codes in M file(s)" in the header (tooltip lists the files).
 * @param {Array<{name:string, codes:number, used:number, error:?string}>} files
 */
function renderRefSummary(files) {
  const el = document.getElementById("ref-summary");
  if (!files) return;
  const ok = files.filter((f) => !f.error);
  const total = ok.reduce((s, f) => s + f.codes, 0);
  const used = ok.reduce((s, f) => s + f.used, 0);
  el.textContent = ok.length
    ? `${total.toLocaleString()} codes · ${used.toLocaleString()} used · ${ok.length} file${ok.length === 1 ? "" : "s"}`
    : "No reference files found";
  el.title = files.map((f) => `${f.name}: ${f.error ? f.error : `${f.codes} codes, ${f.used} used`}`).join("\n");
}

/* ===================================================================== */
/* 5. Startup                                                             */
/* ===================================================================== */

/**
 * Initialise all parts, load the reference-file summary and open the
 * tutorial automatically on the first visit.
 */
function start() {
  Voice.init();
  Tour.init();
  Checker.init();
  document.getElementById("help-btn").addEventListener("click", () => Tour.open());

  fetch("/api/status")
    .then((r) => r.json())
    .then((d) => renderRefSummary(d.files))
    .catch(() => { document.getElementById("ref-summary").textContent = "Server not reachable"; });

  if (Store.get("tutorialSeen", "no") !== "yes") Tour.open();
}

document.addEventListener("DOMContentLoaded", start);

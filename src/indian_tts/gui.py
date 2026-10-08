# -*- coding: utf-8 -*-
"""Tkinter user interface."""

import csv
import json
import os
import queue
import random
import shutil
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

from .config import (APP_NAME, CATEGORIES, CATEGORY_LABELS, DEFAULT_SETTINGS, ENGLISH_ACCENTS,
                     LANG_KEYS, LANGUAGES, PROJECT_FORMAT, SAMPLE_CONTENT, TARGET_LANGS)
from .content import (content_to_entries, entries_to_content, entry_status, export_python_dicts,
                      load_python_dicts, merge_entries, natural_key, new_entry, normalize_category,
                      read_csv_entries, slugify, write_csv_entries)
from .pipeline import (build_jobs, convert_to_wav, ffmpeg_available, folder_size, gTTS,
                       load_manifest, output_base, read_failed_csv, run_pipeline)
from .playback import find_ffplay, open_folder, play_audio
from .translation import translate_text


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def fmt_secs(s):
    s = int(s)
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1200x780")
        self.minsize(1000, 640)

        self.entries = []
        self.project_path = None
        self.dirty = False
        self.current = None          # entry dict shown in the editor
        self.by_iid = {}             # treeview iid -> entry dict
        self._loading = False
        self.events = queue.Queue()  # worker threads -> UI thread
        self.cancel_event = threading.Event()
        self.busy = False
        self.last_failed = None
        self.run_stats = {}

        self._setup_style()
        self._build_vars()
        self._build_menu()
        self._build_ui()
        self.refresh_tree()
        self.load_entry(None)
        self.update_title()
        self.after(100, self._poll_events)
        self.after(300, self.check_tools)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- setup ----------
    def _setup_style(self):
        style = ttk.Style(self)
        if sys.platform.startswith("linux") and "clam" in style.theme_names():
            style.theme_use("clam")
        base = tkfont.nametofont("TkDefaultFont")
        size = max(10, abs(base.cget("size")))
        family = "Nirmala UI" if os.name == "nt" else base.cget("family")  # Indic glyphs on Windows
        self.text_font = tkfont.Font(family=family, size=size + 1)
        self.bold_font = tkfont.Font(family=base.cget("family"), size=size, weight="bold")
        self.title_font = tkfont.Font(family=base.cget("family"), size=size + 3, weight="bold")
        style.configure("Treeview", rowheight=int(self.text_font.metrics("linespace") * 1.5))
        style.configure("Treeview", font=self.text_font)
        style.configure("Accent.TButton", font=self.bold_font)
        style.configure("Hint.TLabel", foreground="#6b6b6b")
        style.configure("Warn.TLabel", foreground="#b3261e")
        style.configure("Good.TLabel", foreground="#1e7a3c")

    def _build_vars(self):
        d = DEFAULT_SETTINGS
        self.v_output = tk.StringVar(value=d["output_dir"])
        self.v_ffmpeg = tk.StringVar(value=d["ffmpeg"])
        self.v_rate = tk.StringVar(value=str(d["sample_rate"]))
        self.v_channels = tk.StringVar(value="Mono")
        self.v_workers = tk.StringVar(value=str(d["workers"]))
        self.v_dmin = tk.StringVar(value=str(d["delay_min"]))
        self.v_dmax = tk.StringVar(value=str(d["delay_max"]))
        self.v_retries = tk.StringVar(value=str(d["retries"]))
        self.v_accent = tk.StringVar(value=dict(ENGLISH_ACCENTS)[d["english_tld"]])
        self.v_keep_mp3 = tk.BooleanVar(value=d["keep_mp3"])
        self.v_skip = tk.BooleanVar(value=d["skip_unchanged"])
        self.v_organize = tk.BooleanVar(value=d["organize"])
        self.v_test = tk.BooleanVar(value=d["test_run"])
        self.v_test_n = tk.StringVar(value=str(d["test_n"]))
        self.v_device = tk.StringVar(value=str(d["device_mb"]))
        self.v_langs = {l: tk.BooleanVar(value=True) for l in LANG_KEYS}
        self.v_cats = {c: tk.BooleanVar(value=True) for c in CATEGORIES}
        for var in [self.v_rate, self.v_channels, self.v_test, self.v_test_n, self.v_device,
                    *self.v_langs.values(), *self.v_cats.values()]:
            var.trace_add("write", lambda *_: self.update_estimate())
        self._applying = False
        for var in [self.v_output, self.v_ffmpeg, self.v_rate, self.v_channels, self.v_workers,
                    self.v_dmin, self.v_dmax, self.v_retries, self.v_accent, self.v_keep_mp3,
                    self.v_skip, self.v_organize, self.v_test, self.v_test_n, self.v_device,
                    *self.v_langs.values(), *self.v_cats.values()]:
            var.trace_add("write", lambda *_: None if self._applying else self.mark_dirty())
        # editor
        self.v_filter = tk.StringVar(value="All")
        self.v_search = tk.StringVar()
        self.v_cat = tk.StringVar()
        self.v_id = tk.StringVar()
        self.v_reviewed = tk.BooleanVar()
        self.v_preview_lang = tk.StringVar(value="Hindi")
        self.v_status = tk.StringVar(value="Ready.")
        self.v_filter.trace_add("write", lambda *_: self.refresh_tree())
        self.v_search.trace_add("write", lambda *_: self.refresh_tree())
        self.v_cat.trace_add("write", lambda *_: self.update_filename_hint())
        self.v_id.trace_add("write", lambda *_: self.update_filename_hint())

    def _build_menu(self):
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=False)
        m_file.add_command(label="New project", command=self.new_project, accelerator="Ctrl+N")
        m_file.add_command(label="Open project…", command=self.open_project, accelerator="Ctrl+O")
        m_file.add_command(label="Save project", command=self.save_project, accelerator="Ctrl+S")
        m_file.add_command(label="Save project as…", command=lambda: self.save_project(True))
        m_file.add_separator()
        m_file.add_command(label="Import Python dictionaries (.py)…", command=self.import_py)
        m_file.add_command(label="Import CSV…", command=self.import_csv)
        m_file.add_command(label="Export CSV for review…", command=self.export_csv)
        m_file.add_command(label="Export Python dictionaries (.py)…", command=self.export_py)
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=m_file)

        m_tools = tk.Menu(menubar, tearoff=False)
        m_tools.add_command(label="Translate all missing fields", command=self.translate_all_missing)
        m_tools.add_command(label="Add counting numbers…", command=self.add_numbers)
        m_tools.add_command(label="Load sample content", command=self.load_sample)
        m_tools.add_separator()
        m_tools.add_command(label="Check gTTS & FFmpeg", command=lambda: self.check_tools(verbose=True))
        menubar.add_cascade(label="Tools", menu=m_tools)

        m_help = tk.Menu(menubar, tearoff=False)
        m_help.add_command(label="How it works", command=self.show_help)
        menubar.add_cascade(label="Help", menu=m_help)
        self.config(menu=menubar)

        self.bind_all("<Control-s>", lambda e: self.save_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-n>", lambda e: self.new_project())

    def _build_ui(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.tab_content = ttk.Frame(self.nb, padding=8)
        self.tab_generate = ttk.Frame(self.nb, padding=8)
        self.nb.add(self.tab_content, text="  1 · Content & translations  ")
        self.nb.add(self.tab_generate, text="  2 · Generate audio  ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._build_content_tab()
        self._build_generate_tab()

        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.v_status).pack(side="left")
        self.lbl_ffmpeg = ttk.Label(bar, text="FFmpeg: …")
        self.lbl_ffmpeg.pack(side="right", padx=(12, 0))
        self.lbl_gtts = ttk.Label(bar, text="gTTS: …")
        self.lbl_gtts.pack(side="right", padx=(12, 0))
        self.lbl_count = ttk.Label(bar, text="")
        self.lbl_count.pack(side="right")

    # ---------- content tab ----------
    def _build_content_tab(self):
        pane = ttk.PanedWindow(self.tab_content, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane)
        right = ttk.Frame(pane, padding=(10, 0, 0, 0))
        pane.add(left, weight=3)
        pane.add(right, weight=2)

        top = ttk.Frame(left)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Category").pack(side="left")
        self.cmb_filter = ttk.Combobox(top, textvariable=self.v_filter, state="readonly", width=14)
        self.cmb_filter.pack(side="left", padx=(4, 12))
        ttk.Label(top, text="Search").pack(side="left")
        ttk.Entry(top, textvariable=self.v_search, width=24).pack(side="left", padx=4, fill="x", expand=True)

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        cols = ("category", "id", "english", "langs", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        heads = {"category": ("Category", 80), "id": ("ID", 95), "english": ("English text", 200),
                 "langs": ("Langs", 48), "status": ("Status", 120)}
        for c in cols:
            title, width = heads[c]
            self.tree.heading(c, text=title, command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=width, stretch=(c == "english"),
                             anchor="center" if c == "langs" else "w")
        self.tree.tag_configure("missing", foreground="#b3261e")
        self.tree.tag_configure("review", foreground="#9a6700")
        self.tree.tag_configure("ok", foreground="#1e7a3c")
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self.delete_entries())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="+ Add entry", command=self.add_entry).pack(side="left")
        ttk.Button(btns, text="Duplicate", command=self.duplicate_entry).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete", command=self.delete_entries).pack(side="left")
        ttk.Button(btns, text="Translate all missing", command=self.translate_all_missing).pack(side="right")

        # editor
        ttk.Label(right, text="Entry", font=self.title_font).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(right, text="Category").grid(row=1, column=0, sticky="w", pady=(8, 2))
        self.cmb_cat = ttk.Combobox(right, textvariable=self.v_cat, values=CATEGORIES, width=14)
        self.cmb_cat.grid(row=1, column=1, sticky="w", pady=(8, 2))
        ttk.Label(right, text="ID").grid(row=1, column=2, sticky="e", padx=(10, 4), pady=(8, 2))
        self.ent_id = ttk.Entry(right, textvariable=self.v_id, width=16)
        self.ent_id.grid(row=1, column=3, sticky="ew", pady=(8, 2))
        self.lbl_filename = ttk.Label(right, text="", style="Hint.TLabel")
        self.lbl_filename.grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 6))

        self.text_widgets = {}
        row = 3
        for lang in LANG_KEYS:
            name = LANGUAGES[lang][0]
            label = name if lang != "sanskrit" else "Sanskrit\n(Hindi voice)"
            ttk.Label(right, text=label, font=self.bold_font if lang == "english" else None,
                      justify="left").grid(row=row, column=0, sticky="nw", pady=3)
            txt = tk.Text(right, height=3 if lang == "english" else 2, width=36, wrap="word", undo=True,
                          font=self.text_font, relief="solid", borderwidth=1,
                          highlightthickness=1, padx=6, pady=4)
            txt.grid(row=row, column=1, columnspan=3, sticky="ew", pady=3)
            txt.bind("<Tab>", self._focus_next)
            txt.bind("<Shift-Tab>", self._focus_prev)
            self.text_widgets[lang] = txt
            row += 1

        self.chk_reviewed = ttk.Checkbutton(right, text="Translations reviewed by a native speaker",
                                            variable=self.v_reviewed)
        self.chk_reviewed.grid(row=row, column=1, columnspan=3, sticky="w", pady=(4, 8))
        row += 1

        actions = ttk.Frame(right)
        actions.grid(row=row, column=0, columnspan=4, sticky="ew")
        self.btn_apply = ttk.Button(actions, text="Apply changes", style="Accent.TButton",
                                    command=lambda: self.commit_form(force_refresh=True))
        self.btn_apply.pack(side="left")
        self.btn_tr_missing = ttk.Button(actions, text="Translate empty fields",
                                         command=lambda: self.translate_current(False))
        self.btn_tr_missing.pack(side="left", padx=4)
        self.btn_tr_all = ttk.Button(actions, text="Re-translate all",
                                     command=lambda: self.translate_current(True))
        self.btn_tr_all.pack(side="left")
        row += 1

        prev = ttk.Frame(right)
        prev.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Label(prev, text="Listen:").pack(side="left")
        ttk.Combobox(prev, textvariable=self.v_preview_lang, state="readonly", width=10,
                     values=[LANGUAGES[l][0] for l in LANG_KEYS]).pack(side="left", padx=4)
        self.btn_preview = ttk.Button(prev, text="▶ Preview speech", command=self.preview)
        self.btn_preview.pack(side="left")
        row += 1

        ttk.Label(right, style="Hint.TLabel", justify="left", wraplength=420,
                  text="Machine translation is a first draft. Have a native speaker check "
                       "each entry (export CSV → review → import CSV), then tick 'reviewed'. "
                       "Sanskrit has no gTTS voice, so it is spoken by the Hindi voice."
                  ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(14, 0))
        right.columnconfigure(3, weight=1)
        right.columnconfigure(1, weight=0)
        self.editor_widgets = [self.cmb_cat, self.ent_id, self.chk_reviewed, self.btn_apply,
                               self.btn_tr_missing, self.btn_tr_all, self.btn_preview]

    def _focus_next(self, event):
        event.widget.tk_focusNext().focus_set()
        return "break"

    def _focus_prev(self, event):
        event.widget.tk_focusPrev().focus_set()
        return "break"

    # ---------- generate tab ----------
    def _build_generate_tab(self):
        tab = self.tab_generate
        top = ttk.Frame(tab)
        top.pack(fill="x")

        col1 = ttk.Frame(top)
        col1.pack(side="left", fill="both", expand=True)
        col2 = ttk.Frame(top, padding=(12, 0, 0, 0))
        col2.pack(side="left", fill="both", expand=True)

        out = ttk.LabelFrame(col1, text="Output", padding=8)
        out.pack(fill="x")
        ttk.Label(out, text="Output folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(out, textvariable=self.v_output).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(out, text="Browse…", command=self.choose_output).grid(row=0, column=2)
        ttk.Label(out, text="FFmpeg").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(out, textvariable=self.v_ffmpeg).grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
        ttk.Button(out, text="Browse…", command=self.choose_ffmpeg).grid(row=1, column=2, pady=(6, 0))
        ttk.Checkbutton(out, text="Organise into wav/<category>/<language>/ folders",
                        variable=self.v_organize).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        out.columnconfigure(1, weight=1)

        fmt = ttk.LabelFrame(col1, text="WAV format (for the embedded device)", padding=8)
        fmt.pack(fill="x", pady=(8, 0))
        ttk.Label(fmt, text="Sample rate").grid(row=0, column=0, sticky="w")
        ttk.Combobox(fmt, textvariable=self.v_rate, width=8,
                     values=["8000", "16000", "22050", "44100"]).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(fmt, text="Hz").grid(row=0, column=2, sticky="w")
        ttk.Label(fmt, text="Channels").grid(row=0, column=3, sticky="w", padx=(16, 0))
        ttk.Combobox(fmt, textvariable=self.v_channels, width=7, state="readonly",
                     values=["Mono", "Stereo"]).grid(row=0, column=4, sticky="w", padx=4)
        ttk.Label(fmt, text="Codec: 16-bit PCM (pcm_s16le)", style="Hint.TLabel").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ttk.Label(fmt, text="English accent").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(fmt, textvariable=self.v_accent, state="readonly", width=26,
                     values=[label for _, label in ENGLISH_ACCENTS]).grid(
            row=2, column=1, columnspan=4, sticky="w", padx=4, pady=(6, 0))

        perf = ttk.LabelFrame(col1, text="Speed & reliability", padding=8)
        perf.pack(fill="x", pady=(8, 0))
        ttk.Label(perf, text="Worker threads").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(perf, from_=1, to=32, textvariable=self.v_workers, width=5).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(perf, text="Retries").grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Spinbox(perf, from_=1, to=10, textvariable=self.v_retries, width=4).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(perf, text="Delay per request").grid(row=1, column=0, sticky="w", pady=(6, 0))
        dl = ttk.Frame(perf)
        dl.grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Spinbox(dl, from_=0, to=5, increment=0.1, textvariable=self.v_dmin, width=5).pack(side="left", padx=4)
        ttk.Label(dl, text="to").pack(side="left")
        ttk.Spinbox(dl, from_=0, to=5, increment=0.1, textvariable=self.v_dmax, width=5).pack(side="left", padx=4)
        ttk.Label(dl, text="seconds (random, avoids throttling)").pack(side="left")
        ttk.Checkbutton(perf, text="Keep MP3 backups (re-convert later without calling gTTS again)",
                        variable=self.v_keep_mp3).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Checkbutton(perf, text="Skip files whose text hasn't changed",
                        variable=self.v_skip).grid(row=3, column=0, columnspan=4, sticky="w")

        what = ttk.LabelFrame(col2, text="What to generate", padding=8)
        what.pack(fill="x")
        ttk.Label(what, text="Languages", font=self.bold_font).grid(row=0, column=0, sticky="w")
        for i, lang in enumerate(LANG_KEYS):
            ttk.Checkbutton(what, text=LANGUAGES[lang][0], variable=self.v_langs[lang]).grid(
                row=1 + i // 3, column=i % 3, sticky="w", padx=(0, 12))
        ttk.Label(what, text="Categories", font=self.bold_font).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.cat_frame = ttk.Frame(what)
        self.cat_frame.grid(row=4, column=0, columnspan=3, sticky="w")
        self.refresh_category_checks()

        test = ttk.LabelFrame(col2, text="Test run & storage", padding=8)
        test.pack(fill="x", pady=(8, 0))
        tr = ttk.Frame(test)
        tr.pack(fill="x")
        ttk.Checkbutton(tr, text="Test run: only the first", variable=self.v_test).pack(side="left")
        ttk.Spinbox(tr, from_=1, to=50, textvariable=self.v_test_n, width=4).pack(side="left", padx=4)
        ttk.Label(tr, text="entries → <output>/_test_run").pack(side="left")
        dv = ttk.Frame(test)
        dv.pack(fill="x", pady=(6, 0))
        ttk.Label(dv, text="Device storage").pack(side="left")
        ttk.Spinbox(dv, from_=0, to=1_000_000, increment=64, textvariable=self.v_device, width=8).pack(side="left", padx=4)
        ttk.Label(dv, text="MB  (0 = don't check)").pack(side="left")
        self.lbl_estimate = ttk.Label(test, text="", justify="left", wraplength=430)
        self.lbl_estimate.pack(fill="x", pady=(6, 0))

        run = ttk.Frame(tab)
        run.pack(fill="x", pady=(10, 4))
        self.btn_start = ttk.Button(run, text="▶ Generate audio", style="Accent.TButton",
                                    command=lambda: self.start_generation("all"))
        self.btn_start.pack(side="left")
        self.btn_retry = ttk.Button(run, text="Retry failed", command=lambda: self.start_generation("retry"))
        self.btn_retry.pack(side="left", padx=4)
        self.btn_reconvert = ttk.Button(run, text="Re-convert MP3 → WAV",
                                        command=lambda: self.start_generation("reconvert"))
        self.btn_reconvert.pack(side="left")
        self.btn_cancel = ttk.Button(run, text="Cancel", command=self.cancel_generation, state="disabled")
        self.btn_cancel.pack(side="left", padx=4)
        ttk.Button(run, text="Open output folder", command=self.open_output).pack(side="right")

        self.progress = ttk.Progressbar(tab, mode="determinate")
        self.progress.pack(fill="x")
        self.lbl_progress = ttk.Label(tab, text="", style="Hint.TLabel")
        self.lbl_progress.pack(fill="x", pady=(2, 4))

        self.log = ScrolledText(tab, height=10, wrap="none", font=self.text_font, state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground="#1e7a3c")
        self.log.tag_configure("err", foreground="#b3261e")
        self.log.tag_configure("warn", foreground="#9a6700")
        self.log.tag_configure("head", font=self.bold_font)
        self.run_buttons = [self.btn_start, self.btn_retry, self.btn_reconvert]

    def refresh_category_checks(self):
        for child in self.cat_frame.winfo_children():
            child.destroy()
        cats = CATEGORIES + sorted({e["category"] for e in self.entries} - set(CATEGORIES))
        for i, cat in enumerate(cats):
            if cat not in self.v_cats:
                self.v_cats[cat] = tk.BooleanVar(value=True)
                self.v_cats[cat].trace_add("write", lambda *_: self.update_estimate())
            ttk.Checkbutton(self.cat_frame, text=CATEGORY_LABELS.get(cat, cat.title()),
                            variable=self.v_cats[cat]).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 16))

    def _on_tab_changed(self, _event=None):
        if self.nb.index("current") == 1:
            self.commit_form()
            self.refresh_category_checks()
            self.update_estimate()

    # ---------- settings ----------
    def cfg(self, quiet=False):
        """Read the settings widgets. Returns None (and shows an error) if invalid."""
        try:
            accent = {label: tld for tld, label in ENGLISH_ACCENTS}.get(self.v_accent.get(), "co.in")
            cfg = {
                "output_dir": os.path.abspath(os.path.expanduser(self.v_output.get().strip())),
                "ffmpeg": self.v_ffmpeg.get().strip() or "ffmpeg",
                "sample_rate": int(self.v_rate.get()),
                "channels": 2 if self.v_channels.get() == "Stereo" else 1,
                "workers": max(1, min(64, int(self.v_workers.get()))),
                "delay_min": max(0.0, float(self.v_dmin.get())),
                "delay_max": max(0.0, float(self.v_dmax.get())),
                "retries": max(1, int(self.v_retries.get())),
                "english_tld": accent,
                "keep_mp3": self.v_keep_mp3.get(),
                "skip_unchanged": self.v_skip.get(),
                "organize": self.v_organize.get(),
                "test_run": self.v_test.get(),
                "test_n": max(1, int(self.v_test_n.get())),
                "device_mb": max(0, int(float(self.v_device.get() or 0))),
                "languages": [l for l in LANG_KEYS if self.v_langs[l].get()],
                "categories": [c for c, v in self.v_cats.items() if v.get()],
            }
            if not 4000 <= cfg["sample_rate"] <= 192000:
                raise ValueError("sample rate must be between 4000 and 192000 Hz")
            cfg["delay_max"] = max(cfg["delay_max"], cfg["delay_min"])
            return cfg
        except ValueError as exc:
            if not quiet:
                messagebox.showerror(APP_NAME, f"Please check the settings: {exc}")
            return None

    def apply_settings(self, s):
        self._applying = True
        try:
            self._apply_settings(s)
        finally:
            self._applying = False
        self.update_estimate()

    def _apply_settings(self, s):
        s = {**DEFAULT_SETTINGS, **(s or {})}
        self.v_output.set(s["output_dir"])
        self.v_ffmpeg.set(s["ffmpeg"])
        self.v_rate.set(str(s["sample_rate"]))
        self.v_channels.set("Stereo" if int(s["channels"]) == 2 else "Mono")
        self.v_workers.set(str(s["workers"]))
        self.v_dmin.set(str(s["delay_min"]))
        self.v_dmax.set(str(s["delay_max"]))
        self.v_retries.set(str(s["retries"]))
        self.v_accent.set(dict(ENGLISH_ACCENTS).get(s["english_tld"], ENGLISH_ACCENTS[0][1]))
        self.v_keep_mp3.set(bool(s["keep_mp3"]))
        self.v_skip.set(bool(s["skip_unchanged"]))
        self.v_organize.set(bool(s["organize"]))
        self.v_test.set(bool(s["test_run"]))
        self.v_test_n.set(str(s["test_n"]))
        self.v_device.set(str(s["device_mb"]))
        for l, var in self.v_langs.items():
            var.set(l in s["languages"])
        for c, var in self.v_cats.items():
            var.set(c in s["categories"] or c not in CATEGORIES)

    def update_estimate(self):
        if not hasattr(self, "lbl_estimate"):
            return
        cfg = self.cfg(quiet=True)
        if cfg is None:
            self.lbl_estimate.config(text="", style="TLabel")
            return
        cats = set(cfg["categories"])
        selected = [e for e in self.entries if e["category"] in cats]
        if cfg["test_run"]:
            selected = selected[: cfg["test_n"]]
        n = sum(1 for e in selected for l in cfg["languages"] if e.get(l, "").strip())
        missing = sum(1 for e in selected for l in cfg["languages"] if not e.get(l, "").strip())
        per_file = cfg["sample_rate"] * 2 * cfg["channels"] * 3 + 44  # ~3 s of 16-bit PCM
        total = n * per_file
        text = (f"Will produce {n} WAV file{'s' if n != 1 else ''} ≈ {fmt_bytes(total)} "
                f"(assuming ~3 s each, {fmt_bytes(per_file)}/file).")
        if missing:
            text += f"\n{missing} language field(s) are empty and will be skipped."
        style = "TLabel"
        if cfg["device_mb"] and total > cfg["device_mb"] * 1024 * 1024:
            text += f"\n⚠ Exceeds the device's {cfg['device_mb']} MB."
            style = "Warn.TLabel"
        self.lbl_estimate.config(text=text, style=style)

    # ---------- tree ----------
    def refresh_tree(self, select=None):
        if not hasattr(self, "tree"):
            return
        cats = ["All"] + CATEGORIES + sorted({e["category"] for e in self.entries} - set(CATEGORIES))
        self.cmb_filter.config(values=cats)
        flt = self.v_filter.get()
        q = self.v_search.get().strip().lower()
        self._loading = True
        try:
            self.tree.delete(*self.tree.get_children())
            self.by_iid = {}
            for e in self.entries:
                if flt != "All" and e["category"] != flt:
                    continue
                if q and not any(q in str(e.get(k, "")).lower() for k in ["id"] + LANG_KEYS):
                    continue
                iid = f"e{id(e)}"
                self.by_iid[iid] = e
                self.tree.insert("", "end", iid=iid, values=self._row_values(e), tags=(entry_status(e)[1],))
            target = select if select is not None else self.current
            if target is not None and f"e{id(target)}" in self.by_iid:
                iid = f"e{id(target)}"
                self.tree.selection_set(iid)
                self.tree.see(iid)
        finally:
            self._loading = False
        filled = sum(1 for e in self.entries if entry_status(e)[1] == "ok")
        self.lbl_count.config(text=f"{len(self.entries)} entries · {filled} reviewed")

    def _row_values(self, e):
        filled = sum(1 for l in LANG_KEYS if e.get(l, "").strip())
        english = e.get("english", "").replace("\n", " ")
        return (e["category"], e["id"], english, f"{filled}/{len(LANG_KEYS)}", entry_status(e)[0])

    def update_row(self, e):
        iid = f"e{id(e)}"
        if self.tree.exists(iid):
            self.tree.item(iid, values=self._row_values(e), tags=(entry_status(e)[1],))

    def sort_by(self, col):
        if not self.commit_form():
            return
        if col in ("category", "id"):
            self.entries.sort(key=lambda e: (CATEGORIES.index(e["category"]) if e["category"] in CATEGORIES
                                             else 99, e["category"], natural_key(e["id"])))
        elif col == "english":
            self.entries.sort(key=lambda e: e.get("english", "").lower())
        else:
            self.entries.sort(key=lambda e: (entry_status(e)[1], e["category"], natural_key(e["id"])))
        self.mark_dirty()
        self.refresh_tree()

    def _on_select(self, _event=None):
        if self._loading:
            return
        sel = self.tree.selection()
        entry = self.by_iid.get(sel[0]) if len(sel) == 1 else None
        if entry is self.current:
            return
        if not self.commit_form():
            self._loading = True
            self.tree.selection_set(f"e{id(self.current)}")
            self._loading = False
            return
        self.load_entry(entry)
        if entry is not None and self.tree.exists(f"e{id(entry)}") \
                and self.tree.selection() != (f"e{id(entry)}",):
            self.tree.selection_set(f"e{id(entry)}")  # the commit may have rebuilt the list

    # ---------- editor ----------
    def _alive(self, entry):
        return any(x is entry for x in self.entries)

    def load_entry(self, entry):
        self.current = entry
        state = "normal" if entry else "disabled"
        for w in self.editor_widgets:
            w.config(state=state)
        self.cmb_cat.config(state=state)
        self.v_cat.set(entry["category"] if entry else "")
        self.v_id.set(entry["id"] if entry else "")
        self.v_reviewed.set(bool(entry and entry.get("reviewed")))
        for lang, txt in self.text_widgets.items():
            txt.config(state="normal")
            txt.delete("1.0", "end")
            if entry:
                txt.insert("1.0", entry.get(lang, ""))
            txt.edit_reset()
            txt.config(state=state, background="white" if entry else "#f0f0f0")
        self.update_filename_hint()

    def form_text(self, lang):
        return self.text_widgets[lang].get("1.0", "end-1c").strip()

    def commit_form(self, force_refresh=False):
        """Write the editor into the current entry. Returns False if the form is invalid."""
        e = self.current
        if e is None or not self._alive(e):
            return True
        cat = normalize_category(self.v_cat.get()) or "question"
        iid = slugify(self.v_id.get())
        if not iid:
            messagebox.showerror(APP_NAME, "The ID can't be empty (use letters, digits, underscores).")
            return False
        if any(x is not e and x["category"] == cat and x["id"] == iid for x in self.entries):
            messagebox.showerror(APP_NAME, f"'{cat}_{iid}' already exists. Choose a different ID.")
            return False
        new = {"category": cat, "id": iid, "reviewed": self.v_reviewed.get()}
        for lang in LANG_KEYS:
            new[lang] = self.form_text(lang)
        changed = any(e.get(k) != v for k, v in new.items())
        if changed:
            cat_changed = e["category"] != cat
            e.update(new)
            self.mark_dirty()
            if cat_changed or force_refresh:
                self.refresh_tree()
            else:
                self.update_row(e)
        if self.v_id.get() != iid:
            self.v_id.set(iid)
        if self.v_cat.get() != cat:
            self.v_cat.set(cat)
        if force_refresh:
            self.set_status("Changes applied." if changed else "No changes.")
        return True

    def update_filename_hint(self):
        if not hasattr(self, "lbl_filename"):
            return
        cat, iid = normalize_category(self.v_cat.get()), slugify(self.v_id.get())
        self.lbl_filename.config(text=f"Files: {cat}_{iid}_<language>.wav" if cat and iid else "")

    def add_entry(self):
        if not self.commit_form():
            return
        flt = self.v_filter.get()
        cat = flt if flt != "All" else (self.current["category"] if self.current else "question")
        nums = [int(e["id"]) for e in self.entries if e["category"] == cat and e["id"].isdigit()]
        item_id = f"{(max(nums) + 1) if nums else 1:02d}"
        while any(e["category"] == cat and e["id"] == item_id for e in self.entries):
            item_id += "_new"
        entry = new_entry(cat, item_id)
        self.entries.append(entry)
        self.mark_dirty()
        self.v_search.set("")
        self.refresh_tree(select=entry)
        self.load_entry(entry)
        self.text_widgets["english"].focus_set()

    def duplicate_entry(self):
        if not self.current or not self.commit_form():
            return
        copy = dict(self.current)
        base_id = copy["id"] + "_copy"
        copy["id"] = base_id
        n = 2
        while any(e["category"] == copy["category"] and e["id"] == copy["id"] for e in self.entries):
            copy["id"] = f"{base_id}{n}"
            n += 1
        copy["reviewed"] = False
        self.entries.insert(self.entries.index(self.current) + 1, copy)
        self.mark_dirty()
        self.refresh_tree(select=copy)
        self.load_entry(copy)

    def delete_entries(self):
        doomed = [self.by_iid[i] for i in self.tree.selection() if i in self.by_iid]
        if not doomed:
            return
        label = f"{doomed[0]['category']}_{doomed[0]['id']}" if len(doomed) == 1 else f"{len(doomed)} entries"
        if not messagebox.askyesno(APP_NAME, f"Delete {label}?"):
            return
        ids = {id(e) for e in doomed}
        self.entries = [e for e in self.entries if id(e) not in ids]
        self.current = None
        self.mark_dirty()
        self.refresh_tree()
        self.load_entry(None)

    # ---------- translation ----------
    def translate_current(self, overwrite):
        if not self.current or not self.commit_form():
            return
        e = self.current
        if not e["english"].strip():
            messagebox.showinfo(APP_NAME, "Type the English text first.")
            return
        langs = [l for l in TARGET_LANGS if overwrite or not e.get(l, "").strip()]
        if not langs:
            self.set_status("All languages already have text. Use 'Re-translate all' to overwrite.")
            return
        if overwrite and not messagebox.askyesno(
                APP_NAME, "Replace all five translations of this entry with machine translations?"):
            return
        self.run_translation([(e, l) for l in langs])

    def translate_all_missing(self):
        if not self.commit_form():
            return
        pairs = [(e, l) for e in self.entries if e["english"].strip()
                 for l in TARGET_LANGS if not e.get(l, "").strip()]
        if not pairs:
            messagebox.showinfo(APP_NAME, "Nothing to translate: every entry has all languages filled in.")
            return
        if not messagebox.askyesno(APP_NAME, f"Machine-translate {len(pairs)} empty field(s)?\n\n"
                                             "They will be marked 'needs review'."):
            return
        self.run_translation(pairs)

    def run_translation(self, pairs):
        if self.busy:
            messagebox.showinfo(APP_NAME, "Please wait for the current task to finish.")
            return
        self.busy = True
        self.set_run_state(True)
        total = len(pairs)
        self.set_status(f"Translating 0/{total}…")

        def worker():
            done = failed = 0
            errors = []

            def one(pair):
                entry, lang = pair
                time.sleep(random.uniform(0.05, 0.3))
                return pair, translate_text(entry["english"], LANGUAGES[lang][2])

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(one, p) for p in pairs]
                for fut in as_completed(futures):
                    try:
                        (entry, lang), text = fut.result()
                        self.ui(self._apply_translation, entry, lang, text)
                        done += 1
                    except Exception as exc:
                        failed += 1
                        errors.append(str(exc))
                    self.ui(self.set_status, f"Translating {done + failed}/{total}…")
            self.ui(self._translation_finished, done, failed, errors[:1])

        threading.Thread(target=worker, daemon=True).start()

    def _apply_translation(self, entry, lang, text):
        if not self._alive(entry) or not text:
            return
        entry[lang] = text
        entry["reviewed"] = False
        self.mark_dirty()
        self.update_row(entry)
        if entry is self.current:
            txt = self.text_widgets[lang]
            txt.delete("1.0", "end")
            txt.insert("1.0", text)
            self.v_reviewed.set(False)

    def _translation_finished(self, done, failed, errors):
        self.busy = False
        self.set_run_state(False)
        msg = f"Translated {done} field(s)."
        if failed:
            msg += f" {failed} failed ({errors[0] if errors else 'unknown error'})."
            messagebox.showwarning(APP_NAME, msg + "\n\nCheck your internet connection, "
                                   "or install deep-translator (pip install deep-translator).")
        self.set_status(msg + " Please review the machine translations.")
        self.refresh_tree()

    # ---------- preview ----------
    def preview(self):
        if not self.current:
            return
        name = self.v_preview_lang.get()
        lang = next(l for l in LANG_KEYS if LANGUAGES[l][0] == name)
        text = self.form_text(lang)
        if not text:
            messagebox.showinfo(APP_NAME, f"There is no {name} text to speak.")
            return
        if gTTS is None:
            messagebox.showerror(APP_NAME, "gTTS is not installed.\n\nRun:  pip install gTTS")
            return
        cfg = self.cfg()
        if cfg is None:
            return
        tld = cfg["english_tld"] if lang == "english" else "com"
        self.btn_preview.config(state="disabled")
        self.set_status(f"Generating {name} preview…")

        def worker():
            tmpdir = tempfile.mkdtemp(prefix="audio_preview_")
            try:
                mp3 = os.path.join(tmpdir, "preview.mp3")
                gTTS(text=text, lang=LANGUAGES[lang][1], tld=tld, slow=False).save(mp3)
                wav = os.path.join(tmpdir, "preview.wav")
                if ffmpeg_available(cfg["ffmpeg"]):  # hear exactly what the device will play
                    convert_to_wav(cfg["ffmpeg"], mp3, wav, cfg["sample_rate"], cfg["channels"])
                else:
                    wav = mp3
                self.ui(self.set_status, f"Playing {name} preview…")
                play_audio(wav, cfg["ffmpeg"])
                self.ui(self.set_status, "Preview finished.")
            except Exception as exc:
                self.ui(messagebox.showerror, APP_NAME, f"Preview failed:\n{exc}")
                self.ui(self.set_status, "Preview failed.")
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
                self.ui(lambda: self.btn_preview.config(state="normal" if self.current else "disabled"))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- generation ----------
    def start_generation(self, mode="all"):
        if self.busy:
            return
        if not self.commit_form():
            return
        cfg = self.cfg()
        if cfg is None:
            return
        if not cfg["languages"] or not cfg["categories"]:
            messagebox.showinfo(APP_NAME, "Select at least one language and one category.")
            return
        if mode != "reconvert" and gTTS is None:
            messagebox.showerror(APP_NAME, "gTTS is not installed.\n\nRun:  pip install gTTS")
            return
        if not ffmpeg_available(cfg["ffmpeg"]):
            messagebox.showerror(APP_NAME, "FFmpeg was not found.\n\nInstall FFmpeg and add it to PATH, "
                                 "or point the FFmpeg field to ffmpeg.exe / ffmpeg.")
            return
        base = output_base(cfg)
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Can't create the output folder:\n{exc}")
            return
        manifest = load_manifest(base)
        only = None
        if mode == "retry":
            only = self.last_failed or read_failed_csv(base)
            if not only:
                messagebox.showinfo(APP_NAME, "No failed files are recorded for this output folder.")
                return
        entries = [dict(e) for e in self.entries]  # snapshot: editing can continue safely
        jobs, notes = build_jobs(entries, cfg, manifest, only=only, reconvert=(mode == "reconvert"))
        if not jobs:
            msg = "Nothing to generate."
            if notes:
                msg += "\n\n" + "\n".join(notes[:8]) + ("\n…" if len(notes) > 8 else "")
            messagebox.showinfo(APP_NAME, msg)
            return
        work = [j for j in jobs if j.action != "skip"]
        if cfg["device_mb"]:
            per_file = cfg["sample_rate"] * 2 * cfg["channels"] * 3 + 44
            existing, _ = folder_size(os.path.join(base, "wav"))
            projected = existing + len(work) * per_file
            if projected > cfg["device_mb"] * 1024 * 1024 and not messagebox.askyesno(
                    APP_NAME, f"The WAV set may reach ≈ {fmt_bytes(projected)}, more than the device's "
                              f"{cfg['device_mb']} MB.\n\nContinue anyway?"):
                return

        self.busy = True
        self.cancel_event.clear()
        self.set_run_state(True)
        self.progress.config(maximum=max(1, len(jobs)), value=0)
        self.run_stats = {"processed": 0, "total": len(jobs), "done": 0, "converted": 0,
                          "skipped": 0, "failed": 0, "cancelled": 0, "t0": time.time(),
                          "network_jobs": sum(j.action == "full" for j in work)}
        self.log_clear()
        title = {"all": "Generating audio", "retry": "Retrying failed files",
                 "reconvert": "Re-converting MP3 → WAV"}[mode]
        self.log_line(f"{title} → {base}", "head")
        self.log_line(f"{len(jobs)} file(s): {sum(j.action == 'full' for j in jobs)} via gTTS, "
                      f"{sum(j.action == 'convert' for j in jobs)} from kept MP3s, "
                      f"{sum(j.action == 'skip' for j in jobs)} unchanged · "
                      f"{cfg['workers']} threads · {cfg['sample_rate']} Hz "
                      f"{'stereo' if cfg['channels'] == 2 else 'mono'} 16-bit PCM")
        for n in notes[:20]:
            self.log_line("  – skipped: " + n, "warn")
        if len(notes) > 20:
            self.log_line(f"  – … and {len(notes) - 20} more without text", "warn")
        self.set_status(title + "…")

        def worker():
            try:
                summary = run_pipeline(jobs, cfg, manifest, self.cancel_event,
                                       lambda kind, payload: self.events.put((kind, payload)))
                self.events.put(("finished", summary))
            except Exception:
                self.events.put(("crashed", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_generation(self):
        if self.busy:
            self.cancel_event.set()
            self.btn_cancel.config(state="disabled")
            self.set_status("Cancelling… (waiting for files in progress)")

    def _handle_result(self, r):
        st = self.run_stats
        job = r["job"]
        st["processed"] += 1
        st[r["status"]] = st.get(r["status"], 0) + 1
        name = job.stem + ".wav"
        if r["status"] == "done":
            self.log_line(f"✓ {name}  ({r['duration']:.1f} s, {fmt_bytes(r['size'])})", "ok")
        elif r["status"] == "converted":
            self.log_line(f"⟳ {name}  re-converted from MP3", "ok")
        elif r["status"] == "failed":
            self.log_line(f"✗ {name}  {r['error']}", "err")
        self.update_progress_label()

    def update_progress_label(self):
        st = self.run_stats
        self.progress.config(value=st["processed"])
        elapsed = time.time() - st["t0"]
        active = st["processed"] - st["skipped"]
        remaining = st["total"] - st["processed"]
        eta = f" · ~{fmt_secs(elapsed / active * remaining)} left" if active > 2 and remaining else ""
        self.lbl_progress.config(
            text=f"{st['processed']}/{st['total']} · new {st['done']} · re-converted {st['converted']} · "
                 f"unchanged {st['skipped']} · failed {st['failed']} · {fmt_secs(elapsed)} elapsed{eta}")

    def _finish(self, s):
        self.busy = False
        self.set_run_state(False)
        self.last_failed = {(r["job"].category, r["job"].item_id, r["job"].lang) for r in s["failed"]}
        self.update_progress_label()
        elapsed = time.time() - self.run_stats.get("t0", time.time())
        self.log_line("")
        self.log_line(f"Finished in {fmt_secs(elapsed)}: {s['done']} new, {s['converted']} re-converted, "
                      f"{s['skipped']} unchanged, {len(s['failed'])} failed"
                      + (f", {s['cancelled']} cancelled" if s["cancelled"] else ""), "head")
        self.log_line(f"WAV folder now holds {s['wav_count']} files, {fmt_bytes(s['wav_bytes'])} "
                      f"→ {os.path.join(s['base'], 'wav')}")
        cfg = self.cfg(quiet=True)
        if cfg and cfg["device_mb"] and s["wav_bytes"] > cfg["device_mb"] * 1024 * 1024:
            self.log_line(f"⚠ That is more than the device's {cfg['device_mb']} MB.", "err")
        if s["failed_csv"]:
            self.log_line(f"Failures logged to {s['failed_csv']} — use 'Retry failed'.", "err")
        self.set_status(f"Done: {s['done'] + s['converted']} file(s) written, {len(s['failed'])} failed.")
        if s["failed"]:
            messagebox.showwarning(APP_NAME, f"{len(s['failed'])} file(s) failed.\n\n"
                                   f"First error: {s['failed'][0]['error']}\n\n"
                                   "Click 'Retry failed' to process only those files.")

    def set_run_state(self, running):
        for b in self.run_buttons:
            b.config(state="disabled" if running else "normal")
        if not running:  # Cancel is enabled by the pipeline's "start" event
            self.btn_cancel.config(state="disabled")
        for b in (self.btn_tr_missing, self.btn_tr_all):
            b.config(state="disabled" if running or not self.current else "normal")

    def open_output(self):
        cfg = self.cfg(quiet=True)
        path = output_base(cfg) if cfg else self.v_output.get()
        if not os.path.isdir(path):
            path = self.v_output.get()
        if os.path.isdir(path):
            open_folder(path)
        else:
            messagebox.showinfo(APP_NAME, "The output folder doesn't exist yet.")

    def choose_output(self):
        path = filedialog.askdirectory(title="Choose output folder", initialdir=self.v_output.get())
        if path:
            self.v_output.set(path)
            self.mark_dirty()

    def choose_ffmpeg(self):
        types = [("ffmpeg", "ffmpeg.exe"), ("All files", "*")] if os.name == "nt" else [("All files", "*")]
        path = filedialog.askopenfilename(title="Locate the ffmpeg executable", filetypes=types)
        if path:
            self.v_ffmpeg.set(path)
            self.check_tools()

    # ---------- log / status / events ----------
    def log_clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def log_line(self, text, tag=None):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.config(state="disabled")

    def set_status(self, text):
        self.v_status.set(text)

    def ui(self, fn, *args):
        """Run fn(*args) on the Tk thread (safe to call from worker threads)."""
        self.events.put(("call", (fn, args)))

    def _poll_events(self):
        try:
            for _ in range(500):
                kind, payload = self.events.get_nowait()
                if kind == "call":
                    fn, args = payload
                    fn(*args)
                elif kind == "start":
                    self.btn_cancel.config(state="normal")
                    self.run_stats["skipped"] = self.run_stats["processed"] = payload["skipped"]
                    self.update_progress_label()
                    if payload["skipped"]:
                        self.log_line(f"↷ {payload['skipped']} unchanged file(s) skipped")
                elif kind == "result":
                    self._handle_result(payload)
                elif kind == "finished":
                    self._finish(payload)
                elif kind == "crashed":
                    self.busy = False
                    self.set_run_state(False)
                    self.log_line(payload, "err")
                    messagebox.showerror(APP_NAME, "Generation stopped unexpectedly. See the log for details.")
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    def check_tools(self, verbose=False):
        ff = self.v_ffmpeg.get().strip() or "ffmpeg"  # read Tk state on the UI thread

        def worker():
            ok = ffmpeg_available(ff)
            self.ui(self._show_tools, ok, verbose)
        threading.Thread(target=worker, daemon=True).start()

    def _show_tools(self, ffmpeg_ok, verbose):
        self.lbl_gtts.config(text="gTTS ✓" if gTTS else "gTTS ✗ (pip install gTTS)",
                             style="Good.TLabel" if gTTS else "Warn.TLabel")
        self.lbl_ffmpeg.config(text="FFmpeg ✓" if ffmpeg_ok else "FFmpeg ✗ not found",
                               style="Good.TLabel" if ffmpeg_ok else "Warn.TLabel")
        if verbose:
            messagebox.showinfo(APP_NAME, f"gTTS: {'installed' if gTTS else 'NOT installed — pip install gTTS'}\n"
                                          f"FFmpeg: {'found' if ffmpeg_ok else 'NOT found — install it or set its path'}")

    # ---------- project files ----------
    def mark_dirty(self, dirty=True):
        if self.dirty != dirty:
            self.dirty = dirty
            self.update_title()
        if hasattr(self, "lbl_estimate"):
            self.update_estimate()

    def update_title(self):
        name = os.path.basename(self.project_path) if self.project_path else "Untitled"
        self.title(f"{'● ' if self.dirty else ''}{name} — {APP_NAME}")

    def confirm_discard(self):
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel(APP_NAME, "Save changes to the current project?")
        if ans is None:
            return False
        return self.save_project() if ans else True

    def new_project(self):
        if self.busy or not self.confirm_discard():
            return
        self.entries, self.project_path, self.current = [], None, None
        self.apply_settings(DEFAULT_SETTINGS)
        self.last_failed = None
        self.refresh_tree()
        self.load_entry(None)
        self.mark_dirty(False)
        self.update_title()

    def open_project(self, path=None):
        if self.busy or not self.confirm_discard():
            return
        path = path or filedialog.askopenfilename(title="Open project",
                                                  filetypes=[("Audio project", "*.json"), ("All files", "*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            content = data.get("content", data) if isinstance(data, dict) else {}
            entries = content_to_entries(content)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"Couldn't open the project:\n{exc}")
            return
        self.entries, self.project_path, self.current = entries, path, None
        self.last_failed = None
        self.refresh_category_checks()
        self.apply_settings(data.get("settings") if isinstance(data, dict) else None)
        self.refresh_tree()
        self.load_entry(None)
        self.mark_dirty(False)
        self.update_title()
        self.set_status(f"Opened {os.path.basename(path)} — {len(entries)} entries.")

    def save_project(self, save_as=False):
        if not self.commit_form():
            return False
        path = self.project_path
        if save_as or not path:
            path = filedialog.asksaveasfilename(title="Save project", defaultextension=".json",
                                                initialfile="audio_project.json",
                                                filetypes=[("Audio project", "*.json")])
            if not path:
                return False
        cfg = self.cfg(quiet=True) or dict(DEFAULT_SETTINGS)
        data = {"format": PROJECT_FORMAT, "settings": cfg, "content": entries_to_content(self.entries)}
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Couldn't save:\n{exc}")
            return False
        self.project_path = path
        self.mark_dirty(False)
        self.update_title()
        self.set_status(f"Saved {os.path.basename(path)}.")
        return True

    def _merge_in(self, incoming, source):
        added, updated = merge_entries(self.entries, incoming)
        self.refresh_category_checks()
        self.refresh_tree()
        if added or updated:
            self.mark_dirty()
        self.set_status(f"Imported from {os.path.basename(source)}: {added} new, {updated} updated.")
        messagebox.showinfo(APP_NAME, f"{added} new entries, {updated} updated.")

    def import_py(self):
        if not self.commit_form():
            return
        path = filedialog.askopenfilename(title="Import Python dictionaries",
                                          filetypes=[("Python file", "*.py"), ("All files", "*")])
        if not path:
            return
        try:
            incoming = load_python_dicts(path)
        except (OSError, SyntaxError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"Couldn't read the file:\n{exc}")
            return
        if not incoming:
            messagebox.showinfo(APP_NAME, "No dictionaries like  questions = {'q1': {'english': …}}  were found.")
            return
        self._merge_in(incoming, path)

    def import_csv(self):
        if not self.commit_form():
            return
        path = filedialog.askopenfilename(title="Import CSV", filetypes=[("CSV", "*.csv"), ("All files", "*")])
        if not path:
            return
        try:
            incoming = read_csv_entries(path)
        except (OSError, ValueError, csv.Error) as exc:
            messagebox.showerror(APP_NAME, f"Couldn't read the CSV:\n{exc}")
            return
        self._merge_in(incoming, path)

    def export_csv(self):
        if not self.commit_form():
            return
        path = filedialog.asksaveasfilename(title="Export CSV", defaultextension=".csv",
                                            initialfile="translations_for_review.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            write_csv_entries(self.entries, path)
            self.set_status(f"Exported {len(self.entries)} entries to {os.path.basename(path)}.")

    def export_py(self):
        if not self.commit_form():
            return
        path = filedialog.asksaveasfilename(title="Export Python dictionaries", defaultextension=".py",
                                            initialfile="audio_content.py", filetypes=[("Python", "*.py")])
        if path:
            export_python_dicts(self.entries, path)
            self.set_status(f"Exported to {os.path.basename(path)}.")

    # ---------- tools ----------
    def add_numbers(self):
        if not self.commit_form():
            return
        start = simpledialog.askinteger(APP_NAME, "First number:", initialvalue=0, minvalue=0, parent=self)
        if start is None:
            return
        end = simpledialog.askinteger(APP_NAME, "Last number:", initialvalue=99, minvalue=start, parent=self)
        if end is None:
            return
        width = max(2, len(str(end)))
        incoming = []
        for n in range(start, end + 1):
            e = new_entry("number", f"{n:0{width}d}", str(n))
            for lang in ("hindi", "marathi", "bengali", "gujarati"):
                e[lang] = str(n)  # Google voices read digits in their own language
            incoming.append(e)
        added, _ = merge_entries(self.entries, incoming)
        self.refresh_tree()
        self.mark_dirty()
        messagebox.showinfo(APP_NAME, f"Added {added} number entries ({start}–{end}).\n\n"
                            "English, Hindi, Marathi, Bengali and Gujarati use digits, which each voice "
                            "reads in its own language. Sanskrit is left empty: the Hindi voice would say "
                            "Hindi numbers, so type the Sanskrit number words (e.g. पञ्च) yourself.")

    def load_sample(self):
        if not self.commit_form():
            return
        incoming = [new_entry(c, i, t) for c, i, t in SAMPLE_CONTENT]
        added, _ = merge_entries(self.entries, incoming)
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(f"Added {added} sample entries. Use 'Translate all missing' to fill other languages.")

    def show_help(self):
        messagebox.showinfo(APP_NAME, (
            "Workflow\n\n"
            "1. Content: add entries per category (questions, solutions, instructions, states, numbers, "
            "modes) in English, or import your Python dictionaries / a CSV.\n\n"
            "2. Translate: 'Translate all missing' fills Hindi, Marathi, Bengali, Gujarati and Sanskrit. "
            "Export CSV for native-speaker review, import it back, tick 'reviewed'.\n\n"
            "3. Generate: each text goes gTTS → MP3 → FFmpeg → WAV on a pool of worker threads. "
            "Sanskrit is spoken with the Hindi voice.\n\n"
            "Files are named {category}_{id}_{language}.wav and saved under wav/<category>/<language>/. "
            "MP3 backups go under mp3/. Unchanged files are skipped on later runs; failures are written "
            "to failed_files.csv and can be retried.\n\n"
            "Do a test run first, then play a sample of each language on the real device."))

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno(APP_NAME, "A task is still running. Stop it and quit?"):
                return
            self.cancel_event.set()
        if not self.confirm_discard():
            return
        self.destroy()


def main():
    if os.name == "nt":
        try:  # crisp text on high-DPI Windows displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if getattr(sys, "frozen", False):  # packaged .exe: use the ffmpeg/ffplay shipped beside it
        os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
    app = App()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        app.open_project(sys.argv[1])
    report = os.environ.get("AUDIO_STUDIO_SMOKE_TEST")
    if report:  # CI check for the packaged app: record what it can find, then quit
        def smoke_test():
            with open(report, "w", encoding="utf-8") as fh:
                json.dump({"gtts": gTTS is not None, "ffmpeg": ffmpeg_available("ffmpeg"),
                           "ffplay": find_ffplay("ffmpeg") is not None}, fh)
            app.destroy()
        app.after(1000, smoke_test)
    app.mainloop()


if __name__ == "__main__":
    main()

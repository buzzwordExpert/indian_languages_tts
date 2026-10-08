# Indian Languages TTS — Multilingual Audio Studio

A Tkinter desktop app that turns English text into **hardware-ready WAV audio in six languages**:
English, Hindi, Marathi, Bengali, Gujarati and Sanskrit. It was built to produce the voice prompts for an
embedded educational device (an interactive map & quiz module), but works for any project that needs
batches of short multilingual audio clips.

```
English text ──► translation + review ──► gTTS (MP3) ──► FFmpeg (16-bit PCM WAV) ──► organised output
```

- Write content once in English; machine-translate the other five languages, then mark them reviewed.
- Generate hundreds of files in parallel (15 worker threads by default) with retries and throttling protection.
- Firmware-safe file names: `{category}_{id}_{language}.wav`, no spaces.
- Incremental: only changed text is re-synthesised; failures are logged and can be retried on their own.

The full design and requirements are in
[`docs/multilingual_audio_workflow_detailed.pdf`](docs/multilingual_audio_workflow_detailed.pdf).

---

## Contents

1. [Requirements](#1-requirements)
2. [Installation](#2-installation)
3. [Launching the app](#3-launching-the-app)
4. [Quick start: your first audio set in 5 minutes](#4-quick-start-your-first-audio-set-in-5-minutes)
5. [Tab 1 · Content & translations](#5-tab-1--content--translations)
6. [Tab 2 · Generate audio](#6-tab-2--generate-audio)
7. [Menus and shortcuts](#7-menus-and-shortcuts)
8. [Working with files: projects, CSV review, Python dictionaries](#8-working-with-files)
9. [Output folder layout](#9-output-folder-layout)
10. [Language notes (Sanskrit, numbers)](#10-language-notes)
11. [Troubleshooting](#11-troubleshooting)
12. [Project structure](#12-project-structure)

---

## 1. Requirements

| Requirement | Why | Notes |
|---|---|---|
| **Python 3.8+** with **Tkinter** | Runs the app | Tkinter ships with the python.org installers for Windows/macOS. On Linux install it separately (see below). |
| **gTTS** | Text → MP3 speech | Installed from `requirements.txt`. |
| **FFmpeg** | MP3 → WAV conversion | Must be on `PATH`, or point the app to the executable. `ffplay` (bundled with FFmpeg) is used for previews. |
| **Internet connection** | gTTS and translation call Google's servers | No API key needed. |
| *deep-translator* (optional) | More reliable auto-translation | The app falls back to Google's public translate endpoint without it. |

Install the system packages:

```bash
# Fedora
sudo dnf install python3-tkinter ffmpeg-free        # or 'ffmpeg' from RPM Fusion

# Ubuntu / Debian
sudo apt install python3-tk ffmpeg

# macOS (Homebrew)
brew install python-tk ffmpeg

# Windows
winget install Gyan.FFmpeg                           # then restart the terminal so PATH updates
```

## 2. Installation

```bash
git clone https://github.com/buzzwordExpert/indian_languages_tts.git
cd indian_languages_tts

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

To get an `audio-studio` command instead, install the package itself:

```bash
pip install -e ".[translate]"        # drop [translate] to skip deep-translator
```

## 3. Launching the app

```bash
python run.py                        # from the repository folder
python run.py my_project.json        # open a saved project directly

audio-studio                         # if installed with pip install -e .
python -m indian_tts                 # same, as a module
```

On start-up the status bar (bottom right) shows **gTTS ✓** and **FFmpeg ✓**. If either shows **✗**, see
[Troubleshooting](#11-troubleshooting) before generating audio.

## 4. Quick start: your first audio set in 5 minutes

1. **Tools → Load sample content.** This adds 18 example entries: quiz questions, solutions, instructions,
   state facts and quiz modes, in English only. They show as red **✗ incomplete**.
2. Click **Translate all missing** (bottom right of the list) and confirm. Hindi, Marathi, Bengali, Gujarati
   and Sanskrit are filled in, and the entries turn amber (**⚠ needs review**).
3. Select an entry, choose a language next to **Listen:** and click **▶ Preview speech** to hear it.
4. Switch to **2 · Generate audio**. Tick **Test run: only the first 5 entries**, then click
   **▶ Generate audio**. The files go to `<output>/_test_run/`, so a test never mixes with the real set.
5. Click **Open output folder** and play a few WAVs, ideally **on the target device**.
6. Untick **Test run** and click **▶ Generate audio** again to produce the full set.
7. **File → Save project** (`Ctrl+S`) stores your content *and* settings in one `.json` file.

---

## 5. Tab 1 · Content & translations

This is where you write and review the text. Each **entry** is one prompt (for example *question 01*) holding
its text in all six languages.

### Entry list (left)

| Control | What it does |
|---|---|
| **Category** filter | Show one category (question, solution, instruction, state, number, mode) or **All**. |
| **Search** | Filters by ID or by text in any language. |
| Column headers | Click to sort by category/ID (natural order: 2 before 10), English text, or status. |
| **Langs** column | How many of the 6 languages have text, e.g. `4/6`. |
| **Status** column | 🔴 **✗ incomplete**: a language is empty · 🟠 **⚠ needs review**: all filled, not yet checked · 🟢 **✔ reviewed** |
| **+ Add entry** | New entry in the filtered (or current) category with the next free numeric ID (`01`, `02`, …). |
| **Duplicate** | Copies the selected entry as `<id>_copy` (marked not reviewed). |
| **Delete** / `Del` key | Deletes the selected entries (multi-select with Ctrl/Shift-click). |
| **Translate all missing** | Machine-translates every empty language field of every entry. |

### Entry editor (right)

| Control | What it does |
|---|---|
| **Category** / **ID** | Determine the file name, shown live underneath (`Files: question_01_<language>.wav`). IDs are cleaned automatically to lowercase letters, digits and underscores. A category + ID pair must be unique. |
| Six text boxes | English (the source) plus the five translations. `Tab` / `Shift+Tab` move between them. |
| **Translations reviewed by a native speaker** | Tick once the translations have been checked. Any machine translation clears this tick again. |
| **Apply changes** | Saves the editor into the entry. Edits are also applied automatically when you select another entry, switch tabs, save or generate. |
| **Translate empty fields** | Translates only this entry's empty languages. |
| **Re-translate all** | Overwrites all five translations of this entry (asks first). |
| **Listen:** + **▶ Preview speech** | Speaks the chosen language. When FFmpeg is available the preview is converted to your configured WAV format first, so you hear what the device will play. |

> Machine translation is only a first draft. For educational content have a native speaker review every entry,
> especially Marathi, Gujarati and Sanskrit. See [CSV review](#csv-review-round-trip) for doing this outside the app.

---

## 6. Tab 2 · Generate audio

### Output

| Setting | Default | Meaning |
|---|---|---|
| **Output folder** | `~/multilingual_audio_output` | Where `wav/`, `mp3/` and the logs are written. |
| **FFmpeg** | `ffmpeg` | Command name or full path to the executable (**Browse…** to pick it). |
| **Organise into wav/\<category\>/\<language\>/** | on | Off = all files flat in `wav/` and `mp3/`. |

### WAV format (for the embedded device)

| Setting | Default | Meaning |
|---|---|---|
| **Sample rate** | 22050 Hz | Choose 8000, 16000, 22050 or 44100, or type any value from 4000 to 192000. |
| **Channels** | Mono | Mono halves file size; most device speakers are mono anyway. |
| Codec | 16-bit PCM (`pcm_s16le`) | Fixed. Uncompressed WAV plays on microcontrollers without a decoder. |
| **English accent** | Indian English (`co.in`) | Also US, British or Australian. Affects English only. |

### Speed & reliability

| Setting | Default | Meaning |
|---|---|---|
| **Worker threads** | 15 | Files processed in parallel. Lower it if you see throttling errors. |
| **Retries** | 3 | Attempts per file, with increasing back-off between them. |
| **Delay per request** | 0.1 – 0.5 s | Random pause before each gTTS call to avoid IP throttling (HTTP 429). |
| **Keep MP3 backups** | on | Keeps gTTS's MP3s in `mp3/` so you can change the WAV format later without calling gTTS again. |
| **Skip files whose text hasn't changed** | on | Re-runs only synthesise new or edited text (see [manifest](#9-output-folder-layout)). |

### What to generate

Tick the **languages** and **categories** to include. Custom categories from imported files appear here too.

### Test run & storage

- **Test run: only the first N entries**: generates just N entries (all ticked languages) into
  `<output>/_test_run/`. Use it to catch font, encoding or voice problems before a full run.
- **Device storage (MB)**: enter your SD card/flash budget (0 = don't check). The estimate below updates live
  (assuming ~3 s per clip; 22050 Hz mono ≈ 130 KB per file). It turns red when the set won't fit, and
  generation asks before going over.

### Run buttons

| Button | What it does |
|---|---|
| **▶ Generate audio** | Runs the full pipeline for the current selection. |
| **Retry failed** | Re-processes only the files that failed last time (from memory, or from `failed_files.csv`). |
| **Re-convert MP3 → WAV** | Rebuilds every WAV from its kept MP3, with no network calls. Use it after changing the sample rate or channels. |
| **Cancel** | Stops after the files currently in progress finish. Completed files are kept. |
| **Open output folder** | Opens the folder in your file manager. |

The progress bar shows counts and the estimated time left. The log marks each file:

```
✓ question_01_hindi.wav  (2.4 s, 103.5 KB)      new file
⟳ question_01_hindi.wav  re-converted from MP3   WAV rebuilt from a kept MP3
✗ question_02_bengali.wav  gTTS failed after …   failed (logged to failed_files.csv)
↷ 42 unchanged file(s) skipped
```

---

## 7. Menus and shortcuts

| Menu | Item | Shortcut |
|---|---|---|
| **File** | New project · Open project… · Save project · Save project as… | `Ctrl+N` · `Ctrl+O` · `Ctrl+S` |
| | Import Python dictionaries (.py)… · Import CSV… | |
| | Export CSV for review… · Export Python dictionaries (.py)… | |
| **Tools** | Translate all missing fields | |
| | Add counting numbers… (asks for a range, e.g. 0–99) | |
| | Load sample content | |
| | Check gTTS & FFmpeg | |
| **Help** | How it works | |

A **●** in the window title means there are unsaved changes. Closing the window offers to save them.

---

## 8. Working with files

### Project files (`.json`)

**Save project** writes a single JSON file with every entry and every Generate-tab setting:

```json
{
  "format": "multilingual-audio-studio/1",
  "settings": { "output_dir": "...", "sample_rate": 22050, "workers": 15, "...": "..." },
  "content": {
    "question": {
      "01": { "english": "What is the capital of Maharashtra?", "hindi": "...", "reviewed": true }
    }
  }
}
```

### CSV review round-trip

1. **File → Export CSV for review…** writes `category, id, english, hindi, marathi, bengali, gujarati, sanskrit, reviewed`.
   The file is UTF-8 with BOM, so Excel and LibreOffice display Indic scripts correctly.
2. Send it to reviewers. They fix the text and set `reviewed` to `yes` (also accepted: `y`, `true`, `1`, `✔`).
3. **File → Import CSV…** merges the file back, matching rows on **category + id**:
   - non-empty cells overwrite the current text, and empty cells leave it untouched;
   - unknown category/id pairs are added as new entries.

You can also author content entirely in a spreadsheet. Only the `category` and `id` columns are required, and
language columns may use codes (`hi`, `mr`, `bn`, `gu`, `sa`, `en`).

### Python dictionaries (`.py`)

If your content already lives in Python (as described in the project document), import it directly. The file is
parsed safely and **never executed**:

```python
questions = {
    'q1': {'english': 'What is the capital of Maharashtra?', 'hindi': 'महाराष्ट्र की राजधानी क्या है?'},
}
instructions = {
    'start': 'Welcome! Press the start button to begin.',   # a plain string = English only
}
```

- The variable name becomes the category. Plurals and aliases are recognised: `questions` → question,
  `answers`/`solutions` → solution, `states`/`state_info` → state, `numbers`/`counting` → number,
  `modes`/`quiz_modes` → mode. Any other name becomes a custom category.
- **Export Python dictionaries** writes the same format back, so it can be used directly in firmware tooling.

---

## 9. Output folder layout

```
multilingual_audio_output/
├── wav/                                   ← copy this to the device's SD card / flash
│   ├── question/
│   │   ├── english/question_01_english.wav
│   │   ├── hindi/question_01_hindi.wav
│   │   └── …
│   ├── solution/ instruction/ state/ number/ mode/
├── mp3/                                   ← gTTS originals (if "Keep MP3 backups" is on)
├── manifest.json                          ← what each WAV was built from (for skipping unchanged files)
├── failed_files.csv                       ← only present if the last run had failures
└── _test_run/                             ← same structure, test runs only
```

**File naming:** `{category}_{id}_{language}.wav`, for example `question_01_hindi.wav`,
`state_maharashtra_gujarati.wav`, `mode_quiz_sanskrit.wav`. Names never contain spaces.

**How "skip unchanged" decides:** `manifest.json` stores a hash of each file's text, voice and accent, plus the
WAV format it was built with.

| What changed | What happens on the next run |
|---|---|
| Nothing | File skipped (`↷`) |
| WAV format only (sample rate/channels), MP3 kept | Re-converted from the MP3 (`⟳`), no network call |
| The text, or the English accent | Re-synthesised with gTTS (`✓`) |

`failed_files.csv` lists `category, id, language, file, text, error` for every failure, so you can see what went
wrong. **Retry failed** reads it, even after restarting the app.

---

## 10. Language notes

| Language | Script | gTTS voice | Notes |
|---|---|---|---|
| English | Latin | `en` | Accent selectable (Indian by default). |
| Hindi | Devanagari | `hi` | |
| Marathi | Devanagari | `mr` | |
| Bengali | Bengali | `bn` | |
| Gujarati | Gujarati | `gu` | |
| **Sanskrit** | Devanagari | **`hi`** | gTTS has no Sanskrit voice. Sanskrit text is written in Devanagari and read by the **Hindi voice**, so expect a slight modern-Hindi accent. Files are still saved as `_sanskrit.wav`. For high-fidelity Sanskrit, use human recordings. |

**Counting numbers:** **Tools → Add counting numbers…** creates `number` entries (e.g. `number_05`). English,
Hindi, Marathi, Bengali and Gujarati get digits, which each voice reads in its own language. **Sanskrit is left
empty on purpose**: the Hindi voice would read digits as Hindi numbers. Type the Sanskrit number words
(e.g. पञ्च) yourself.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Install Tkinter for your system Python: `sudo dnf install python3-tkinter` / `sudo apt install python3-tk`. |
| Status bar shows **gTTS ✗** | `pip install -r requirements.txt` inside the same environment you launch the app from. |
| Status bar shows **FFmpeg ✗ not found** | Install FFmpeg, or set the **FFmpeg** field (Generate tab) to its full path, e.g. `C:\ffmpeg\bin\ffmpeg.exe`. |
| Many files fail with `429` / `Too Many Requests` / connection errors | Google is throttling you. Lower **Worker threads** (e.g. 4–8), raise the **Delay** (e.g. 0.5–1.5 s), wait a few minutes, then click **Retry failed**. |
| Translation fails | Check your internet connection. `pip install deep-translator` gives a more reliable translator. |
| Indic text shows as boxes (□□□) | Install fonts. Fedora: `sudo dnf install google-noto-sans-devanagari-fonts google-noto-sans-bengali-fonts google-noto-sans-gujarati-fonts`. Ubuntu: `sudo apt install fonts-noto`. Windows uses *Nirmala UI* automatically. |
| Preview plays no sound | Install FFmpeg (it includes `ffplay`), or on Linux make sure `paplay`/`aplay` is available. |
| Output folder error | Choose a folder you have write access to with **Browse…**. |
| Sounds fine on PC, bad on device | Try a lower or higher sample rate that matches the device's DAC/codec, then **Re-convert MP3 → WAV**. No network calls are needed. |

---

## 12. Project structure

```
indian_languages_tts/
├── src/indian_tts/
│   ├── __init__.py        # package metadata
│   ├── __main__.py        # python -m indian_tts
│   ├── config.py          # languages, categories, default settings, sample content
│   ├── content.py         # entry model + CSV / Python-dict import & export
│   ├── translation.py     # English → Indian language machine translation
│   ├── pipeline.py        # gTTS → MP3 → FFmpeg → WAV, threading, manifest, failure log
│   ├── playback.py        # preview playback, open folder
│   └── gui.py             # Tkinter interface
├── docs/
│   └── multilingual_audio_workflow_detailed.pdf   # project requirements & workflow document
├── run.py                 # launcher for a source checkout
├── requirements.txt
├── pyproject.toml
└── LICENSE
```

`pipeline.py` has no Tkinter dependency, so the pipeline can also be scripted without the GUI:

```python
import threading
from indian_tts.config import DEFAULT_SETTINGS
from indian_tts.content import new_entry
from indian_tts.pipeline import build_jobs, load_manifest, output_base, run_pipeline

cfg = dict(DEFAULT_SETTINGS, output_dir="out", languages=["english", "hindi"])
entry = new_entry("question", "01", "What is the capital of Maharashtra?")
entry["hindi"] = "महाराष्ट्र की राजधानी क्या है?"

manifest = load_manifest(output_base(cfg))
jobs, _ = build_jobs([entry], cfg, manifest)
summary = run_pipeline(jobs, cfg, manifest, threading.Event(), lambda kind, payload: None)
print(summary["done"], "files written to", summary["base"])
```

## License

[MIT](LICENSE)

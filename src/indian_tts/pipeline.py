# -*- coding: utf-8 -*-
"""Audio pipeline: gTTS -> MP3 -> FFmpeg -> WAV (no Tkinter in here, so it can be
tested or scripted on its own)."""

import csv
import hashlib
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

try:  # gTTS is required for speech generation but the editor works without it
    from gtts import gTTS
except ImportError:  # pragma: no cover - depends on the user's environment
    gTTS = None

from .config import LANGUAGES, NO_WINDOW


class Cancelled(Exception):
    pass


@dataclass
class Job:
    category: str
    item_id: str
    lang: str
    text: str
    tts_lang: str
    tld: str
    stem: str
    mp3_path: str
    wav_path: str
    text_hash: str
    action: str  # "full" (gTTS + FFmpeg) | "convert" (FFmpeg from kept MP3) | "skip"


def output_base(cfg):
    base = cfg["output_dir"]
    return os.path.join(base, "_test_run") if cfg.get("test_run") else base


def file_paths(base, category, item_id, lang, organize):
    stem = f"{category}_{item_id}_{lang}"
    sub = (category, lang) if organize else ()
    return (stem,
            os.path.join(base, "mp3", *sub, stem + ".mp3"),
            os.path.join(base, "wav", *sub, stem + ".wav"))


def text_hash(text, tts_lang, tld):
    return hashlib.sha1(f"{tts_lang}|{tld}|{text}".encode("utf-8")).hexdigest()[:16]


def load_manifest(base):
    try:
        with open(os.path.join(base, "manifest.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_manifest(base, manifest):
    os.makedirs(base, exist_ok=True)
    tmp = os.path.join(base, "manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(base, "manifest.json"))


def read_failed_csv(base):
    path = os.path.join(base, "failed_files.csv")
    if not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return {(r["category"], r["id"], r["language"]) for r in csv.DictReader(fh)}


def write_failed_csv(base, failed_results):
    path = os.path.join(base, "failed_files.csv")
    if not failed_results:
        if os.path.isfile(path):
            os.remove(path)
        return None
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["category", "id", "language", "file", "text", "error"])
        for r in failed_results:
            j = r["job"]
            writer.writerow([j.category, j.item_id, j.lang, j.stem + ".wav", j.text, r["error"]])
    return path


def build_jobs(entries, cfg, manifest, only=None, reconvert=False):
    """Plan the work. Returns (jobs, notes) where notes lists entries that were left out."""
    base = output_base(cfg)
    params = f'{cfg["sample_rate"]}/{cfg["channels"]}'
    cats = set(cfg["categories"])
    selected = [e for e in entries if e["category"] in cats]
    if cfg.get("test_run"):
        selected = selected[: max(1, int(cfg["test_n"]))]
    jobs, notes = [], []
    for e in selected:
        for lang in cfg["languages"]:
            if only is not None and (e["category"], e["id"], lang) not in only:
                continue
            text = (e.get(lang) or "").strip()
            stem, mp3, wav = file_paths(base, e["category"], e["id"], lang, cfg["organize"])
            if not text:
                notes.append(f"{stem}: no {LANGUAGES[lang][0]} text")
                continue
            tts_lang = LANGUAGES[lang][1]
            tld = cfg["english_tld"] if lang == "english" else "com"
            h = text_hash(text, tts_lang, tld)
            rec = manifest.get(stem, {})
            mp3_current = rec.get("hash") == h and os.path.isfile(mp3)
            wav_current = (rec.get("hash") == h and rec.get("params") == params
                           and os.path.isfile(wav))
            if reconvert:
                if not mp3_current:
                    notes.append(f"{stem}: no up-to-date MP3 to re-convert")
                    continue
                action = "convert"
            elif cfg["skip_unchanged"] and wav_current:
                action = "skip"
            elif cfg["skip_unchanged"] and mp3_current:
                action = "convert"
            else:
                action = "full"
            jobs.append(Job(e["category"], e["id"], lang, text, tts_lang, tld,
                            stem, mp3, wav, h, action))
    return jobs, notes


def ffmpeg_available(ffmpeg):
    try:
        subprocess.run([ffmpeg, "-version"], capture_output=True, check=True, timeout=15, **NO_WINDOW)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def convert_to_wav(ffmpeg, src, dst, sample_rate=22050, channels=1):
    """MP3 -> 16-bit little-endian PCM WAV (written atomically)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst[:-4] + ".tmp.wav"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
           "-ar", str(sample_rate), "-ac", str(channels), "-acodec", "pcm_s16le",
           "-f", "wav", tmp]
    proc = subprocess.run(cmd, capture_output=True, timeout=120, **NO_WINDOW)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError("FFmpeg: " + (err[-1] if err else f"exit code {proc.returncode}"))
    os.replace(tmp, dst)


def synthesize(text, tts_lang, tld, out_path, cfg, cancel):
    """gTTS -> MP3 with a polite random delay and retries with back-off."""
    if gTTS is None:
        raise RuntimeError("gTTS is not installed (pip install gTTS)")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    retries = max(1, int(cfg["retries"]))
    last = None
    for attempt in range(1, retries + 1):
        if cancel.is_set():
            raise Cancelled()
        time.sleep(random.uniform(cfg["delay_min"], max(cfg["delay_min"], cfg["delay_max"])))
        tmp = out_path + ".part"
        try:
            gTTS(text=text, lang=tts_lang, tld=tld, slow=False).save(tmp)
            if os.path.getsize(tmp) == 0:
                raise RuntimeError("empty audio returned")
            os.replace(tmp, out_path)
            return
        except Exception as exc:  # network errors, throttling (HTTP 429), etc.
            last = exc
            if os.path.exists(tmp):
                os.remove(tmp)
            if attempt < retries:
                time.sleep(min(10, 2 ** attempt) + random.random())
    raise RuntimeError(f"gTTS failed after {retries} attempt(s): {last}")


def wav_info(path):
    size = os.path.getsize(path)
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate()), size
    except (wave.Error, EOFError, ZeroDivisionError):
        return 0.0, size


def process_job(job, cfg, cancel, tmpdir):
    """One file: [gTTS -> MP3] -> FFmpeg -> WAV. Never raises; returns a result dict."""
    result = {"job": job, "status": "failed", "error": "", "duration": 0.0, "size": 0}
    if cancel.is_set():
        result["status"] = "cancelled"
        return result
    try:
        if job.action == "full":
            mp3 = job.mp3_path if cfg["keep_mp3"] else os.path.join(tmpdir, job.stem + ".mp3")
            synthesize(job.text, job.tts_lang, job.tld, mp3, cfg, cancel)
        else:
            mp3 = job.mp3_path
        if cancel.is_set():
            raise Cancelled()
        convert_to_wav(cfg["ffmpeg"], mp3, job.wav_path, cfg["sample_rate"], cfg["channels"])
        if job.action == "full" and not cfg["keep_mp3"] and os.path.exists(mp3):
            os.remove(mp3)
        result["duration"], result["size"] = wav_info(job.wav_path)
        result["status"] = "done" if job.action == "full" else "converted"
    except Cancelled:
        result["status"] = "cancelled"
    except Exception as exc:
        result["error"] = str(exc).strip().replace("\n", " ")[:300] or exc.__class__.__name__
    return result


def folder_size(path, ext=".wav"):
    total = count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.endswith(ext) and not name.endswith(".tmp.wav"):
                total += os.path.getsize(os.path.join(root, name))
                count += 1
    return total, count


def run_pipeline(jobs, cfg, manifest, cancel, emit):
    """Runs jobs on a ThreadPoolExecutor. emit(kind, payload) reports progress."""
    base = output_base(cfg)
    params = f'{cfg["sample_rate"]}/{cfg["channels"]}'
    os.makedirs(base, exist_ok=True)
    todo = [j for j in jobs if j.action != "skip"]
    emit("start", {"total": len(jobs), "skipped": len(jobs) - len(todo)})
    results = []
    tmpdir = tempfile.mkdtemp(prefix="audio_studio_")
    try:
        with ThreadPoolExecutor(max_workers=max(1, int(cfg["workers"]))) as pool:
            futures = [pool.submit(process_job, j, cfg, cancel, tmpdir) for j in todo]
            for fut in as_completed(futures):
                r = fut.result()
                if r["status"] in ("done", "converted"):
                    manifest[r["job"].stem] = {"hash": r["job"].text_hash, "params": params,
                                               "file": os.path.relpath(r["job"].wav_path, base)}
                results.append(r)
                emit("result", r)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        save_manifest(base, manifest)
    failed = [r for r in results if r["status"] == "failed"]
    failed_csv = write_failed_csv(base, failed)
    size, count = folder_size(os.path.join(base, "wav"))
    return {
        "base": base,
        "done": sum(r["status"] == "done" for r in results),
        "converted": sum(r["status"] == "converted" for r in results),
        "skipped": len(jobs) - len(todo),
        "failed": failed,
        "cancelled": sum(r["status"] == "cancelled" for r in results),
        "failed_csv": failed_csv,
        "wav_bytes": size,
        "wav_count": count,
    }

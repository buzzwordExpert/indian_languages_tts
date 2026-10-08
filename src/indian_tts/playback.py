# -*- coding: utf-8 -*-
"""Audio preview playback and opening folders in the OS file manager."""

import os
import shutil
import subprocess
import sys

from .config import NO_WINDOW
from .pipeline import convert_to_wav


def find_ffplay(ffmpeg):
    found = shutil.which("ffplay")
    if found:
        return found
    if os.path.dirname(ffmpeg):
        sibling = os.path.join(os.path.dirname(ffmpeg), "ffplay" + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(sibling):
            return sibling
    return None


def play_audio(path, ffmpeg="ffmpeg"):
    ffplay = find_ffplay(ffmpeg)
    if ffplay:
        subprocess.run([ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path], **NO_WINDOW)
        return
    if sys.platform == "darwin":
        subprocess.run(["afplay", path])
        return
    wav = path
    if not path.lower().endswith(".wav"):
        wav = os.path.splitext(path)[0] + "_play.wav"
        convert_to_wav(ffmpeg, path, wav, 22050, 1)
    if os.name == "nt":
        import winsound
        winsound.PlaySound(wav, winsound.SND_FILENAME)
        return
    for player in ("paplay", "aplay"):
        if shutil.which(player):
            subprocess.run([player, wav], capture_output=True)
            return
    raise RuntimeError("No audio player found (install FFmpeg's ffplay).")


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - opening a folder the user chose
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

# -*- coding: utf-8 -*-
"""Languages, content categories and default settings."""

import os
import subprocess


APP_NAME = "Multilingual Audio Studio"
PROJECT_FORMAT = "multilingual-audio-studio/1"

# language key -> (display name, gTTS voice code, translation code)
LANGUAGES = {
    "english": ("English", "en", "en"),
    "hindi": ("Hindi", "hi", "hi"),
    "marathi": ("Marathi", "mr", "mr"),
    "bengali": ("Bengali", "bn", "bn"),
    "gujarati": ("Gujarati", "gu", "gu"),
    # gTTS has no Sanskrit voice: Devanagari Sanskrit is read by the Hindi voice
    "sanskrit": ("Sanskrit", "hi", "sa"),
}
LANG_KEYS = list(LANGUAGES)
TARGET_LANGS = [k for k in LANG_KEYS if k != "english"]
LANG_ALIASES = {"en": "english", "hi": "hindi", "mr": "marathi", "bn": "bengali",
                "gu": "gujarati", "sa": "sanskrit"}

CATEGORIES = ["question", "solution", "instruction", "state", "number", "mode"]
CATEGORY_LABELS = {
    "question": "Quiz questions", "solution": "Solutions / answers",
    "instruction": "Instructions", "state": "State information",
    "number": "Counting numbers", "mode": "Quiz modes",
}
CATEGORY_ALIASES = {
    "questions": "question", "solutions": "solution", "answers": "solution",
    "answer": "solution", "instructions": "instruction", "states": "state",
    "state_info": "state", "numbers": "number", "counting": "number",
    "modes": "mode", "quiz_modes": "mode",
}

ENGLISH_ACCENTS = [("co.in", "Indian English (co.in)"), ("com", "US English (com)"),
                   ("co.uk", "British English (co.uk)"), ("com.au", "Australian English (com.au)")]

DEFAULT_SETTINGS = {
    "output_dir": os.path.join(os.path.expanduser("~"), "multilingual_audio_output"),
    "ffmpeg": "ffmpeg",
    "sample_rate": 22050,
    "channels": 1,
    "workers": 15,
    "delay_min": 0.1,
    "delay_max": 0.5,
    "retries": 3,
    "english_tld": "co.in",
    "keep_mp3": True,
    "skip_unchanged": True,
    "organize": True,
    "test_run": False,
    "test_n": 5,
    "device_mb": 0,
    "languages": LANG_KEYS[:],
    "categories": CATEGORIES[:],
}

SAMPLE_CONTENT = [
    ("question", "01", "What is the capital of Maharashtra?"),
    ("question", "02", "Which state is known as the land of five rivers?"),
    ("question", "03", "Which is the largest state in India by area?"),
    ("solution", "01", "The capital of Maharashtra is Mumbai."),
    ("solution", "02", "Punjab is known as the land of five rivers."),
    ("solution", "03", "Rajasthan is the largest state in India by area."),
    ("instruction", "start", "Welcome! Press the start button to begin."),
    ("instruction", "press_state", "Press the state you think is correct."),
    ("instruction", "quiz_active", "Quiz mode is now active."),
    ("instruction", "correct", "Well done, that is correct!"),
    ("instruction", "wrong", "That is not correct. Try again."),
    ("state", "maharashtra", "Maharashtra. Capital: Mumbai. It is the second most populous state in India."),
    ("state", "gujarat", "Gujarat. Capital: Gandhinagar. It has the longest coastline in India."),
    ("state", "west_bengal", "West Bengal. Capital: Kolkata. It is home to the Sundarbans mangrove forest."),
    ("mode", "easy", "Easy mode"),
    ("mode", "hard", "Hard mode"),
    ("mode", "practice", "Practice mode"),
    ("mode", "quiz", "Quiz mode"),
]

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

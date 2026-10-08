# -*- coding: utf-8 -*-
"""
Multilingual Audio Studio
=========================

A Tkinter desktop app for the "English text -> multilingual WAV" pipeline used by
the interactive map & quiz device:

    English source text (Python dicts / JSON)
      -> translation (Hindi, Marathi, Bengali, Gujarati, Sanskrit) + human review
      -> gTTS (MP3)
      -> FFmpeg (16-bit PCM WAV, 22050 Hz, mono by default)
      -> organised output:  wav/<category>/<language>/<category>_<id>_<language>.wav

Requirements:  Python 3.8+, gTTS (pip install gTTS), FFmpeg on PATH.
Optional:      deep-translator (pip install deep-translator) for auto-translation.
"""

__version__ = "1.0.0"

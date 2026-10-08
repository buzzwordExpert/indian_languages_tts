# -*- coding: utf-8 -*-
"""English -> Indian language machine translation."""

import json
import urllib.parse
import urllib.request


def translate_text(text, target_code, source_code="en"):
    """English -> target. Uses deep-translator when installed, else Google's public endpoint."""
    if not text.strip():
        return ""
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source=source_code, target=target_code).translate(text)
    except Exception:
        pass  # not installed, or language not in its list (e.g. Sanskrit) -> fall back
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": source_code, "tl": target_code, "dt": "t", "q": text})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()

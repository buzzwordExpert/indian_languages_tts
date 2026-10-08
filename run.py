#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Launch Multilingual Audio Studio from a source checkout: python run.py [project.json]"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from indian_tts.gui import main  # noqa: E402

if __name__ == "__main__":
    main()

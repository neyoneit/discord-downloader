#!/usr/bin/env python3
import subprocess

from settings import DEMO_RENDERING_LOCAL_YOUTUBE_EXECUTABLE, DEMO_RENDERING_LOCAL_YOUTUBE_PARAMS

subprocess.call([
    DEMO_RENDERING_LOCAL_YOUTUBE_EXECUTABLE,
    *DEMO_RENDERING_LOCAL_YOUTUBE_PARAMS,
    '--refresh-auth'
])

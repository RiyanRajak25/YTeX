"""Shift – Utility helpers.

Metadata scrubbing with randomised fingerprints to evade automated
content-ID footprinting.
"""

import os
import random
import subprocess

import imageio_ffmpeg


def scrub_metadata(input_path, output_path):
    """Strip all metadata and inject randomised software / creation tags."""
    sw = f"Shift_v{random.randint(1, 9)}.{random.randint(0, 9)}"
    ts = (
        f"{random.randint(2020, 2024)}-{random.randint(1, 12):02d}-"
        f"{random.randint(1, 28):02d} {random.randint(0, 23):02d}:"
        f"{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", input_path,
                "-map_metadata", "-1",
                "-metadata", f"creation_time={ts}",
                "-metadata", f"software={sw}",
                "-c:v", "copy", "-c:a", "copy",
                output_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True
    except subprocess.CalledProcessError as exc:
        print(f"Metadata scrub error: {exc.stderr.decode()}")
        return False

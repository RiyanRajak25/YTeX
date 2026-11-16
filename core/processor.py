"""Shift – Core Video Processor.

Pipeline: Watermark Detect → BG Removal → Logo Overlay → Effects → Audio → Mux → Metadata Scrub.
"""

import os
import re
import random
import subprocess

import cv2
import numpy as np
import imageio_ffmpeg
from moviepy import VideoFileClip

from .vision import VisionProcessor
from .effects import EffectsEngine
from .audio import AudioEngine
from .editorial import EditorialEngine
from .utils import scrub_metadata

TEMP_DIR = "temp_processing"


class VideoProcessor:
    """Processes a single video through the Shift pipeline."""

    def __init__(self, video_path, raw_transcript, output_path):
        self.video_path = video_path
        self.raw_transcript = raw_transcript
        self.output_path = output_path

        os.makedirs(TEMP_DIR, exist_ok=True)

        # Sub-engines (fresh per video — no state bleed between queue items)
        self.vision = VisionProcessor()
        self.effects = EffectsEngine()
        self.audio = AudioEngine()
        self.editorial = EditorialEngine()

        self.logo_path = self._pick_logo()
        self.pause_points = self._parse_pause_points()
        self.watermark_bbox = None

    # ── Pause-Point Parsing ──────────────────────────────────────────────────

    def _parse_pause_points(self):
        """Extract [MM:SS | TITLE | text] tags from the transcript."""
        pattern = r"\[\s*(\d{2}:\d{2})\s*\|\s*([^|]+)\s*\|\s*(.*?)\]"
        colors = [
            (255, 87, 34, 230),   # Deep Orange
            (33, 150, 243, 230),  # Blue
            (76, 175, 80, 230),   # Green
            (255, 152, 0, 230),   # Orange
            (156, 39, 176, 230),  # Purple
            (233, 30, 99, 230)    # Pink
        ]
        return [
            {
                "timestamp": m[0],
                "title": m[1].strip(),
                "text": m[2].strip(),
                "duration": 2.0,
                "bg_color": random.choice(colors)
            }
            for m in re.findall(pattern, self.raw_transcript)
        ]

    # ── Logo Selection ───────────────────────────────────────────────────────

    @staticmethod
    def _pick_logo():
        """Return a random logo path from assets/logos, or None."""
        logos_dir = "assets/logos"
        if not os.path.isdir(logos_dir):
            return None
        logos = [f for f in os.listdir(logos_dir)
                 if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        return os.path.join(logos_dir, random.choice(logos)) if logos else None

    # ── Watermark Detection ──────────────────────────────────────────────────

    def _detect_watermark_in_frame(self, frame):
        """Scan the middle band of a single frame for a bright text watermark.

        Excludes the top 8 % (title banners) and bottom 40 % (existing
        subtitles in the raw footage) to avoid false positives.
        Returns (x, y, w, h) or None.
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        y_lo = int(h * 0.08)   # below title banners
        y_hi = int(h * 0.60)   # above subtitles

        for thresh in (240, 220, 200, 180, 160):
            _, binary = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (18, 8))
            closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(
                closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            candidates = []
            for cnt in contours:
                cx, cy, cw, ch = cv2.boundingRect(cnt)
                if cw < 30 or ch < 8:
                    continue
                # Reject contours whose centre sits outside the safe band
                if not (y_lo <= cy + ch // 2 <= y_hi):
                    continue

                aspect = cw / max(ch, 1)
                area_pct = (cw * ch) / (w * h)
                if not (0.0002 < area_pct < 0.03 and 1.2 < aspect < 8.0):
                    continue

                brightness = float(np.mean(gray[cy:cy + ch, cx:cx + cw]))
                if brightness > 100:
                    candidates.append((cx, cy, cw, ch, brightness))

            if candidates:
                best = max(candidates, key=lambda c: c[4])
                return best[:4]

        return None

    def _detect_watermark(self, cap, fps, total_frames):
        """Multi-frame scan with early-frame priority.

        Samples 7 frames across the first 2.5 s.  Trusts the earliest
        detection (the watermark is always visible at the very start).
        """
        offsets = [int(t * fps) for t in (0, 0.3, 0.7, 1.0, 1.5, 2.0, 2.5)
                   if int(t * fps) < total_frames]

        detections = []
        for off in offsets:
            cap.set(cv2.CAP_PROP_POS_FRAMES, off)
            ret, frame = cap.read()
            if not ret:
                continue
            result = self._detect_watermark_in_frame(frame)
            if result is not None:
                detections.append(result)
                print(f"  [watermark] frame {off}: hit {result}")
            else:
                print(f"  [watermark] frame {off}: miss")

        if not detections:
            return None

        bx, by, bw, bh = detections[0]  # anchor = earliest detection

        # Expand box to cover "made with" text above the logo line
        pad_up, pad_side, pad_down = int(bh * 0.7), int(bw * 0.15), int(bh * 0.25)
        fw_total = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh_total = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        fx = max(0, bx - pad_side)
        fy = max(0, by - pad_up)
        fw = min(fw_total - fx, bw + 2 * pad_side)
        fh = min(fh_total - fy, bh + pad_up + pad_down)

        print(f"  [watermark] final: raw=({bx},{by},{bw},{bh}), "
              f"expanded=({fx},{fy},{fw},{fh})")
        return (fx, fy, fw, fh)

    # ── Logo Overlay ─────────────────────────────────────────────────────────

    def _overlay_logo(self, frame):
        """Paste the logo exactly over the detected watermark region."""
        if not self.logo_path or self.watermark_bbox is None:
            return frame

        logo = cv2.imread(self.logo_path, cv2.IMREAD_UNCHANGED)
        if logo is None:
            return frame

        wx, wy, ww, wh = self.watermark_bbox
        h, w = frame.shape[:2]
        ww, wh = min(ww, w - wx), min(wh, h - wy)
        if ww <= 0 or wh <= 0:
            return frame

        logo = cv2.resize(logo, (ww, wh), interpolation=cv2.INTER_AREA)

        if logo.shape[2] == 4:
            alpha3 = (logo[:, :, 3].astype(np.float32) / 255.0)[..., None]
            inv3 = 1.0 - alpha3
            roi = frame[wy:wy + wh, wx:wx + ww]
            frame[wy:wy + wh, wx:wx + ww] = (alpha3 * logo[:, :, :3] + inv3 * roi).astype(np.uint8)
        else:
            frame[wy:wy + wh, wx:wx + ww] = logo[:, :, :3]

        return frame

    # ── Pause-Frame Rendering ────────────────────────────────────────────────

    def _render_pause(self, base_frame, pause, progress, writer, fps):
        """Freeze-frame with micro-zoom, blur, logo, effects, and fact bubble."""
        duration = float(pause.get("duration", 2.0))
        n_frames = int(duration * fps)
        h, w = base_frame.shape[:2]

        for i in range(n_frames):
            t = i / max(n_frames, 1)

            # Micro-zoom 1.0→1.1×
            scale = 1.0 + 0.1 * t
            nw, nh = int(w / scale), int(h / scale)
            y1, x1 = (h - nh) // 2, (w - nw) // 2
            zoomed = cv2.resize(base_frame[y1:y1 + nh, x1:x1 + nw], (w, h))

            # Apply background blur
            zoomed = cv2.GaussianBlur(zoomed, (51, 51), 0)

            zoomed = self._overlay_logo(zoomed)
            zoomed = self.effects.process_frame(zoomed, progress)
            zoomed = self.editorial.render_fact_bubble(
                zoomed, pause.get("text", ""), pause.get("title", ""), t, pause.get("bg_color", (44, 62, 80, 230))
            )
            writer.write(zoomed)

    # ── Main Pipeline ────────────────────────────────────────────────────────

    def _ts_to_seconds(self, ts):
        """Convert "MM:SS" → float seconds."""
        parts = ts.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def process(self, progress_callback=None):
        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # ── 1. Watermark scan (on raw video, before any processing) ──────
        print(f"Scanning for watermark: {os.path.basename(self.video_path)}")
        self.watermark_bbox = self._detect_watermark(cap, fps, total_frames)
        if self.watermark_bbox:
            print(f"  ✓ Logo will cover {self.watermark_bbox}")
        else:
            print("  ✗ No watermark — logo overlay skipped")

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        # Trim final 2 s (Vizard outro)
        work_frames = max(1, total_frames - int(fps * 2.0))

        temp_video = os.path.join(TEMP_DIR, "temp_video.mp4")
        orig_audio = os.path.join(TEMP_DIR, "temp_original_audio.mp3")
        proc_audio = os.path.join(TEMP_DIR, "temp_processed_audio.mp3")
        muxed = os.path.join(TEMP_DIR, "muxed.mp4")

        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(temp_video, fourcc, fps, (width, height))

            try:
                # ── 2. Frame-by-frame processing ─────────────────────────────
                print("Processing frames …")
                for i in range(work_frames):
                    ret, frame = cap.read()
                    if not ret:
                        break

                    current_sec = i / fps
                    progress = i / work_frames

                    # Background removal
                    frame = self.vision.process_frame(frame)

                    # Editorial pause?
                    for p in self.pause_points:
                        if p.get("_done"):
                            continue
                        p_sec = self._ts_to_seconds(p["timestamp"])
                        if abs(current_sec - p_sec) < (1.0 / fps):
                            p["_done"] = True
                            print(f"  ⏸ Pause at {p['timestamp']} ({p['duration']}s)")
                            self._render_pause(frame, p, progress, out, fps)
                            break

                    # Logo → Effects → Write
                    frame = self._overlay_logo(frame)
                    frame = self.effects.process_frame(frame, progress)
                    out.write(frame)

                    if progress_callback and i % 10 == 0:
                        progress_callback(progress * 0.5)
            finally:
                cap.release()
                out.release()

            # ── 3. Audio ─────────────────────────────────────────────────────
            print("Building audio …")
            clip = VideoFileClip(self.video_path)
            try:
                clip.audio.write_audiofile(orig_audio, logger=None)
            finally:
                clip.close()

            self.audio.build_audio_track(
                orig_audio, self.pause_points, proc_audio, work_frames / fps
            )

            if progress_callback:
                progress_callback(0.7)

            # ── 4. Mux + 1.05× speed ────────────────────────────────────────
            print("Muxing + speed …")
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-i", temp_video,
                    "-i", proc_audio,
                    "-filter_complex",
                    (
                        "[0:v]split[v1][v2];"
                        "[v1]trim=end=2,setpts=PTS-STARTPTS[v_start];"
                        "[v2]trim=start=2,setpts=PTS-STARTPTS[v_rest];"
                        "[v_rest][v_start]concat=n=2:v=1:a=0[v_cat];"
                        "[v_cat]setpts=0.95238*PTS[v];"
                        "[1:a]asplit[a1][a2];"
                        "[a1]atrim=end=2,asetpts=PTS-STARTPTS[a_start];"
                        "[a2]atrim=start=2,asetpts=PTS-STARTPTS[a_rest];"
                        "[a_rest][a_start]concat=n=2:v=0:a=1[a_cat];"
                        "[a_cat]atempo=1.05[a]"
                    ),
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-c:a", "aac",
                    muxed,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if progress_callback:
                progress_callback(0.9)

            # ── 5. Metadata scrub ────────────────────────────────────────────
            print("Scrubbing metadata …")
            scrub_metadata(muxed, self.output_path)

            if progress_callback:
                progress_callback(1.0)

            print("✓ Done!")
        finally:
            # Clean up temp files
            for f in [temp_video, orig_audio, proc_audio, muxed]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass

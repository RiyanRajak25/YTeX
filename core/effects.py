"""Shift – Cinematic Effects Engine.

Applies film-grain, chromatic aberration, Ken Burns drift, colour grading,
and micro-jitter to every frame for a handmade / analogue feel.
"""

import random

import cv2
import numpy as np


class EffectsEngine:
    """Per-video effect parameters are rolled once at construction."""

    def __init__(self):
        self.aberration_px = random.randint(1, 2)
        self.ken_burns_max = random.uniform(1.0, 1.08)
        self.grain_opacity = random.uniform(0.02, 0.06)

        self._frame_idx = 0
        self._jitter_interval = random.randint(240, 300)
        self._noise_cache = None

    # ── Individual Effects ───────────────────────────────────────────────────

    def _chromatic_aberration(self, frame):
        """Shift red / blue channels by ±N px using slicing (faster than warpAffine)."""
        if self.aberration_px == 0:
            return frame
        b, g, r = cv2.split(frame)
        s = self.aberration_px

        out_r = np.zeros_like(r)
        out_b = np.zeros_like(b)

        out_r[:, s:] = r[:, :-s]
        out_b[:, :-s] = b[:, s:]
        
        return cv2.merge((out_b, g, out_r))

    def _film_grain(self, frame):
        """Add subtle noise + faint scanlines using a pre-generated noise cache."""
        h, w = frame.shape[:2]
        if self._noise_cache is None or self._noise_cache.shape[:2] != (h * 2, w * 2):
            self._noise_cache = np.random.randint(0, 256, (h * 2, w * 2, 3), dtype=np.uint8)

        dy = random.randint(0, h - 1)
        dx = random.randint(0, w - 1)
        noise = self._noise_cache[dy:dy+h, dx:dx+w]

        out = cv2.addWeighted(frame, 1.0 - self.grain_opacity,
                              noise, self.grain_opacity, 0)
        out[::6] = (out[::6].astype(np.float32) * 0.95).astype(np.uint8)
        return out

    def _colour_grade(self, frame):
        """Slight saturation boost (placeholder for full LUT support)."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.1, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    def _ken_burns(self, frame, progress):
        """Slow centre-crop zoom from 1.0× → ken_burns_max over the video."""
        scale = 1.0 + (self.ken_burns_max - 1.0) * progress
        h, w = frame.shape[:2]
        nw, nh = int(w / scale), int(h / scale)
        y1, x1 = (h - nh) // 2, (w - nw) // 2
        return cv2.resize(frame[y1:y1 + nh, x1:x1 + nw], (w, h))

    def _micro_jitter(self, frame):
        """5 % chance of a 1 px random shift per frame using slicing."""
        if random.random() >= 0.05:
            return frame
        dx, dy = random.randint(-1, 1), random.randint(-1, 1)
        if dx == 0 and dy == 0:
            return frame
            
        out = np.zeros_like(frame)
        h, w = frame.shape[:2]
        
        src_y1 = max(0, -dy)
        src_y2 = min(h, h - dy)
        src_x1 = max(0, -dx)
        src_x2 = min(w, w - dx)
        
        dst_y1 = max(0, dy)
        dst_y2 = min(h, h + dy)
        dst_x1 = max(0, dx)
        dst_x2 = min(w, w + dx)
        
        out[dst_y1:dst_y2, dst_x1:dst_x2] = frame[src_y1:src_y2, src_x1:src_x2]
        return out

    # ── Composite ────────────────────────────────────────────────────────────

    def process_frame(self, frame, progress):
        """Apply the full effects stack to one frame.

        Args:
            frame:    BGR numpy array.
            progress: 0.0 → 1.0 (position in video).
        """
        self._frame_idx += 1

        frame = self._micro_jitter(frame)
        frame = self._ken_burns(frame, progress)
        frame = self._chromatic_aberration(frame)
        frame = self._film_grain(frame)
        frame = self._colour_grade(frame)
        return frame

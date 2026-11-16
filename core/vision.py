"""Shift – Vision Processor (Background Replacement).

Uses MediaPipe's selfie segmenter to isolate the speaker, composites
them onto a random background with a soft drop-shadow.
"""

import os
import random

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite"
)


class VisionProcessor:
    def __init__(self, bg_folder="assets/backgrounds"):
        self.bg_folder = bg_folder
        self._segmenter = self._load_segmenter()
        self._bg = self._load_random_bg()

    # ── Setup ────────────────────────────────────────────────────────────────

    def _load_segmenter(self):
        model_path = os.path.join(os.path.dirname(__file__),
                                  "models", "selfie_segmenter.tflite")
        if not os.path.exists(model_path):
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            import urllib.request
            print("Downloading selfie_segmenter.tflite …")
            urllib.request.urlretrieve(_MODEL_URL, model_path)

        opts = vision.ImageSegmenterOptions(
            base_options=python.BaseOptions(model_asset_path=model_path),
            output_category_mask=True,
        )
        return vision.ImageSegmenter.create_from_options(opts)

    def _load_random_bg(self):
        if not os.path.isdir(self.bg_folder):
            os.makedirs(self.bg_folder, exist_ok=True)
            return None
        imgs = [f for f in os.listdir(self.bg_folder)
                if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        if not imgs:
            return None
        return cv2.imread(os.path.join(self.bg_folder, random.choice(imgs)))

    # ── Per-Frame ────────────────────────────────────────────────────────────

    @staticmethod
    def _drop_shadow(mask, shape, blur=15, offset=(10, 10), opacity=0.5):
        """Return a float32 (h, w) shadow intensity map."""
        h, w = shape
        shifted = np.zeros((h, w), dtype=np.uint8)
        dy, dx = offset
        
        # Slicing translation (much faster than warpAffine)
        max_y = min(h, h - dy)
        max_x = min(w, w - dx)
        if max_y > 0 and max_x > 0:
            shifted[dy:dy+max_y, dx:dx+max_x] = (mask[:max_y, :max_x] * 255).astype(np.uint8)
            
        blurred = cv2.GaussianBlur(shifted, (blur * 2 + 1, blur * 2 + 1), 0)
        return blurred.astype(np.float32) / 255.0 * opacity

    def process_frame(self, frame):
        """Segment → shadow → composite onto background."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._segmenter.segment(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        )
        mask = (result.category_mask.numpy_view() < 0.1).astype(np.float32)
        if mask.ndim == 3:
            mask = mask[:, :, 0]

        # Background (resize once if needed)
        if self._bg is None:
            self._bg = np.zeros_like(frame)
        elif self._bg.shape[:2] != frame.shape[:2]:
            self._bg = cv2.resize(self._bg, (frame.shape[1], frame.shape[0]))
        bg = self._bg

        mask3 = mask[..., None]
        shadow = self._drop_shadow(mask, frame.shape[:2])
        shadow3 = shadow[..., None]

        composite = frame * mask3 + bg * (1 - shadow3) * (1 - mask3)
        return composite.astype(np.uint8)

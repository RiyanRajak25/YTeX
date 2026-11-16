"""Shift – Audio Engine.

Builds the final audio track: pitch-shifted speech + lofi music + ambient.
Handles pause-point silence insertion and layer mixing.
"""

import os
import math
import random
import subprocess

import imageio_ffmpeg
from moviepy import AudioFileClip, CompositeAudioClip, concatenate_audioclips, AudioClip

_SUPPORTED = (".mp3", ".wav", ".aac")


class AudioEngine:
    def __init__(self, music_folder="assets/music", ambient_folder="assets/ambient"):
        self.music_folder = music_folder
        self.ambient_folder = ambient_folder

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _random_file(folder):
        """Pick a random audio file from *folder*, or None."""
        if not os.path.isdir(folder):
            return None
        files = [f for f in os.listdir(folder) if f.lower().endswith(_SUPPORTED)]
        return os.path.join(folder, random.choice(files)) if files else None

    @staticmethod
    def _loop_clip(clip, duration):
        """Loop *clip* to fill *duration* seconds."""
        n = math.ceil(duration / clip.duration)
        return concatenate_audioclips([clip] * n).with_duration(duration)

    @staticmethod
    def _ts_to_seconds(ts):
        """Convert 'MM:SS' or 'HH:MM:SS' → float."""
        parts = [int(p) for p in ts.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    # ── Pitch Shift ──────────────────────────────────────────────────────────

    @staticmethod
    def _pitch_shift(src, dst, semitones=-0.05):
        """Slight pitch shift via ffmpeg asetrate filter."""
        rate = int(44100 * (2 ** (semitones / 12.0)))
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", src,
                 "-af", f"asetrate={rate},atempo={44100 / rate}",
                 dst],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError as exc:
            print(f"Pitch-shift error: {exc.stderr.decode()}")
            return False

    # ── Track Builder ────────────────────────────────────────────────────────

    def build_audio_track(self, original_path, pause_points, output_path, base_duration):
        """Build the composite audio track and write to *output_path*.

        Layers:
            1. Speech (pitch-shifted, with silence inserted at pause points)
            2. Lofi beat        — 10 % volume
            3. Ambient texture  —  5 % volume
        """
        shifted = original_path.replace(".mp3", "_shifted.mp3")
        ok = self._pitch_shift(original_path, shifted)
        
        speech_clip = AudioFileClip(shifted if ok else original_path)
        speech = speech_clip.with_duration(base_duration)
        
        music_clip = None
        ambient_clip = None
        final = None
        clips = []

        try:
            # Insert silence at pause points
            pauses = sorted(
                (pause_points or []),
                key=lambda p: self._ts_to_seconds(p.get("timestamp", "00:00")),
            )

            if pauses:
                segments, cursor = [], 0.0
                for p in pauses:
                    t = self._ts_to_seconds(p.get("timestamp", "00:00"))
                    dur = float(p.get("duration", 3.0))
                    if 0 < t < speech.duration and t > cursor:
                        segments.append(speech.subclipped(cursor, t))
                    segments.append(AudioClip(lambda _: [0, 0], duration=dur))
                    cursor = t
                if cursor < speech.duration:
                    segments.append(speech.subclipped(cursor, speech.duration))
                speech = concatenate_audioclips(segments)

            clips.append(speech)
            total_dur = speech.duration

            # Music layer
            music_path = self._random_file(self.music_folder)
            if music_path:
                music_clip = AudioFileClip(music_path)
                clips.append(
                    self._loop_clip(music_clip, total_dur)
                    .with_volume_scaled(0.05)
                )

            # Ambient layer
            ambient_path = self._random_file(self.ambient_folder)
            if ambient_path:
                ambient_clip = AudioFileClip(ambient_path)
                clips.append(
                    self._loop_clip(ambient_clip, total_dur)
                    .with_volume_scaled(0.04)
                )

            # Mix & write
            final = CompositeAudioClip(clips) if len(clips) > 1 else clips[0]
            final.write_audiofile(output_path, fps=44100, logger=None)

        finally:
            # Close handles (prevents WinError 32 file locks)
            for c in [speech_clip, music_clip, ambient_clip, final, speech] + clips:
                if c is not None:
                    try:
                        c.close()
                    except Exception:
                        pass

            # Cleanup temp shifted file
            try:
                if os.path.exists(shifted):
                    os.remove(shifted)
            except OSError:
                pass

"""Shift – Desktop GUI.

Queue-based video transformer with CustomTkinter.
"""

import os
import threading

import customtkinter as ctk
from tkinter import filedialog

# Suppress harmless MediaPipe C++ telemetry warnings
os.environ["GLOG_minloglevel"] = "2"

from core.processor import VideoProcessor

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

MAX_QUEUE = 10


class ShiftApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Shift – Automated Video Transformer")
        self.geometry("650x780")
        self.resizable(False, False)

        self.queue = []
        self.video_path = ctk.StringVar()
        self.output_folder = ctk.StringVar()
        self._build_ui()

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Title
        ctk.CTkLabel(self, text="Shift",
                     font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(15, 5))

        # Video picker
        ctk.CTkButton(self, text="Select Video (MP4)",
                      command=self._pick_video, width=250).pack(pady=(10, 0))
        ctk.CTkLabel(self, textvariable=self.video_path, text_color="gray",
                     wraplength=600, font=ctk.CTkFont(size=11)).pack()

        # Transcript input (for pause-point tags only)
        ctk.CTkLabel(
            self,
            text="Paste Transcript (optional).  Pause tags: [MM:SS | TITLE | Body...]",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(pady=(8, 0))
        self.txt_transcript = ctk.CTkTextbox(self, height=80, width=580)
        self.txt_transcript.pack(pady=5)

        # Add to queue
        self.btn_add = ctk.CTkButton(
            self, text=f"Add to Queue (0/{MAX_QUEUE})",
            command=self._add_to_queue, width=250,
            fg_color="#2d6a4f", hover_color="#1b4332",
        )
        self.btn_add.pack(pady=5)

        # Queue list
        ctk.CTkLabel(self, text="Queue",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(8, 2))
        self.queue_frame = ctk.CTkScrollableFrame(self, width=580, height=140)
        self.queue_frame.pack(pady=2)
        self._show_empty_queue()

        # Queue actions
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=3)
        ctk.CTkButton(row, text="Remove Last", command=self._remove_last,
                      width=120, fg_color="#6c757d",
                      hover_color="#495057").pack(side="left", padx=5)
        ctk.CTkButton(row, text="Clear All", command=self._clear_queue,
                      width=120, fg_color="#6c757d",
                      hover_color="#495057").pack(side="left", padx=5)

        # Output folder
        ctk.CTkButton(self, text="Select Output Folder",
                      command=self._pick_output, width=250).pack(pady=(10, 0))
        ctk.CTkLabel(self, textvariable=self.output_folder, text_color="gray",
                     wraplength=600, font=ctk.CTkFont(size=11)).pack()

        # Progress
        self.progress_bar = ctk.CTkProgressBar(self, width=500)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(15, 5))

        self.status_label = ctk.CTkLabel(self, text="Ready", text_color="green",
                                         font=ctk.CTkFont(size=12))
        self.status_label.pack()

        # Start
        self.btn_start = ctk.CTkButton(
            self, text="Start Processing All", command=self._start,
            width=300, fg_color="green", hover_color="darkgreen",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.btn_start.pack(pady=12)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _pick_video(self):
        path = filedialog.askopenfilename(
            title="Select Video",
            filetypes=[("Video Files", "*.mp4 *.mov *.avi")],
        )
        if path:
            self.video_path.set(path)

    def _pick_output(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder.set(folder)

    def _add_to_queue(self):
        video = self.video_path.get().strip()
        transcript = self.txt_transcript.get("1.0", "end-1c").strip()
        if not video:
            self._set_status("Select a video first.", "red")
            return
        if len(self.queue) >= MAX_QUEUE:
            self._set_status(f"Queue full (max {MAX_QUEUE}).", "red")
            return

        self.queue.append({"video": video, "transcript": transcript})
        self._refresh_queue()
        self.video_path.set("")
        self.txt_transcript.delete("1.0", "end")
        self._set_status(f"Added — {len(self.queue)}/{MAX_QUEUE} in queue.", "green")

    def _remove_last(self):
        if self.queue:
            name = os.path.basename(self.queue.pop()["video"])
            self._refresh_queue()
            self._set_status(f"Removed: {name}", "gray")

    def _clear_queue(self):
        self.queue.clear()
        self._refresh_queue()
        self._set_status("Queue cleared.", "gray")

    # ── Queue Display ────────────────────────────────────────────────────────

    def _show_empty_queue(self):
        ctk.CTkLabel(self.queue_frame, text="No videos queued yet.",
                     text_color="gray").pack(pady=10)

    def _refresh_queue(self):
        for w in self.queue_frame.winfo_children():
            w.destroy()
        if not self.queue:
            self._show_empty_queue()
        else:
            for i, item in enumerate(self.queue):
                name = os.path.basename(item["video"])
                has_t = "✓ transcript" if item["transcript"] else "no transcript"
                status = item.get("status", "pending")
                colour = {"pending": "gray", "processing": "orange",
                          "done": "green", "error": "red"}.get(status, "gray")
                row = ctk.CTkFrame(self.queue_frame, fg_color="transparent")
                row.pack(fill="x", padx=5, pady=1)
                ctk.CTkLabel(row, text=f"{i + 1}.", width=25,
                             font=ctk.CTkFont(size=12)).pack(side="left")
                ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=12),
                             anchor="w").pack(side="left", padx=(5, 10))
                ctk.CTkLabel(row, text=f"[{has_t}]", text_color="gray",
                             font=ctk.CTkFont(size=11)).pack(side="left")
                ctk.CTkLabel(row, text=status.upper(), text_color=colour,
                             font=ctk.CTkFont(size=11, weight="bold")
                             ).pack(side="right", padx=10)
        self.btn_add.configure(text=f"Add to Queue ({len(self.queue)}/{MAX_QUEUE})")

    # ── Processing ───────────────────────────────────────────────────────────

    def _refresh_queue_safe(self):
        self.after(0, self._refresh_queue)

    def _set_status(self, text, colour="orange"):
        self.after(0, lambda t=text, c=colour: self.status_label.configure(text=t, text_color=c))

    def _process_thread(self):
        total = len(self.queue)
        for idx, item in enumerate(self.queue):
            base = os.path.splitext(os.path.basename(item["video"]))[0]
            out = os.path.join(self.output_folder.get(), f"{base}_shift.mp4")

            item["status"] = "processing"
            self._refresh_queue_safe()
            self._set_status(f"Processing {idx + 1}/{total}: {os.path.basename(item['video'])}")

            try:
                proc = VideoProcessor(item["video"], item["transcript"], out)

                def cb(val, _i=idx, _t=total):
                    self.after(0, lambda v=val: self.progress_bar.set((_i + v) / _t))

                proc.process(progress_callback=cb)
                item["status"] = "done"
            except Exception as exc:
                item["status"] = "error"
                print(f"Error processing {base}: {exc}")

            self._refresh_queue_safe()

        self._set_status(f"All {total} videos complete!", "green")
        self.after(0, lambda: self.progress_bar.set(1.0))
        self.after(0, lambda: self.btn_start.configure(state="normal"))

    def _start(self):
        if not self.queue:
            self._set_status("Queue is empty — add videos first.", "red")
            return
        if not self.output_folder.get():
            self._set_status("Select an output folder first.", "red")
            return
        self.btn_start.configure(state="disabled")
        self.progress_bar.set(0)
        t = threading.Thread(target=self._process_thread, daemon=True)
        t.start()


if __name__ == "__main__":
    ShiftApp().mainloop()

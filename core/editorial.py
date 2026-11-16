"""Shift – Editorial Engine.

Renders animated "Fact Bubble" overlays during freeze-frame pauses
(trivia, fan-theories, reactions, commentary).
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont




class EditorialEngine:
    def __init__(self, font_path="arial.ttf"):
        self._font_path = font_path

    def _load_font(self, size):
        try:
            return ImageFont.truetype(self._font_path, size)
        except IOError:
            return ImageFont.load_default()

    def render_fact_bubble(self, frame, text, title, progress, bg_color):
        """Draw an animated fact bubble on *frame*.

        Args:
            frame:       BGR numpy array.
            text:        Body text for the bubble.
            title:       Title for the bubble.
            progress:    0.0 → 1.0 (slide-in → hold → slide-out).
            bg_color:    RGBA tuple for the bubble background.
        """
        h, w = frame.shape[:2]
        pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil, "RGBA")

        # Slide animation
        y_offset, alpha = 0, 1.0
        if progress < 0.1:
            t = progress / 0.1
            y_offset = int((1 - t) * 50)
            alpha = t
        elif progress > 0.9:
            t = (progress - 0.9) / 0.1
            y_offset = int(t * 50)
            alpha = 1.0 - t

        # Dynamic Layout Parameters
        max_box_w = int(w * 0.9)
        max_box_h = int(h * 0.8)
        padding_x = 40
        padding_y = 30
        
        title_sz = 60
        body_sz = 45
        
        while title_sz >= 15:
            font_title = self._load_font(title_sz)
            font_body = self._load_font(body_sz)
            
            def get_text_size(txt, fnt):
                if hasattr(draw, "textbbox"):
                    bbox = draw.textbbox((0, 0), txt, font=fnt)
                    return bbox[2] - bbox[0], bbox[3] - bbox[1]
                else:
                    # Fallback for older Pillow versions
                    try:
                        return fnt.getsize(txt)
                    except AttributeError:
                        bbox = fnt.getbbox(txt)
                        return bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            title_w, title_h = get_text_size(title, font_title)
            
            max_text_w = max_box_w - (padding_x * 2)
            lines = []
            line = ""
            for word in text.split():
                test = line + word + " "
                test_w, _ = get_text_size(test, font_body)
                if test_w > max_text_w and line != "":
                    lines.append(line)
                    line = word + " "
                else:
                    line = test
            if line:
                lines.append(line)
                
            body_w = 0
            _, line_h = get_text_size("Ay", font_body)
            line_spacing = line_h * 1.5
            
            for ln in lines:
                lw, _ = get_text_size(ln, font_body)
                body_w = max(body_w, lw)
                
            body_h = len(lines) * line_spacing
            
            content_w = max(title_w, body_w)
            spacing = padding_y if lines else 0
            
            total_w = content_w + (padding_x * 2)
            total_h = title_h + spacing + body_h + (padding_y * 2)
            
            if total_w <= max_box_w and total_h <= max_box_h:
                break
                
            title_sz -= 2
            body_sz -= 2

        box_w = int(total_w)
        box_h = int(total_h)
        
        # Center position
        x1 = (w - box_w) // 2
        y1 = (h - box_h) // 2 + y_offset

        bg = bg_color
        fill = (bg[0], bg[1], bg[2], int(bg[3] * alpha))
        text_col = (255, 255, 255, int(255 * alpha))

        try:
            draw.rounded_rectangle([x1, y1, x1 + box_w, y1 + box_h],
                                   radius=20, fill=fill)
        except AttributeError:
            draw.rectangle([x1, y1, x1 + box_w, y1 + box_h], fill=fill)

        draw.text((x1 + padding_x, y1 + padding_y), title, font=font_title, fill=text_col)

        y_text = y1 + padding_y + title_h + spacing
        for ln in lines:
            draw.text((x1 + padding_x, y_text), ln, font=font_body, fill=text_col)
            y_text += line_spacing

        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

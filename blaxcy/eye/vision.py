"""Local OCR / computer-vision perception.

Uses Tesseract (via pytesseract) for text and OpenCV for region/change analysis.
It is designed for *targeted* use — OCR a specific region on demand, not the
whole screen on every frame — so it stays cheap and never escalates to an
expensive vision model for a tiny change.

Availability is detected honestly: if a dependency is missing, `capabilities()`
says so and the affected methods degrade rather than pretend.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any


@dataclass
class TextBox:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int
    kind: str = "change"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _load_image(png_bytes: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(png_bytes)).convert("RGB")


class VisionBackend:
    name = "vision"

    def __init__(self) -> None:
        self._pytesseract = None
        self._cv2 = None
        self._numpy = None
        try:
            import pytesseract

            self._pytesseract = pytesseract
        except Exception:  # noqa: BLE001
            self._pytesseract = None
        try:
            import cv2

            self._cv2 = cv2
        except Exception:  # noqa: BLE001
            self._cv2 = None
        try:
            import numpy

            self._numpy = numpy
        except Exception:  # noqa: BLE001
            self._numpy = None

    # capability ------------------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        ocr = False
        version = None
        if self._pytesseract is not None:
            try:
                version = str(self._pytesseract.get_tesseract_version())
                ocr = True
            except Exception:  # noqa: BLE001
                ocr = False
        return {"ocr": ocr, "tesseract": version, "cv": self._cv2 is not None,
                "numpy": self._numpy is not None}

    def is_available(self) -> bool:
        caps = self.capabilities()
        return bool(caps["ocr"] or caps["cv"])

    # region helpers --------------------------------------------------------
    @staticmethod
    def _crop(image, region: tuple[int, int, int, int] | None):
        if region is None:
            return image
        x, y, w, h = region
        x = max(0, x); y = max(0, y)
        return image.crop((x, y, x + max(1, w), y + max(1, h)))

    # OCR -------------------------------------------------------------------
    def ocr(self, png_bytes: bytes, region: tuple[int, int, int, int] | None = None,
            psm: int = 6) -> str:
        if self._pytesseract is None:
            return ""
        image = self._crop(_load_image(png_bytes), region)
        try:
            return str(self._pytesseract.image_to_string(image, config=f"--psm {psm}")).strip()
        except Exception:  # noqa: BLE001
            return ""

    def text_boxes(self, png_bytes: bytes,
                   region: tuple[int, int, int, int] | None = None,
                   min_conf: float = 40.0) -> list[TextBox]:
        if self._pytesseract is None:
            return []
        image = self._crop(_load_image(png_bytes), region)
        offset_x = region[0] if region else 0
        offset_y = region[1] if region else 0
        try:
            data = self._pytesseract.image_to_data(
                image, output_type=self._pytesseract.Output.DICT)
        except Exception:  # noqa: BLE001
            return []
        boxes: list[TextBox] = []
        for i in range(len(data["text"])):
            text = (data["text"][i] or "").strip()
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if not text or conf < min_conf:
                continue
            boxes.append(TextBox(
                text=text, confidence=conf,
                x=offset_x + int(data["left"][i]), y=offset_y + int(data["top"][i]),
                width=int(data["width"][i]), height=int(data["height"][i])))
        return boxes

    def find_text(self, png_bytes: bytes, needle: str, *,
                  region: tuple[int, int, int, int] | None = None,
                  min_conf: float = 40.0) -> list[TextBox]:
        needle_l = needle.lower()
        return [b for b in self.text_boxes(png_bytes, region, min_conf)
                if needle_l in b.text.lower()]

    def contains_text(self, png_bytes: bytes, needle: str, **kwargs: Any) -> bool:
        return bool(self.find_text(png_bytes, needle, **kwargs))

    # CV --------------------------------------------------------------------
    def detect_ui_regions(self, png_bytes: bytes,
                          region: tuple[int, int, int, int] | None = None,
                          min_area: int = 900) -> list[Region]:
        """Detect rectangular UI-ish regions (buttons/panels) via contours."""
        if self._cv2 is None or self._numpy is None:
            return []
        image = self._crop(_load_image(png_bytes), region)
        arr = self._numpy.array(image)
        gray = self._cv2.cvtColor(arr, self._cv2.COLOR_RGB2GRAY)
        edges = self._cv2.Canny(gray, 50, 150)
        contours, _ = self._cv2.findContours(edges, self._cv2.RETR_EXTERNAL,
                                             self._cv2.CHAIN_APPROX_SIMPLE)
        out: list[Region] = []
        for c in contours:
            x, y, w, h = self._cv2.boundingRect(c)
            if w * h < min_area:
                continue
            out.append(Region(x=x, y=y, width=w, height=h, kind="ui-region"))
        return sorted(out, key=lambda r: r.width * r.height, reverse=True)[:50]

    def diff_regions(self, prev_png: bytes, cur_png: bytes, *,
                     region: tuple[int, int, int, int] | None = None,
                     threshold: int = 25, min_area: int = 400) -> list[Region]:
        """Return bounding boxes of changed areas between two frames."""
        if self._cv2 is None or self._numpy is None:
            return []
        a = self._numpy.array(self._crop(_load_image(prev_png), region))
        b = self._numpy.array(self._crop(_load_image(cur_png), region))
        if a.shape != b.shape:
            return [Region(*(region or (0, 0, 0, 0)), kind="change", detail="size-change")]  # type: ignore[arg-type]
        gray_a = self._cv2.cvtColor(a, self._cv2.COLOR_RGB2GRAY)
        gray_b = self._cv2.cvtColor(b, self._cv2.COLOR_RGB2GRAY)
        delta = self._cv2.absdiff(gray_a, gray_b)
        _, mask = self._cv2.threshold(delta, threshold, 255, self._cv2.THRESH_BINARY)
        mask = self._cv2.dilate(mask, None, iterations=2)
        contours, _ = self._cv2.findContours(mask, self._cv2.RETR_EXTERNAL,
                                             self._cv2.CHAIN_APPROX_SIMPLE)
        ox = region[0] if region else 0
        oy = region[1] if region else 0
        out: list[Region] = []
        for c in contours:
            x, y, w, h = self._cv2.boundingRect(c)
            if w * h < min_area:
                continue
            out.append(Region(x=ox + x, y=oy + y, width=w, height=h, kind="change"))
        return sorted(out, key=lambda r: r.width * r.height, reverse=True)[:30]

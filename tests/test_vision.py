"""Tests for on-demand local OCR / CV perception (requirement C9).

Tests render synthetic images with Pillow so they never read the real screen.
OCR/CV assertions skip cleanly when the optional dependency is missing, so the
suite stays honest on hosts without Tesseract or OpenCV.
"""

from __future__ import annotations

import io
import time

import pytest
from PIL import Image, ImageDraw

from blaxcy.eye import Eye, FakeEyeBackend
from blaxcy.eye.vision import Region, TextBox, VisionBackend
from blaxcy.models import ScreenState


def _render(text: str, size: tuple[int, int] = (600, 120), scale: int = 3) -> bytes:
    img = Image.new("RGB", size, (255, 255, 255))
    ImageDraw.Draw(img).text((12, 20), text, fill=(0, 0, 0))
    img = img.resize((size[0] * scale, size[1] * scale))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def vision() -> VisionBackend:
    return VisionBackend()


def test_capabilities_report_honestly(vision: VisionBackend):
    caps = vision.capabilities()
    assert set(caps) == {"ocr", "tesseract", "cv", "numpy"}
    assert isinstance(caps["ocr"], bool) and isinstance(caps["cv"], bool)


def test_ocr_reads_synthetic_text(vision: VisionBackend):
    if not vision.capabilities()["ocr"]:
        pytest.skip("tesseract not available")
    # Normalise whitespace: OCR may split "BLAXCY" into "BLAXC Y".
    text = "".join(vision.ocr(_render("BLAXCY PLAYER")).split()).upper()
    assert "BLAXCY" in text


def test_text_boxes_and_find_text_are_positioned(vision: VisionBackend):
    if not vision.capabilities()["ocr"]:
        pytest.skip("tesseract not available")
    png = _render("BLAXCY PLAYER")
    boxes = vision.text_boxes(png, min_conf=30)
    assert boxes and all(isinstance(b, TextBox) for b in boxes)
    hits = vision.find_text(png, "PLAYER", min_conf=30)
    assert hits and all(isinstance(b, TextBox) for b in hits)
    assert vision.contains_text(png, "PLAYER", min_conf=30)
    assert not vision.contains_text(png, "ZZQXNOTPRESENT", min_conf=30)


def test_diff_regions_detects_change(vision: VisionBackend):
    if not vision.capabilities()["cv"]:
        pytest.skip("opencv not available")
    blank = _render("", size=(200, 100))
    changed = _render("XX", size=(200, 100))
    regions = vision.diff_regions(blank, changed)
    assert regions and all(isinstance(r, Region) for r in regions)
    assert vision.diff_regions(blank, blank) == []


def test_detect_ui_regions_returns_list(vision: VisionBackend):
    if not vision.capabilities()["cv"]:
        pytest.skip("opencv not available")
    regions = vision.detect_ui_regions(_render("HELLO", size=(200, 100), scale=1))
    assert isinstance(regions, list)
    assert all(isinstance(r, Region) for r in regions)


def test_missing_dependencies_degrade_without_raising(vision: VisionBackend):
    vision._pytesseract = None
    assert vision.ocr(_render("HELLO")) == ""
    assert vision.text_boxes(_render("HELLO")) == []
    vision._cv2 = None
    vision._numpy = None
    png = _render("HELLO", size=(100, 50), scale=1)
    assert vision.diff_regions(png, png) == []
    assert vision.detect_ui_regions(png) == []


class _StubVision:
    name = "stub"

    def capabilities(self) -> dict:
        return {"ocr": True, "cv": True}

    def is_available(self) -> bool:
        return True

    def ocr(self, png: bytes, region=None) -> str:
        return f"STUB:{len(png)}"

    def find_text(self, png: bytes, needle: str, region=None, min_conf: float = 40.0):
        return [TextBox(needle, 99.0, 1, 2, 3, 4)]

    def detect_ui_regions(self, png: bytes, region=None):
        return [Region(0, 0, 1, 1)]


def _frame_factory(seq: int) -> ScreenState:
    return ScreenState(timestamp=time.time(), width=1, height=1, frame_bytes=b"abc")


def test_eye_vision_hooks_use_frame_and_degrade_without_backend():
    eye = Eye(FakeEyeBackend(factory=_frame_factory), interval_s=0.005, vision=_StubVision())
    eye.start()
    try:
        eye.snapshot(timeout=1.0)
        assert eye.vision_capabilities()["available"] is True
        assert eye.ocr().startswith("STUB:")
        assert eye.contains_text("PLAYER")
        assert eye.ui_regions()
    finally:
        eye.stop()

    bare = Eye(FakeEyeBackend(factory=_frame_factory), interval_s=0.005)
    bare.start()
    try:
        bare.snapshot(timeout=1.0)
        assert bare.vision_capabilities() == {"ocr": False, "cv": False, "available": False}
        assert bare.ocr() == ""
        assert bare.find_text("x") == []
        assert bare.ui_regions() == []
    finally:
        bare.stop()

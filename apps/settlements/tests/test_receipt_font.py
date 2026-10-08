"""The receipt renderer must use the small CJK font packaged in Linux images."""

from pathlib import Path

from apps.settlements.services import receipts


def test_receipt_font_uses_packaged_wqy_font(monkeypatch):
    font_path = Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
    loaded = []
    sentinel = object()

    monkeypatch.setattr(Path, "is_file", lambda path: path == font_path)
    monkeypatch.setattr(
        receipts.ImageFont,
        "truetype",
        lambda path, size: loaded.append((path, size)) or sentinel,
    )

    assert receipts._font(28) is sentinel
    assert loaded == [(str(font_path), 28)]

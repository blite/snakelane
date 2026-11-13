from __future__ import annotations

from pathlib import Path

from snakelane.screenshots.framing.style import Style, for_text, theme_of


def test_a_thai_caption_switches_to_a_font_with_thai() -> None:
    style = Style(theme=theme_of("dusk"))
    thai = for_text(style, ["กล้องทั้งหมดของคุณ", "==ไม่มีคลาวด์=="])
    assert thai.theme.font.endswith("SukhumvitSet.ttc")
    assert Path(thai.theme.font).exists()  # ships with macOS
    assert thai.theme.font_face == "Bold"
    assert thai.theme.accent == style.theme.accent  # only the font changes


def test_a_latin_or_cyrillic_caption_keeps_the_theme_font() -> None:
    style = Style(theme=theme_of("dusk"))
    assert for_text(style, "Все ваши камеры. ==Без облака.==") is style
    assert for_text(style, "Tất cả camera của bạn.") is style

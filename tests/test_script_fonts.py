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


def test_avenir_captions_switch_where_avenir_has_no_letters() -> None:
    # felt's Avenir Next Heavy has Latin, French and Portuguese, but no Cyrillic, Korean or Arabic,
    # and not Vietnamese's stacked marks.
    style = Style(theme=theme_of("felt"))
    assert for_text(style, "Sans pub. Aucune. Nenhum anúncio.") is style
    assert for_text(style, "Без рекламы").theme.font.endswith("SFNS.ttf")
    assert for_text(style, "Không quảng cáo").theme.font.endswith("SFNS.ttf")
    korean = for_text(style, "광고 없음")
    assert korean.theme.font.endswith("AppleSDGothicNeo.ttc") and korean.theme.font_face == "Heavy"
    for switched in (for_text(style, "Без рекламы"), korean):
        assert Path(switched.theme.font).exists()
        assert switched.theme.accent == style.theme.accent

"""`snakelane frame` refuses a deck that is a captioned shot short."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane import project
from snakelane.screenshots import frame

from .helpers import make_app

Image = pytest.importorskip("PIL.Image")


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return make_app(tmp_path, screenshots={"frame": "snakelane",
                                           "framing": {"captions": {"1": "One", "2": "Two", "3": "Three"}}})


def capture(app: project.App, deck: str, n: int, locale: str = "en-US") -> None:
    path = project.DeckTree.for_deck(app, deck).raw(locale) / f"ss-{n:02}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1284, 2778), "white").save(path)


def test_a_caption_no_deck_produced_fails_the_run(app: project.App) -> None:
    capture(app, "iphone", 1)
    capture(app, "iphone", 2)
    with pytest.raises(SystemExit, match=r"captioned shot\(s\) 3 .* have no capture"):
        frame.frame_deck(app, "en-US")


def test_a_shot_one_platform_leaves_out_is_fine(app: project.App) -> None:
    for n in (1, 2, 3):
        capture(app, "iphone", n)
    capture(app, "ipad", 1)
    assert frame.frame_deck(app, "en-US") == 4


def test_framing_writes_jpeg(app: project.App) -> None:
    for n in (1, 2, 3):
        capture(app, "iphone", n)
    frame.frame_deck(app, "en-US")
    framed = project.DeckTree.for_deck(app, "iphone").framed("en-US")
    assert sorted(p.name for p in framed.iterdir()) == ["ss-01.jpg", "ss-02.jpg", "ss-03.jpg"]
    app.config["screenshots"]["framing"]["format"] = "png"
    with pytest.raises(SystemExit, match="unknown key"):
        frame.frame_deck(app, "en-US")


def styled(app: project.App, **framing: object) -> None:
    app.config["screenshots"]["framing"].update(framing)


def test_rotate_puts_a_landscape_capture_in_a_portrait_deck(app: project.App) -> None:
    capture(app, "iphone", 1)
    capture(app, "iphone", 3)
    raw = project.DeckTree.for_deck(app, "iphone").raw("en-US") / "ss-02.png"
    landscape = Image.new("RGB", (2778, 1284), "white")
    landscape.paste((255, 0, 0), (0, 0, 100, 1284))  # the capture's left edge, in red
    landscape.save(raw)
    styled(app, targets={"iphone": [1284, 2778]})
    with pytest.raises(SystemExit, match="landscape, and the deck is portrait"):
        frame.frame_deck(app, "en-US")
    styled(app, slots={"2": {"rotate": 90, "caption": {"shape": "callout", "callout": {"edge": "right"}}}})
    frame.frame_deck(app, "en-US")
    with Image.open(project.DeckTree.for_deck(app, "iphone").framed("en-US") / "ss-02.jpg") as out:
        assert out.size == (1284, 2778)
        assert out.getpixel((640, 2740))[0] > 200, "anticlockwise: the left edge is now the bottom"


def test_exif_orientation_is_applied_before_rotating(app: project.App, tmp_path: Path) -> None:
    raw = project.DeckTree.for_deck(app, "iphone").raw("en-US")
    raw.mkdir(parents=True, exist_ok=True)
    pixels = Image.new("RGB", (1284, 2778), "white")
    exif = Image.Exif()
    exif[274] = 8  # stored portrait, shown landscape: how a landscape XCUIScreen capture arrives
    pixels.save(raw / "ss-02.jpg", exif=exif)
    capture(app, "iphone", 1)
    capture(app, "iphone", 3)
    styled(app, slots={"2": {"rotate": 90, "caption": {"shape": "callout"}}})
    frame.frame_deck(app, "en-US")  # without the EXIF turn this would be a double turn: landscape


def test_the_styled_band_and_callout_keep_the_size_and_are_deterministic(app: project.App) -> None:
    for n in (1, 2, 3):
        capture(app, "iphone", n)
    styled(app, layout="full-bleed", caption={"shape": "arch"},
           theme={"fill": ["#1A7540", "#053D1F"], "panel": {"color": "#298C4F"},
                  "lip": {"color": "#BF8F2E", "highlight": "#FCD978", "height": 33},
                  "shadow": {"offset": [0, 17]}, "text_shadow": "#001F0A"},
           captions={"1": "No ads.\nNot one.", "2": "Play in<br>landscape", "3": "Three"},
           slots={"2": {"caption": {"shape": "callout", "callout": {"edge": "left", "lip": 15}}}})
    framed = project.DeckTree.for_deck(app, "iphone").framed("en-US")
    frame.frame_deck(app, "en-US")
    first = {p.name: p.read_bytes() for p in framed.iterdir()}
    frame.frame_deck(app, "en-US")
    assert first == {p.name: p.read_bytes() for p in framed.iterdir()}, "a reframe must not churn git"
    with Image.open(framed / "ss-01.jpg") as out:
        assert out.size == (1284, 2778)
        # The band is 278 px deep at the sides and 50 px less in the middle.
        middle, side = out.getpixel((642, 255)), out.getpixel((5, 255))
        assert middle != side, "the arch's edge is higher in the middle than at the sides"


@pytest.mark.parametrize(("framing", "message"), [
    ({"caption": {"shape": "wave"}}, "caption.shape"),
    ({"band_shape": "arch"}, "unknown key"),
    ({"layout": "overlay"}, "framing.layout must be one of"),
    ({"theme": "plaid"}, "no theme 'plaid'"),
    ({"theme": {"base": "felt", "colour": "#000000"}}, "unknown key"),
    ({"slots": {"1": {"rotation": 90}}}, r"framing\.slots\.1"),
    ({"slots": {"1": {"rotate": 45}}}, "rotate must be"),
    ({"slots": {"1": {"caption": {"shape": "callout", "callout": {"side": "right"}}}}}, "unknown key"),
    ({"slots": {"1": {"caption": {"shape": "callout", "callout": {"edge": "top"}}}}}, '"edge" must be'),
])
def test_bad_framing_settings_say_which(app: project.App, framing: dict, message: str) -> None:
    for n in (1, 2, 3):
        capture(app, "iphone", n)
    styled(app, **framing)
    with pytest.raises(SystemExit, match=message):
        frame.frame_deck(app, "en-US")


def test_a_bottom_band_mirrors_the_top_one(app: project.App) -> None:
    for n in (1, 2, 3):
        capture(app, "iphone", n)
    styled(app, layout="full-bleed", theme={"fill": "#14141F", "rule": {"color": "#C9A24A", "height": 3}},
           slots={"2": {"caption": {"position": "bottom"}}})
    frame.frame_deck(app, "en-US")
    framed = project.DeckTree.for_deck(app, "iphone").framed("en-US")
    with Image.open(framed / "ss-01.jpg") as top, Image.open(framed / "ss-02.jpg") as bottom:
        assert top.size == bottom.size == (1284, 2778)
        assert sum(top.getpixel((5, 5))) < 100 and sum(top.getpixel((5, 2770))) > 600
        assert sum(bottom.getpixel((5, 5))) > 600 and sum(bottom.getpixel((5, 2770))) < 100
        seam = 2778 - round(2778 * 0.10) - 2  # the rule sits on the band's capture side
        assert bottom.getpixel((5, seam))[0] > 150, "the rule is above a bottom band"


def test_band_position_can_differ_per_deck(app: project.App) -> None:
    for n in (1, 2, 3):
        capture(app, "iphone", n)
    capture(app, "ipad", 1)
    styled(app, layout="full-bleed", caption={"position": {"iphone": "top", "ipad": "bottom"}, "shape": "arch"},
           theme={"lip": {"color": "#BF8F2E", "height": 20}, "shadow": {"offset": [0, 10]}})
    frame.frame_deck(app, "en-US")
    with Image.open(project.DeckTree.for_deck(app, "ipad").framed("en-US") / "ss-01.jpg") as ipad:
        assert sum(ipad.getpixel((5, 5))) > 600 and sum(ipad.getpixel((5, 2770))) < 100
    styled(app, caption={"position": {"watch": "bottom"}})
    with pytest.raises(SystemExit, match="unknown deck"):
        frame.frame_deck(app, "en-US")
    styled(app, caption={"position": "middle"})
    with pytest.raises(SystemExit, match='"top" or "bottom"'):
        frame.frame_deck(app, "en-US")


def test_the_banner_handoff_is_the_depth_the_band_is_drawn_at(app: project.App) -> None:
    styled(app, layout="full-bleed", caption={"shape": "arch", "depth": 0.158},
           theme={"lip": {"color": "#BF8F2E", "height": 33}},
           captions={"1": "NO ADS.\nNOT ONE.", "2": "PLAY", "4": "BOTTOM"},
           slots={"2": {"rotate": 90, "caption": {"shape": "callout"}}, "4": {"caption": {"position": "bottom"}}})
    handoff = frame.banner_handoff(app, "iphone")
    # Solitaire kept 0.17 by hand in its app and its test; snakelane now derives it.
    assert handoff["position"] == "top" and handoff["depth"] == pytest.approx(0.17, abs=0.001)
    assert handoff["slots"]["2"] == {"position": "none", "depth": 0}
    assert handoff["slots"]["4"]["position"] == "bottom"
    assert handoff["slots"]["4"]["depth"] == handoff["depth"], "the same band, mirrored"
    capture(app, "iphone", 1)
    capture(app, "iphone", 4)
    raw = project.DeckTree.for_deck(app, "iphone").raw("en-US")
    Image.new("RGB", (2778, 1284), "white").save(raw / "ss-02.png")
    frame.frame_deck(app, "en-US")
    with Image.open(project.DeckTree.for_deck(app, "iphone").framed("en-US") / "ss-01.jpg") as out:
        side = round(handoff["depth"] * 2778)
        assert out.getpixel((5, side - 3)) != (255, 255, 255), "the band reaches the handed-over depth"
        assert out.getpixel((5, side + 3)) == (255, 255, 255), "and stops there"


def test_a_stacked_layout_needs_no_reserve(app: project.App) -> None:
    assert {s["position"] for s in frame.banner_handoff(app, "iphone")["slots"].values()} == {"none"}


def test_key_art_is_cropped_by_bias_and_reserves_nothing(app: project.App) -> None:
    styled(app, layout="full-bleed", captions={"1": "One", "9": "Key art"},
           slots={"9": {"bias": 0.62}})
    handoff = frame.banner_handoff(app, "iphone")
    assert handoff["slots"]["1"]["position"] == "top"
    assert handoff["slots"]["9"] == {"position": "none", "depth": 0}, "key art isn't a screen the app lays out"

def test_caption_marks_parse_into_runs() -> None:
    from snakelane.screenshots.framing.draw import Run, parse_caption
    from snakelane.screenshots.framing.style import theme_of

    theme = theme_of({"colors": {"gold": "#FFC46B"}})
    assert parse_caption(theme, "**Every** *hike*, ==logged== [today]{gold}\\*") == [[
        Run("Every", bold=True), Run(" "), Run("hike", italic=True), Run(", "),
        Run("logged", colour="accent"), Run(" "), Run("today", colour="gold"), Run("*")]]
    assert parse_caption(theme, "***both***") == [[Run("both", bold=True, italic=True)]]
    assert parse_caption(theme_of("felt"), "No ads.<br>==Not one.==")[1] == [Run("NOT ONE.", colour="accent")]
    assert parse_caption(theme, "[a]{#FF0000} [b] c") == [[Run("a", colour="#FF0000"), Run(" [b] c")]]


@pytest.mark.parametrize(("caption", "theme", "message"), [
    ("an **unclosed", None, r"\*\* unclosed"),
    ("==half", None, "== unclosed"),
    ("*italic*", "campfire", "has no italic"),
    ("[gold]{gold}", None, "no colour 'gold'"),
])
def test_bad_caption_marks_say_what_to_fix(app: project.App, caption: str, theme: str | None, message: str) -> None:
    capture(app, "iphone", 1)
    styled(app, captions={"1": caption}, **({"theme": theme} if theme else {}))
    with pytest.raises(SystemExit, match=message):
        frame.frame_deck(app, "en-US")


def test_mixed_faces_render_and_lists_are_lines(app: project.App, capsys: pytest.CaptureFixture[str]) -> None:
    capture(app, "iphone", 1)
    styled(app, theme="dusk", captions={"1": ["**Every** *hike*,", "==logged=="]})
    frame.frame_deck(app, "en-US")
    assert "use *word*" not in capsys.readouterr().out
    styled(app, captions={"1": "Every *hike*"})
    frame.frame_deck(app, "en-US")
    assert "the accent colour is ==word==" in capsys.readouterr().out, "old accent syntax gets a hint"


def test_platform_frames_only_that_platforms_decks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `frame --platform macos` once re-framed the iOS decks from stale raws as well.
    app = make_app(tmp_path, platforms=["ios", "macos"],
                   screenshots={"frame": "snakelane", "framing": {"captions": {"1": "One"}}})
    capture(app, "iphone", 1)
    mac = project.DeckTree.for_deck(app, "mac").raw("en-US") / "ss-01.png"
    mac.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2880, 1800), "white").save(mac)
    monkeypatch.chdir(tmp_path)
    frame.frame_command(platform="macos")
    assert (project.DeckTree.for_deck(app, "mac").framed("en-US") / "ss-01.jpg").exists()
    assert not project.DeckTree.for_deck(app, "iphone").framed("en-US").exists()


def by_locale(tmp_path: Path, captions: dict, **config: object) -> project.App:
    return make_app(tmp_path, locales=["en-US", "de-DE", "fr-FR"], **config,
                    screenshots={"frame": "snakelane", "framing": {"captions": captions}})


def test_one_caption_map_serves_every_locale(app: project.App, capsys: pytest.CaptureFixture[str]) -> None:
    assert frame.captions(app, frame.framing(app), "de-DE") == {1: "One", 2: "Two", 3: "Three"}
    assert frame.captions(app, frame.framing(app), None) == frame.captions(app, frame.framing(app), "en-US")
    assert frame.fallback_note(app, frame.framing(app), "de-DE") is None
    capture(app, "iphone", 1, "de-DE")
    capture(app, "iphone", 2, "de-DE")
    capture(app, "iphone", 3, "de-DE")
    assert frame.frame_deck(app, "de-DE") == 3
    assert "“One”" in capsys.readouterr().out


def test_per_locale_captions_pick_the_locale(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    app = by_locale(tmp_path, {"en-US": {"1": "One", 2: ["Two", "lines"]}, "de-DE": {"1": "Eins", "2": "Zwei"}})
    cfg = frame.framing(app)
    assert frame.captions(app, cfg, "de-DE") == {1: "Eins", 2: "Zwei"}
    assert frame.captions(app, cfg, "en-US") == {1: "One", 2: "Two\nlines"}
    for n in (1, 2):
        capture(app, "iphone", n, "de-DE")
    frame.frame_deck(app, "de-DE")
    out = capsys.readouterr().out
    assert "“Eins”" in out and "“One”" not in out and "using" not in out
    assert frame.banner_handoff(app, "iphone", "de-DE")["slots"].keys() == {"1", "2"}


def test_a_locale_without_captions_gets_the_primarys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    app = by_locale(tmp_path, {"de-DE": {"1": "Eins"}, "fr-FR": {"1": "Un"}}, primary_locale="fr-FR")
    assert frame.captions(app, frame.framing(app), "en-US") == {1: "Un"}
    capture(app, "iphone", 1, "en-US")
    frame.frame_deck(app, "en-US")
    out = capsys.readouterr().out
    assert "en-US has none" in out and "using fr-FR's" in out and "“Un”" in out


def test_a_locale_map_must_caption_every_capture(tmp_path: Path) -> None:
    app = by_locale(tmp_path, {"en-US": {"1": "One", "2": "Two"}, "de-DE": {"1": "Eins"}})
    capture(app, "iphone", 1, "de-DE")
    capture(app, "iphone", 2, "de-DE")
    with pytest.raises(SystemExit, match="no caption for shot 2"):
        frame.frame_deck(app, "de-DE")


def test_mixing_the_two_caption_forms_is_an_error(tmp_path: Path) -> None:
    app = by_locale(tmp_path, {"1": "One", "de-DE": {"1": "Eins"}})
    with pytest.raises(SystemExit, match="mixes shot numbers"):
        frame.captions(app, frame.framing(app), "en-US")


def test_no_captions_for_the_locale_or_the_primary_is_an_error(tmp_path: Path) -> None:
    app = by_locale(tmp_path, {"de-DE": {"1": "Eins"}})
    with pytest.raises(SystemExit, match="no captions for fr-FR, nor for the primary locale en-US"):
        frame.captions(app, frame.framing(app), "fr-FR")


def test_every_locales_marks_are_checked(tmp_path: Path) -> None:
    app = by_locale(tmp_path, {"en-US": {"1": "One"}, "de-DE": {"1": "==Eins"}})
    capture(app, "iphone", 1, "en-US")
    with pytest.raises(SystemExit, match="== unclosed"):
        frame.frame_deck(app, "en-US")

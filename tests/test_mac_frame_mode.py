"""`screenshots.mac.frame` gives the Mac deck its own caption mode."""

from __future__ import annotations

from snakelane.screenshots.shoot import frame_mode


def test_mac_frame_overrides_the_top_level_mode_for_the_mac_only() -> None:
    config = {"frame": "test", "mac": {"frame": "snakelane"}}
    assert frame_mode(config, "macos") == "snakelane"
    assert frame_mode(config, "ios") == "test"
    assert frame_mode(config) == "test"


def test_without_mac_frame_the_mac_follows_the_top_level_mode() -> None:
    assert frame_mode({"frame": "test", "mac": {}}, "macos") == "test"
    assert frame_mode({"framing": {"captions": {"1": "x"}}}, "macos") == "snakelane"


def test_frame_on_a_mac_only_app_honours_mac_frame_without_platform(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from snakelane.screenshots import frame, shoot

    resolved = SimpleNamespace(config={"platforms": ["macos"], "screenshots": {"frame": "test",
                                                                               "mac": {"frame": "snakelane"}}})
    monkeypatch.setattr(frame, "resolve_app", lambda _: resolved)
    monkeypatch.setattr(shoot, "reframe_with_test", lambda _: (_ for _ in ()).throw(AssertionError("reframed")))
    framed = []
    monkeypatch.setattr(frame, "frame_deck", lambda *a, **k: framed.append(a))
    frame.frame_command(app=None, locale=None, deck=None, theme=None, list_themes=False, device=None,
                        platform=None, dry_run=False)
    assert framed

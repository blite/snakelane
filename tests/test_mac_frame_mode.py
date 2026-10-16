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

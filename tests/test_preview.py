"""`snakelane preview` offline: the MP4 reader, Apple's preview checks, the config, caption timing,
the test's events and the band overlay. Recording needs a simulator and is not tested here."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from snakelane import project
from snakelane.screenshots import media, preview

from .helpers import image, make_app


def box(kind: bytes, *children: bytes) -> bytes:
    body = b"".join(children)
    return struct.pack(">I", 8 + len(body)) + kind + body


def full(kind: bytes, payload: bytes) -> bytes:
    return box(kind, b"\0\0\0\0" + payload)  # version 0, no flags


def track(handler: bytes, codec: bytes, seconds: float, *, size=(0, 0), frames=0, channels=0, rate=0,
          quicktime=False) -> bytes:
    timescale = 600
    # Version 0: times and ids (20), reserved (8), layer to volume (8), matrix (36), then width and height.
    tkhd = full(b"tkhd", b"\0" * (20 + 8 + 8 + 36) + struct.pack(">II", size[0] << 16, size[1] << 16))
    mdhd = full(b"mdhd", struct.pack(">IIII", 0, 0, timescale, round(seconds * timescale)) + b"\0" * 4)
    hdlr = full(b"hdlr", b"mhlr" + handler + b"\0" * 12)
    entry = codec + b"\0" * 6 + b"\0\x01"
    if handler == b"soun":
        entry += b"\0" * 8 + struct.pack(">HHHHI", channels, 16, 0, 0, rate << 16)
    stsd = full(b"stsd", struct.pack(">I", 1) + struct.pack(">I", 8 + len(entry)) + entry)
    stts = full(b"stts", struct.pack(">III", 1, frames, round(timescale / (frames / seconds))) if frames else
                struct.pack(">I", 0))
    # A QuickTime minf has its own data-handler hdlr, which must not overwrite the track's.
    data_handler = full(b"hdlr", b"dhlr" + b"alis" + b"\0" * 12) if quicktime else b""
    return box(b"trak", tkhd, box(b"mdia", mdhd, hdlr, box(b"minf", data_handler, box(b"stbl", stsd, stts))))


def movie(path: Path, seconds=20.0, size=(886, 1920), fps=30, audio: tuple | None = (2, 48000),
          codec=b"mp4a", quicktime=False) -> Path:
    mvhd = full(b"mvhd", struct.pack(">IIII", 0, 0, 600, round(seconds * 600)) + b"\0" * 80)
    tracks = [track(b"vide", b"avc1", seconds, size=size, frames=round(seconds * fps), quicktime=quicktime)]
    if audio:
        tracks.append(track(b"soun", codec, seconds, channels=audio[0], rate=audio[1], quicktime=quicktime))
    path.write_bytes(box(b"ftyp", b"isom") + box(b"moov", mvhd, *tracks))
    return path


def test_the_reader_finds_size_length_rate_and_audio(tmp_path: Path) -> None:
    m = media.read_movie(movie(tmp_path / "a.m4v", seconds=18, fps=30, audio=(2, 44100)))
    assert m.dimensions == (886, 1920)
    assert m.seconds == pytest.approx(18)
    assert m.video.fps == pytest.approx(30, abs=0.1)
    assert m.audio is not None and (m.audio.codec, m.audio.channels, m.audio.sample_rate) == (b"mp4a", 2, 44100)


def test_a_quicktime_data_handler_does_not_hide_the_video_track(tmp_path: Path) -> None:
    m = media.read_movie(movie(tmp_path / "raw.mov", size=(1206, 2622), fps=52, audio=None, quicktime=True))
    assert m.dimensions == (1206, 2622) and m.audio is None


@pytest.mark.parametrize("kwargs, problem", [
    ({"seconds": 12}, "12.0s long"),
    ({"seconds": 31}, "31.0s long"),
    ({"fps": 60}, "60.0 fps"),
    ({"audio": (1, 48000)}, "1ch"),
    ({"audio": (2, 22050)}, "22050 Hz"),
    ({"codec": b"lpcm"}, "lpcm"),
])
def test_what_apple_rejects_is_an_error(tmp_path: Path, kwargs: dict, problem: str) -> None:
    errors, _ = media.preview_problems(media.read_movie(movie(tmp_path / "p.m4v", **kwargs)))
    assert any(problem in e for e in errors), errors


def test_a_good_preview_passes_and_a_silent_one_only_warns(tmp_path: Path) -> None:
    assert media.preview_problems(media.read_movie(movie(tmp_path / "good.m4v"))) == ([], [])
    errors, warnings = media.preview_problems(media.read_movie(movie(tmp_path / "silent.m4v", audio=None)))
    assert errors == [] and "no audio track" in warnings[0]


def test_the_push_refuses_a_preview_apple_would_bounce(tmp_path: Path) -> None:
    deck = tmp_path / "iphone"
    image(deck / "ss-01.jpg", 1206, 2622)
    assert media.preview_type_for(movie(deck / "ap-01.m4v"), deck) == "IPHONE_61"
    with pytest.raises(SystemExit, match=r"60\.0 fps"):
        media.preview_type_for(movie(deck / "ap-01.m4v", fps=60), deck)


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return make_app(tmp_path, scheme="Example", screenshots={"locales": ["en-US", "de-DE"]})


def test_defaults_record_the_first_screenshot_locale_with_sound(app: project.App) -> None:
    config = preview.load_preview_config(app)
    assert config.test == "ExampleUITests/ExampleUITestsVideoPreviewUITests"
    assert list(config.locales) == ["en-US"]
    assert config.capture and config.bed is None and config.overlay is None
    assert config.fit == "crop" and config.max_seconds == 29


@pytest.mark.parametrize("previews, message", [
    ({"tset": "x"}, "unknown key"),
    ({"audio": {"bedd": "x"}}, "previews.audio"),
    ({"overlay": {"style": "band"}}, "captions is empty"),
    ({"overlay": {"style": "frame", "captions": "x"}}, '"band" or "none"'),
    ({"audio": {"bed": "missing.wav"}}, "no file"),
    ({"locales": ["fr-FR"]}, "not in screenshots.locales"),
    ({"fit": "stretch"}, '"crop" or "pad"'),
    ({"launch": "--ui-screenshot=video"}, "list of launch arguments"),
    ({"launch": ["--video"], "test": "T/T"}, "both launch and test"),
])
def test_bad_preview_settings_say_which(tmp_path: Path, previews: dict, message: str) -> None:
    app = make_app(tmp_path, scheme="Example", previews=previews)
    with pytest.raises(SystemExit, match=message):
        preview.load_preview_config(app)


def test_captions_hold_until_the_next_and_take_moments(app: project.App) -> None:
    timed = preview.caption_times([{"at": "trick", "text": "B"}, {"text": "A"}], {"trick": 6.5}, 20.0)
    assert timed == [(0.0, 6.5, "A"), (6.5, 20.0, "B")]
    with pytest.raises(SystemExit, match="never marked"):
        preview.caption_times([{"at": "queen", "text": "Q"}], {"trick": 1.0}, 20.0)


def test_captions_fall_back_to_the_primary_locale(tmp_path: Path) -> None:
    app = make_app(tmp_path, scheme="Example", previews={"overlay": {
        "style": "band", "captions": {"en-US": "No ads", "de-DE": [{"at": 0, "text": "Keine Werbung"}]}}})
    config = preview.load_preview_config(app)
    assert preview.captions_for(config, "de-DE", "en-US") == [{"at": 0, "text": "Keine Werbung"}]
    assert preview.captions_for(config, "fr-FR", "en-US") == [{"at": 0, "text": "No ads"}]


def test_events_before_this_run_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"event": "ready", "t": 90.0}, {"event": "end", "t": 95.0},  # the last run's
        {"event": "ready", "t": 101.0}, "not json", {"event": "ready", "t": 102.0}]) + "\nnot json\n")
    assert preview.read_events(path, since=100.0) == {"ready": 101.0}


def test_the_clip_runs_between_the_marks_and_a_long_one_keeps_its_end() -> None:
    assert preview.clip_window({"start": 1.0, "end": 21.0}, 30.0, 29) == (1.0, 20.0)
    assert preview.clip_window({"start": 1.0, "end": 41.0}, 45.0, 29) == (12.0, 29.0)
    assert preview.clip_window({}, 25.0, 29) == (0.0, 25.0)  # no marks: the whole recording


def test_the_preview_size_follows_the_slot_and_the_orientation(tmp_path: Path) -> None:
    assert preview.preview_size((1206, 2622), tmp_path / "none") == (886, 1920)
    assert preview.preview_size((2622, 1206), tmp_path / "none") == (1920, 886)
    assert preview.preview_size((2064, 2752), tmp_path / "none") == (1200, 1600)
    with pytest.raises(SystemExit, match="no App Preview slot"):
        preview.preview_size((1000, 1000), tmp_path / "none")


def test_the_band_is_opaque_at_the_top_and_clear_below(tmp_path: Path) -> None:
    app = make_app(tmp_path, scheme="Example", previews={"overlay": {
        "style": "band", "captions": "No ads", "framing": {"theme": "ruby", "caption": {"shape": "arch"}}}})
    config = preview.load_preview_config(app)
    png, (x, y) = preview.band_layer(app, config, "No ads", (1206, 2622), (886, 1920), tmp_path / "band.png")
    band = Image.open(png)
    assert (x, y) == (0, 0) and band.width == 886
    assert 0.07 * 1920 < band.height < 0.14 * 1920, "a thin band: depth plus the arch's bow and shadow"
    assert band.getpixel((443, 5))[3] == 255
    assert band.getpixel((443, band.height - 1))[3] < 255


def test_a_hung_xcodebuild_after_a_passing_test_is_a_pass(tmp_path: Path) -> None:
    import subprocess
    log = tmp_path / "test.log"
    log.write_text("Test Suite 'Selected tests' passed at 2026-10-16 14:10:13.907.\n")
    hung = subprocess.Popen(["sleep", "30"])
    assert preview.finish(hung, log, timeout=0.5) == 0
    log.write_text("Testing started\n")
    with pytest.raises(SystemExit, match="did not finish"):
        preview.finish(subprocess.Popen(["sleep", "30"]), log, timeout=0.5)
    assert preview.finish(subprocess.Popen(["false"]), log, timeout=5) == 1


def test_a_stall_is_a_gap_in_the_middle_of_motion() -> None:
    times = [i / 60 for i in range(10)] + [10 / 60 + 0.2] + [10 / 60 + 0.2 + i / 60 for i in range(1, 10)]
    moving = [0.0] + [1.0] * 9 + [4.0] + [1.0] * 9   # a card in flight, then a jump after a 200 ms gap
    assert preview.find_stalls(times, moving, 0, 30) == [(pytest.approx(10 / 60 + 0.2), pytest.approx(0.2 + 1 / 60))]
    still = [0.0] + [1.0] * 9 + [4.0] + [0.0] * 9    # the card lands and the table goes still: no stall
    assert preview.find_stalls(times, still, 0, 30) == []
    assert preview.find_stalls(times, moving, 1.0, 30) == [], "outside the clip window"


def test_launch_mode_builds_the_app_and_runs_no_test(tmp_path: Path) -> None:
    from types import SimpleNamespace
    (tmp_path / "Example.xcodeproj").mkdir()
    app = make_app(tmp_path, scheme="Example", previews={"launch": ["--ui-screenshot=video"]},
                   screenshots={"devices": ["iPhone 17 Pro"]})
    config = preview.load_preview_config(app)
    plan = preview.make_plan(app, config, SimpleNamespace(locales=None, device=None, dry_run=True, encode_only=False))
    assert config.launch == ["--ui-screenshot=video"]
    assert plan.passes[0].build[-1] == "build" and plan.passes[0].test == []


# --- the poster frame -----------------------------------------------------------------------------

def test_a_time_code_is_hours_minutes_seconds_frames_at_30_fps() -> None:
    assert media.time_code(5) == "00:00:05:00"  # Apple's example
    assert media.time_code(14.4) == "00:00:14:12"
    assert media.time_code(3725.5) == "01:02:05:15"
    assert media.time_code_seconds("00:00:14:12") == pytest.approx(14.4)
    for bad in ("00:00:14.4", "0:00:14:12", "00:00:14:30"):
        with pytest.raises(ValueError):
            media.time_code_seconds(bad)


@pytest.mark.parametrize("poster, message", [
    (True, "moment the app marks"), (-1, "moment the app marks"), ("  ", "moment the app marks"),
    (["won"], "moment the app marks"), (40, "at most 29"),
])
def test_a_bad_poster_says_what_it_takes(tmp_path: Path, poster: object, message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        preview.load_preview_config(make_app(tmp_path, scheme="Example", previews={"poster": poster}))


def test_the_poster_is_a_moment_or_seconds_and_unset_by_default(tmp_path: Path, app: project.App) -> None:
    assert preview.load_preview_config(app).poster is None
    assert preview.load_preview_config(make_app(tmp_path / "w", scheme="E", previews={"poster": "won"})).poster == "won"
    assert preview.poster_time(None, {"won": 3.0}, 20.0) is None
    assert preview.poster_time("won", {"won": 14.4}, 20.0) == pytest.approx(14.4)
    assert preview.poster_time(12.5, {}, 20.0) == 12.5
    assert preview.poster_time("end", {"end": 20.0}, 20.0) == pytest.approx(20.0 - 1 / 30), "the last frame"
    with pytest.raises(SystemExit, match="never marked"):
        preview.poster_time("won", {"start": 0.0}, 20.0)
    with pytest.raises(SystemExit, match=r"25s into a 20\.0s clip"):
        preview.poster_time(25, {}, 20.0)


def sidecar(clip: Path, poster: dict | None, captions: list[dict] | None = None) -> None:
    media.preview_sidecar(clip).write_text(json.dumps({"poster": poster, "captions": captions or []}))


def test_the_push_reads_the_poster_from_the_sidecar(tmp_path: Path) -> None:
    clip = movie(tmp_path / "ap-01.m4v", seconds=20)
    assert media.poster_time_code(clip, 20.0) is None, "no sidecar: Apple's default"
    sidecar(clip, {"seconds": 14.4, "time_code": "00:00:14:12", "from": "won"})
    assert media.poster_time_code(clip, 20.0) == "00:00:14:12"
    with pytest.raises(SystemExit, match="past the end"):
        media.poster_time_code(clip, 12.0)
    sidecar(clip, {"time_code": "14.4"})
    with pytest.raises(SystemExit, match="not an HH:MM:SS:FF"):
        media.poster_time_code(clip, 20.0)


def test_previews_push_reserves_each_preview_with_its_poster(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    from types import SimpleNamespace

    from snakelane.connect import asc
    from snakelane.screenshots import upload

    from .fakes import FakeClient

    app = make_app(tmp_path)
    deck = app.folder / "ios" / "screenshots" / "en-US" / "iphone"
    image(deck / "ss-01.jpg", 1206, 2622)
    clip = movie(deck / "ap-01.m4v")
    sidecar(clip, {"seconds": 14.4, "time_code": "00:00:14:12", "from": "won"})

    class Client(FakeClient):
        def post(self, path, body):
            super().post(path, body)
            return {"data": {**body["data"], "id": "new-1"}}

    client = Client({"/v1/appStoreVersionLocalizations/L1/appPreviewSets": {
        "data": [{"id": "S1", "attributes": {"previewType": "IPHONE_61"}}]}})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(asc.Credentials, "available", staticmethod(lambda: True))
    monkeypatch.setattr(upload.asc, "Client", lambda dry_run=False: client)
    monkeypatch.setattr(upload, "find_app", lambda c, cfg: {"id": "A1"})
    monkeypatch.setattr(upload, "find_editable_version", lambda c, app_id, platform: {"id": "V1"})
    monkeypatch.setattr(upload, "keyed", lambda c, path: {"en-US": {"id": "L1"}})
    monkeypatch.setattr(upload, "wait_for_asset_processing", lambda *a, **k: (["ok"], [], []))
    upload.cmd_previews_push(SimpleNamespace(app=None, platform=None, dry_run=False))
    [reserve] = [body for verb, path, body in client.writes if verb == "POST" and path == "/v1/appPreviews"]
    assert reserve["data"]["attributes"]["previewFrameTimeCode"] == "00:00:14:12"
    assert "en-US/iphone/ap-01.m4v: poster 00:00:14:12" in capsys.readouterr().out

    media.preview_sidecar(clip).unlink()
    client.writes.clear()
    upload.cmd_previews_push(SimpleNamespace(app=None, platform=None, dry_run=False))
    [reserve] = [body for verb, path, body in client.writes if verb == "POST" and path == "/v1/appPreviews"]
    assert "previewFrameTimeCode" not in reserve["data"]["attributes"], "unset: never sent"
    assert "poster Apple's default" in capsys.readouterr().out


# --- search results -------------------------------------------------------------------------------

def test_a_repeat_is_the_same_words_whatever_the_case() -> None:
    assert preview.repeats("SHOOT THE MOON", "Shoot the moon!")
    assert preview.repeats("No ads", "NO ADS\nNO ACCOUNTS"), "a caption inside the shot's text"
    assert not preview.repeats("Beat the bots", "Shoot the moon")
    assert not preview.repeats("ads", "No roads"), "whole words only"


def test_a_caption_repeating_ss_02_warns(tmp_path: Path) -> None:
    app = make_app(tmp_path, screenshots={"frame": "snakelane", "framing": {"captions": {
        "1": "No ads, ever", "2": ["Shoot", "the moon"], "3": "Beat the bots"}}})
    framed = tmp_path / "deck"
    [warning] = preview.search_result_repeats(app, "iphone", "en-US", framed, ["SHOOT THE MOON", "Beat the bots"])
    assert '"SHOOT THE MOON" repeats ss-02' in warning, "ss-03 isn't beside the preview"


def test_with_frame_test_the_captions_are_read_off_the_shots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from snakelane.screenshots import check, upload

    app = make_app(tmp_path, screenshots={"frame": "test"})
    framed = app.folder / "ios" / "screenshots" / "en-US" / "iphone"
    assert "has no ss-01/ss-02" in preview.search_result_repeats(app, "iphone", "en-US", framed, ["X"])[0]
    for n in (1, 2, 3):
        image(framed / f"ss-{n:02d}.jpg", 1206, 2622)
    monkeypatch.setattr(upload, "developer_chrome_check_available", lambda: False)
    [warning] = preview.search_result_repeats(app, "iphone", "en-US", framed, ["SHOOT THE MOON"])
    assert warning.startswith("can't check") and "snakelane[check]" in warning
    monkeypatch.setattr(upload, "developer_chrome_check_available", lambda: True)
    read = {"ss-01.jpg": ["NO ADS EVER"], "ss-02.jpg": ["SHOOT", "THE MOON", "12"]}
    monkeypatch.setattr(check, "text_in", lambda path: read[path.name])
    [warning] = preview.search_result_repeats(app, "iphone", "en-US", framed, ["SHOOT THE MOON", "BEAT THE BOTS"])
    assert '"SHOOT THE MOON" repeats ss-02' in warning


def test_the_gallery_mock_puts_the_poster_beside_ss_01_and_ss_02(tmp_path: Path) -> None:
    from snakelane.screenshots import gallery

    app = make_app(tmp_path, screenshots={"frame": "snakelane", "framing": {"captions": {
        "1": "No ads", "2": "Shoot the moon", "3": "Beat the bots"}}})
    folder = app.folder / "ios" / "screenshots" / "en-US" / "iphone"
    shots = [gallery.Shot(image(folder / f"ss-{n:02d}.jpg", 1206, 2622)) for n in (1, 2, 3)]
    clip = movie(folder / "ap-01.m4v")
    sidecar(clip, {"seconds": 14.4, "time_code": "00:00:14:12", "from": "won"},
            [{"from": 0, "to": 14, "text": "SHOOT THE MOON"}, {"from": 14, "to": 20, "text": "BEAT THE BOTS"}])
    deck = gallery.Deck("iPhone", "ios", folder, shots, [clip])
    tiles, warnings = gallery.search_strip(app, deck, "en-US", gallery.Assets(None))
    assert len(tiles) == 3 and "poster 00:00:14:12" in tiles[0]
    assert "ss-01.jpg" in tiles[1] and "ss-02.jpg" in tiles[2]
    assert len(warnings) == 1 and "repeats ss-02" in warnings[0]
    tiles, _ = gallery.search_strip(app, gallery.Deck("iPhone", "ios", folder, shots, []), "en-US", gallery.Assets(None))
    assert ["ss-01.jpg" in tiles[0], "ss-03.jpg" in tiles[2]] == [True, True], "no preview: three shots"


def test_the_dry_run_shows_the_poster_and_the_repeats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from types import SimpleNamespace
    (tmp_path / "Example.xcodeproj").mkdir()
    app = make_app(tmp_path, scheme="Example", screenshots={
        "devices": [{"name": "iPhone 17 Pro", "id": "UDID-1", "deck": "iphone"}], "frame": "snakelane",
        "framing": {"captions": {"1": "No ads", "2": "Shoot the moon"}}},
        previews={"launch": ["--video"], "poster": "won", "overlay": {"style": "band", "captions": [
            {"at": 0, "text": "SHOOT THE MOON"}, {"at": "won", "text": "BEAT THE BOTS"}]}})
    config = preview.load_preview_config(app)
    plan = preview.make_plan(app, config, SimpleNamespace(locales=None, device=None, dry_run=True, encode_only=True))
    clip = plan.passes[0].clip
    clip.parent.mkdir(parents=True)
    sidecar(clip, {"seconds": 14.4, "time_code": "00:00:14:12", "from": "won"},
            [{"from": 0, "to": 14, "text": "SHOOT THE MOON"}, {"from": 14, "to": 20, "text": "BEAT THE BOTS"}])
    preview.print_plan(plan, encode_only=True)
    out = capsys.readouterr().out
    assert "poster     'won' (a moment the app marks)" in out
    assert 'poster   00:00:14:12 in the encoded clip, under "BEAT THE BOTS"' in out
    assert 'warning: preview caption "SHOOT THE MOON" repeats ss-02' in out


def test_a_clip_encoded_before_the_sidecar_is_checked_against_the_config(tmp_path: Path) -> None:
    from snakelane.screenshots import gallery

    app = make_app(tmp_path, scheme="Example",
                   screenshots={"frame": "snakelane", "framing": {"captions": {"1": "No ads", "2": "Shoot the moon"}}},
                   previews={"overlay": {"style": "band", "captions": "SHOOT THE MOON"}})
    folder = app.folder / "ios" / "screenshots" / "en-US" / "iphone"
    shots = [gallery.Shot(image(folder / f"ss-{n:02d}.jpg", 1206, 2622)) for n in (1, 2)]
    deck = gallery.Deck("iPhone", "ios", folder, shots, [movie(folder / "ap-01.m4v")])
    tiles, warnings = gallery.search_strip(app, deck, "en-US", gallery.Assets(None))
    assert "poster: Apple&#x27;s default" in tiles[0] and "repeats ss-02" in warnings[0]

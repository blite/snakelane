"""`snakelane lint` rules, over a throwaway metadata tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane import project
from snakelane.listing import lint
from snakelane.release import ship

from .helpers import make_app, write


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return make_app(tmp_path, locales=["en-US", "es-ES", "ja"])


def rules(app: project.App) -> dict[tuple[str, str], str]:
    return {(f.where, f.rule): f.severity for f in lint.run(app, "ios")}


def test_clean_listing(app: project.App) -> None:
    write(app, "default", "name", "Example")
    write(app, "default", "description", "Plan your week. Works offline.")
    write(app, "default", "support_url", "https://example.com/support")
    assert lint.run(app, "ios") == []


def test_other_platform_matches_unspaced_scripts_but_not_inside_words(app: project.App) -> None:
    write(app, "default", "description", "An androgynous robot mascot.")
    write(app, "ja", "description", "Androidにも対応しています。")
    found = rules(app)
    assert found == {("ja/description", "other-platform"): "error"}


def test_todo_is_a_placeholder_in_english_but_a_word_in_spanish(app: project.App) -> None:
    write(app, "en-US", "description", "TODO write this")
    write(app, "es-ES", "description", "TODO LO QUE INCLUYE")
    write(app, "ja", "description", "説明\nTODO: 翻訳")
    found = rules(app)
    assert ("en-US/description", "placeholder") in found
    assert ("es-ES/description", "placeholder") not in found
    assert ("ja/description", "placeholder") in found


def test_a_todo_app_describing_itself_is_fine(app: project.App) -> None:
    write(app, "default", "description", "The todo list for busy people.")
    assert lint.run(app, "ios") == []


def test_keyword_format(app: project.App) -> None:
    write(app, "default", "name", "Pool Log")
    write(app, "default", "keywords", "pool, chlorine,,Chlorine,spa")
    messages = [f.message for f in lint.run(app, "ios") if f.where == "en-US/keywords"]
    assert any("spaces after commas" in m for m in messages)
    assert any("empty entry" in m for m in messages)
    assert any('repeats "chlorine"' in m for m in messages)
    assert any("name/subtitle: pool" in m for m in messages)


def test_errors_and_warnings(app: project.App) -> None:
    write(app, "default", "name", "A name that is far too long for the store")
    write(app, "default", "promotional_text", "Dark mode coming soon. Join the beta!")
    write(app, "default", "support_url", "example.com/help")
    found = rules(app)
    assert found[("en-US/name", "field-length")] == "error"
    assert found[("en-US/support_url", "url-format")] == "error"
    assert found[("en-US/promotional_text", "future-functionality")] == "warning"
    assert found[("en-US/promotional_text", "test-word")] == "warning"


def test_ignore_list_and_gate(app: project.App) -> None:
    write(app, "default", "description", "Also on Google Play.")
    with pytest.raises(SystemExit, match="lint found listing problems"):
        lint.gate(app, "ios")
    app.config["lint"] = {"ignore": ["other-platform"]}
    lint.gate(app, "ios")


def test_release_lints_the_live_listing_and_flags_unpushed_text(
        app: project.App, monkeypatch: pytest.MonkeyPatch) -> None:
    from snakelane.connect import asc
    from snakelane.listing import fields

    live_fields = dict.fromkeys(fields.LISTING)
    live = {
        "categories": {}, "copyright": None, "review": {"notes": None},
        "per_locale": {"en-US": {**live_fields, "description": "Also on Android."},
                       "es-ES": dict(live_fields), "ja": dict(live_fields)},
    }
    monkeypatch.setattr(asc, "Client", lambda *a, **k: object())
    monkeypatch.setattr(ship, "find_app", lambda client, config: {"id": "1"})
    monkeypatch.setattr(ship, "find_listing_version", lambda client, app_id, platform: {"id": "v"})
    monkeypatch.setattr(ship, "find_editable_app_info", lambda client, app_id: {"id": "i"})
    monkeypatch.setattr(ship, "fetch_live_state", lambda client, info, version, locales: live)
    write(app, "default", "description", "Fixed locally, never pushed.")

    found = {(f.where, f.rule) for f in ship.release_findings(app, "ios")}
    assert ("en-US/description", "other-platform") in found, "the live text is what gets linted"
    assert ("en-US/listing", "unpushed") in found


SUBSCRIPTIONS = """
subscription_groups:
  - reference_name: Plus
    subscriptions:
      - product_id: com.example.app.plus.yearly
        reference_name: Plus Yearly
        period: ONE_YEAR
"""


def links(app: project.App) -> list[lint.Finding]:
    return [f for f in lint.run(app, "ios") if f.rule == "subscription-links"]


def test_subscriptions_need_privacy_and_terms_links_in_every_description(app: project.App) -> None:
    write(app, "default", "description", "Plan your week.")
    write(app, "default", "privacy_url", "https://example.com/privacy/")
    assert links(app) == [], "no subscriptions, no rule"

    (app.folder / "iap.yml").write_text(SUBSCRIPTIONS)
    assert {(f.where, "Terms of Use" in f.message) for f in links(app)} == {
        (f"{locale}/description", terms) for locale in ("en-US", "es-ES", "ja") for terms in (False, True)}

    write(app, "default", "description", f"Plan your week.\n\nPrivacy Policy: https://example.com/privacy\n"
                                          f"Terms of Use: {lint.APPLE_EULA}")
    write(app, "ja", "description", "週の計画。https://example.com/privacy/")  # a translation that dropped the terms
    [found] = links(app)
    assert found.where == "ja/description" and lint.APPLE_EULA in found.message and "terms_url" in found.message


def test_terms_url_and_missing_privacy_url(app: project.App) -> None:
    (app.folder / "iap.yml").write_text(SUBSCRIPTIONS)
    app.config["terms_url"] = "https://example.com/terms"
    write(app, "default", "description", "Terms: https://example.com/terms/. https://example.com/privacy")
    found = links(app)
    assert {f.where for f in found} == {"en-US/description", "es-ES/description", "ja/description"}
    assert all("privacy_url.txt" in f.message for f in found), "terms found; no privacy URL to look for"
    write(app, "default", "privacy_url", "https://example.com/privacy")
    assert links(app) == []
    write(app, "default", "description", "Terms: https://example.com/terms-old and https://example.com/privacy")
    assert [f.message.split(": ")[-1] for f in links(app)][:1] == ["https://example.com/terms"], \
        "a longer URL that starts with the terms URL is not the terms URL"


def test_the_rule_can_be_ignored(app: project.App) -> None:
    (app.folder / "iap.yml").write_text(SUBSCRIPTIONS)
    write(app, "default", "description", "Plan your week.")
    app.config["lint"] = {"ignore": ["subscription-links"]}
    assert links(app) == []

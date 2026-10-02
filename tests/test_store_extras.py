"""Category validation and the age-rating questionnaire."""

from __future__ import annotations

import pytest

from snakelane.listing import fields, push


def test_categories_must_exist_and_sit_in_the_right_slot() -> None:
    known = fields.APP_CATEGORIES
    assert fields.category_problems({"primary": "GAMES", "primary_subcategory_one": "GAMES_PUZZLE",
                                    "secondary": "EDUCATION"}, known) == []
    problems = fields.category_problems({"primary": "EDUKATION", "secondary": "GAMES_PUZZLE",
                                        "secondary_subcategory_one": None}, known)
    assert "primary: 'EDUKATION' is not an App Store category" in problems
    assert any("is a subcategory" in p for p in problems)
    assert fields.category_problems({"primary": "EDUCATION", "primary_subcategory_one": "GAMES_PUZZLE"}, known) \
        == ["primary_subcategory_one: 'GAMES_PUZZLE' is not a subcategory of EDUCATION"]


def test_a_typo_in_categories_stops_the_offline_plan(tmp_path) -> None:
    with pytest.raises(SystemExit, match="EDUKATION"):
        push.build_push_plan(tmp_path, [], {"categories": {"primary": "EDUKATION"}})


def test_age_rating_keys_become_apples_attribute_names() -> None:
    assert fields.age_rating_attributes({
        "violence_cartoon_or_fantasy": "INFREQUENT_OR_MILD",
        "gambling": False,
        "age_rating_override_v2": "NONE",
    }) == {"violenceCartoonOrFantasy": "INFREQUENT_OR_MILD", "gambling": False, "ageRatingOverrideV2": "NONE"}


def test_only_changed_age_rating_answers_are_pushed() -> None:
    plan = {"age_rating": {"gambling": False, "lootBox": True},
            "category_relationships": {}, "copyright": None, "per_locale": {}, "review": {}}
    live = {"age_rating": {"gambling": False, "lootBox": False}, "categories": {},
            "copyright": None, "per_locale": {}, "review": {}}
    changes = push.diff_plan_against_live(plan, live)
    assert changes["age_rating"] == {"lootBox": True}
    assert push.count_changes(changes) == 1


def test_one_key_space_from_files_to_live_and_one_table_maps_it_to_app_store_connect(tmp_path) -> None:
    from snakelane.listing import fields, push

    platform_dir = tmp_path / "metadata" / "ios"
    (tmp_path / "metadata" / "default").mkdir(parents=True)
    (tmp_path / "metadata" / "default" / "promotional_text.txt").write_text("New levels.")
    (platform_dir / "review").mkdir(parents=True)
    (platform_dir / "review" / "demo_user.txt").write_text("reviewer")
    (platform_dir / "review" / "demo_password.txt").write_text("hunter2")
    plan = push.build_push_plan(platform_dir, ["en-US"], {})
    assert set(plan["per_locale"]["en-US"]) == set(fields.LISTING), "the files' stems, every field"
    assert plan["review"] == {"demo_user": "reviewer", "demo_password": "hunter2"}
    assert fields.review_attributes(plan["review"]) == {
        "demoAccountName": "reviewer", "demoAccountPassword": "hunter2", "demoAccountRequired": True}
    assert fields.mask("demo_password", "hunter2") == "•••" and fields.mask("notes", "hi") == "hi"
    live = {"age_rating": {}, "categories": {}, "copyright": None, "review": {},
            "per_locale": {"en-US": dict.fromkeys(fields.LISTING)}}
    changes = push.diff_plan_against_live(plan, live)
    assert changes["per_locale"] == {"en-US": {"promotional_text": "New levels."}}

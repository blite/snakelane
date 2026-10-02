"""iap.yml holds one-time purchases and subscriptions together."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane import project
from snakelane.purchases import catalogue

PRODUCT = """
products:
  - product_id: com.example.app.lifetime   # the one thing we sell outright
    reference_name: Lifetime
    type: NON_CONSUMABLE
    localizations: {en-US: {name: Lifetime, description: Everything, forever}}
"""
GROUP = """
subscription_groups:
  - reference_name: Plus
    subscriptions:
      - product_id: {id}
        reference_name: Plus Yearly
        period: ONE_YEAR
        localizations: {{en-US: {{name: Plus, description: More}}}}
"""


def write_catalogue(tmp_path: Path, text: str) -> Path:
    """Write metadata/iap.yml; return the platform folder the loaders are handed."""
    (tmp_path / "iap.yml").write_text(text)
    return tmp_path / "ios"


def test_both_sections_load_from_one_file(tmp_path: Path) -> None:
    folder = write_catalogue(tmp_path, PRODUCT + GROUP.format(id="com.example.app.plus.yearly"))
    assert [p["product_id"] for p in catalogue.load_iap_catalogue(folder)] == ["com.example.app.lifetime"]
    assert catalogue.load_subscription_catalogue(folder)[0]["reference_name"] == "Plus"


def test_an_id_used_in_both_sections_is_refused(tmp_path: Path) -> None:
    folder = write_catalogue(tmp_path, PRODUCT + GROUP.format(id="com.example.app.lifetime"))
    with pytest.raises(SystemExit, match=r"used more than once: com\.example\.app\.lifetime"):
        catalogue.load_subscription_catalogue(folder)


def test_a_missing_section_says_how_to_get_it(tmp_path: Path) -> None:
    folder = write_catalogue(tmp_path, PRODUCT)
    with pytest.raises(SystemExit, match="subs pull"):
        catalogue.load_subscription_catalogue(folder)
    folder = write_catalogue(tmp_path, GROUP.format(id="com.example.app.plus.yearly"))
    with pytest.raises(SystemExit, match="no one-time purchases"):
        catalogue.load_iap_catalogue(folder)


def test_subs_pull_rewrites_only_its_section(tmp_path: Path) -> None:
    path = write_catalogue(tmp_path, "# what we sell\n" + PRODUCT + GROUP.format(id="com.example.app.old")).parent / "iap.yml"
    project.set_yaml_section(path, "subscription_groups", [{"reference_name": "Plus", "subscriptions": []}])
    text = path.read_text()
    assert "# what we sell" in text and "# the one thing we sell outright" in text
    assert "com.example.app.old" not in text
    assert project.load_yaml(path)["products"][0]["product_id"] == "com.example.app.lifetime"


def test_subs_pull_creates_the_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "iap.yml"
    project.set_yaml_section(path, "subscription_groups", [{"reference_name": "Plus"}], header="# header\n")
    assert path.read_text().startswith("# header\n")
    assert project.load_yaml(path) == {"subscription_groups": [{"reference_name": "Plus"}]}


def test_a_subscription_price_is_ignored_with_a_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = write_catalogue(tmp_path, GROUP.format(id="com.example.app.plus.yearly").replace(
        "        period: ONE_YEAR\n", "        period: ONE_YEAR\n        price: {base_territory: USA, customer_price: 9.99}\n"))
    groups = catalogue.load_subscription_catalogue(folder)
    assert groups[0]["subscriptions"][0]["product_id"] == "com.example.app.plus.yearly"
    out = capsys.readouterr().out
    assert "price is ignored" in out and "unknown key" not in out


def test_review_screenshots_must_be_jpeg(tmp_path: Path) -> None:
    jpeg = PRODUCT.replace("    type:", "    review_screenshot: iap/lifetime.jpg\n    type:")
    assert catalogue.load_iap_catalogue(write_catalogue(tmp_path, jpeg))
    folder = write_catalogue(tmp_path, jpeg.replace(".jpg", ".png"))
    with pytest.raises(SystemExit, match=r"must be JPEG[\s\S]*com\.example\.app\.lifetime: iap/lifetime\.png"):
        catalogue.load_iap_catalogue(folder)

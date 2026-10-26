"""`asset_packs.items`: which pack.json list names the files to archive."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from snakelane.release.assetpacks import Packs, stage


def make(tmp_path: Path, items: str, entries_key: str) -> tuple[Packs, dict]:
    pictures = tmp_path / "content" / "hosted" / "village"
    pictures.mkdir(parents=True)
    for name in ("village_01", "village_02"):
        (pictures / f"{name}.heic").write_bytes(b"x")
    pack = {"pictureSource": "hosted/village", "imageExtension": "heic",
            entries_key: [{"resourceName": "village_02"}, {"resourceName": "village_01"}]}
    packs = Packs(SimpleNamespace(root=tmp_path), tmp_path / "packs", "packs/{theme}",
                  content_root=tmp_path / "content", record=tmp_path / "record.json",
                  build=tmp_path / "build", items=items)
    return packs, pack


def test_items_is_the_default_list(tmp_path):
    packs, pack = make(tmp_path, "items", "items")
    _, selectors = stage(packs, "village", pack)
    assert selectors == ["packs/village/village_02.heic", "packs/village/village_01.heic"]


def test_a_configured_key_is_read_instead(tmp_path):
    packs, pack = make(tmp_path, "puzzles", "puzzles")
    _, selectors = stage(packs, "village", pack)
    assert selectors == ["packs/village/village_02.heic", "packs/village/village_01.heic"]


def test_the_wrong_key_names_the_one_it_looked_for(tmp_path):
    packs, pack = make(tmp_path, "items", "puzzles")
    with pytest.raises(SystemExit, match='no "items" entries'):
        stage(packs, "village", pack)

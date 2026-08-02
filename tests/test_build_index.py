import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_index  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "nfc"


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tonies_dir = Path(self.tmp) / "tonies"

        # English/Paw Patrol/{Zuma,Marshall}.nfc
        paw_patrol = self.tonies_dir / "English" / "Paw Patrol"
        paw_patrol.mkdir(parents=True)
        shutil.copy(FIXTURES / "Zuma.nfc", paw_patrol / "Zuma.nfc")
        shutil.copy(FIXTURES / "Marshall.nfc", paw_patrol / "Marshall.nfc")

        # A duplicate-UID sibling of Zuma under a different name.
        shutil.copy(FIXTURES / "Zuma.nfc", paw_patrol / "Zuma Copy.nfc")

        # Nested series: English/Clever Tonies Set/Kids Comedy/Joke Telling.nfc
        nested = self.tonies_dir / "English" / "Clever Tonies Set" / "Kids Comedy"
        nested.mkdir(parents=True)
        shutil.copy(FIXTURES / "Joke Telling.nfc", nested / "Joke Telling.nfc")

        # German with umlaut-transliterated filename.
        german = self.tonies_dir / "German" / "Sesamstrasse"
        german.mkdir(parents=True)
        shutil.copy(
            FIXTURES / "Kruemelmonsters Mitmampfspass.nfc",
            german / "Kruemelmonsters Mitmampfspass.nfc",
        )

        # A malformed file that must be excluded, not fatal.
        (paw_patrol / "Broken.nfc").write_text("Filetype: Flipper NFC device\nVersion: 4\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collects_and_excludes_malformed(self):
        entries = build_index.collect_entries(self.tonies_dir)
        names = {e["name"] for e in entries}
        self.assertIn("Zuma", names)
        self.assertIn("Marshall", names)
        self.assertNotIn("Broken", names)
        # 2x Zuma (incl. copy) + Marshall + Joke Telling + Kruemelmonsters = 5
        self.assertEqual(len(entries), 5)

    def test_sort_order_language_series_name(self):
        entries = build_index.collect_entries(self.tonies_dir)
        keys = [(e["language"], e["series"], e["name"]) for e in entries]
        self.assertEqual(keys, sorted(keys))

    def test_nested_series_path(self):
        entries = build_index.collect_entries(self.tonies_dir)
        joke = next(e for e in entries if e["name"] == "Joke Telling")
        self.assertEqual(joke["series"], "Clever Tonies Set/Kids Comedy")
        self.assertEqual(joke["id"], "english/clever-tonies-set/kids-comedy/joke-telling")

    def test_duplicate_ids_get_suffixed(self):
        entries = build_index.collect_entries(self.tonies_dir)
        zuma_entries = [e for e in entries if e["name"].startswith("Zuma")]
        ids = {e["id"] for e in zuma_entries}
        self.assertEqual(len(ids), len(zuma_entries))

    def test_search_haystack_contains_umlaut_variants(self):
        entries = build_index.collect_entries(self.tonies_dir)
        kruemel = next(e for e in entries if "Kruemelmonsters" in e["name"])
        self.assertIn("kruemelmonsters", kruemel["search"])

    def test_json_payload_shape(self):
        entries = build_index.collect_entries(self.tonies_dir)
        payload = build_index.build_tonies_json_payload(entries, "abc1234")
        self.assertEqual(payload["upstream_commit"], "abc1234")
        self.assertEqual(payload["count"], len(entries))
        self.assertIn("generated_at", payload)
        json.dumps(payload)  # must be JSON-serializable

    def test_duplicate_uid_detection(self):
        entries = build_index.collect_entries(self.tonies_dir)
        dupes = build_index.find_duplicate_uids(entries)
        zuma_uid = next(e["uid"] for e in entries if e["name"] == "Zuma")
        self.assertIn(zuma_uid, dupes)
        self.assertEqual(len(dupes[zuma_uid]), 2)

    def test_render_tonies_md_includes_duplicate_section(self):
        entries = build_index.collect_entries(self.tonies_dir)
        md = build_index.render_tonies_md(entries, "abc1234", "2026-08-02T00:00:00Z")
        self.assertIn("# Available Tonies", md)
        self.assertIn("## Duplicate UIDs", md)
        self.assertIn("## English", md)
        self.assertIn("## German", md)
        self.assertIn("Zuma%20Copy.nfc", md)

    def test_render_tonies_md_no_duplicates_section_when_none(self):
        entries = [
            e
            for e in build_index.collect_entries(self.tonies_dir)
            if e["name"] != "Zuma Copy"
        ]
        md = build_index.render_tonies_md(entries, "abc1234", "2026-08-02T00:00:00Z")
        self.assertNotIn("## Duplicate UIDs", md)


if __name__ == "__main__":
    unittest.main()

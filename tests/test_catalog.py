import unittest

from tonie_writer.catalog import CatalogEntry, resolve, search
from tonie_writer.normalize import build_haystack


def make_entry(language, series, name, uid):
    return CatalogEntry(
        id=f"{language.lower()}/{series.lower().replace(' ', '-')}/{name.lower().replace(' ', '-')}",
        name=name,
        series=series,
        language=language,
        path=f"data/tonies/{language}/{series}/{name}.nfc",
        uid=uid,
        search=build_haystack(language, series, name),
    )


ZUMA_EN = make_entry("English", "Paw Patrol", "Zuma", "E00403502030361D")
ZUMA_DE = make_entry("German", "PAW Patrol", "Zuma", "E00403501E593D7B")
MARSHALL = make_entry("English", "Paw Patrol", "Marshall", "E00403501C73DE22")
KRUEMEL = make_entry("German", "Sesamstrasse", "Kruemelmonsters Mitmampfspass", "E00403501E8E99FE")

ENTRIES = [ZUMA_EN, ZUMA_DE, MARSHALL, KRUEMEL]


class TestSearchAndResolve(unittest.TestCase):
    def test_exact_match_unique_name(self):
        result = resolve(ENTRIES, "Marshall")
        self.assertEqual(result.outcome, "single")
        self.assertEqual(result.entry, MARSHALL)

    def test_ambiguous_name_across_languages(self):
        result = resolve(ENTRIES, "Zuma")
        self.assertEqual(result.outcome, "ambiguous")
        self.assertCountEqual(result.candidates, [ZUMA_EN, ZUMA_DE])

    def test_language_narrows_to_single_result(self):
        result = resolve(ENTRIES, "Zuma", language="English")
        self.assertEqual(result.outcome, "single")
        self.assertEqual(result.entry, ZUMA_EN)

        result = resolve(ENTRIES, "Zuma", language="German")
        self.assertEqual(result.outcome, "single")
        self.assertEqual(result.entry, ZUMA_DE)

    def test_pick_selects_from_ambiguous_candidates(self):
        result = resolve(ENTRIES, "Zuma", pick=2)
        self.assertEqual(result.outcome, "single")
        self.assertIn(result.entry, (ZUMA_EN, ZUMA_DE))

    def test_umlaut_query_matches_transliterated_filename(self):
        result = resolve(ENTRIES, "Krümelmonsters")
        self.assertEqual(result.outcome, "single")
        self.assertEqual(result.entry, KRUEMEL)

    def test_transliterated_query_also_matches(self):
        result = resolve(ENTRIES, "Kruemelmonsters")
        self.assertEqual(result.outcome, "single")
        self.assertEqual(result.entry, KRUEMEL)

    def test_no_match_returns_suggestions(self):
        result = resolve(ENTRIES, "Zorro")
        self.assertEqual(result.outcome, "none")
        self.assertTrue(result.suggestions)

    def test_fuzzy_typo_still_matches(self):
        results = search(ENTRIES, "Marshal")  # missing trailing 'l'
        self.assertTrue(results)
        self.assertEqual(results[0].entry, MARSHALL)

    def test_startswith_match(self):
        results = search(ENTRIES, "Kruemel")
        self.assertTrue(results)
        self.assertEqual(results[0].entry, KRUEMEL)

    def test_series_token_search(self):
        results = search(ENTRIES, "Sesamstrasse")
        self.assertTrue(any(r.entry == KRUEMEL for r in results))


if __name__ == "__main__":
    unittest.main()

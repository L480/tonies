"""Load the Tonie catalog (data/tonies.json) and match user queries against it."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from tonie_writer.normalize import normalize, normalized_variants

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "tonies.json"

FUZZY_THRESHOLD = 0.72


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    series: str
    language: str
    path: str
    uid: str
    search: str


def load_catalog(path: Path | None = None) -> list[CatalogEntry]:
    path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    if not path.exists():
        raise CatalogError(
            f"Catalog not found at {path}. Run './tonie index' or "
            "'python3 scripts/build_index.py' to generate it."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Catalog at {path} is not valid JSON: {exc}") from exc

    entries = []
    for item in data.get("tonies", []):
        entries.append(
            CatalogEntry(
                id=item["id"],
                name=item["name"],
                series=item["series"],
                language=item["language"],
                path=item["path"],
                uid=item["uid"],
                search=item["search"],
            )
        )
    return entries


@dataclass(frozen=True)
class MatchResult:
    entry: CatalogEntry
    tier: int
    score: float


def _matches_any(variants: list[str], candidates: list[str]) -> bool:
    return any(v == c for v in variants for c in candidates)


def _startswith_any(variants: list[str], candidates: list[str]) -> bool:
    return any(c.startswith(v) for v in variants for c in candidates if v)


def _best_ratio(variants: list[str], candidates: list[str]) -> float:
    best = 0.0
    for v in variants:
        for c in candidates:
            ratio = difflib.SequenceMatcher(None, v, c).ratio()
            best = max(best, ratio)
    return best


def rank_entry(entry: CatalogEntry, query_variants: list[str]) -> MatchResult | None:
    name_variants = normalized_variants(entry.name)
    id_variants = normalized_variants(entry.id.replace("/", " "))
    series_name_variants = normalized_variants(f"{entry.series} {entry.name}".strip())

    # Tier 1: exact match on normalized name.
    if _matches_any(query_variants, name_variants):
        return MatchResult(entry, tier=1, score=1.0)

    # Tier 2: exact match on normalized series/name or id.
    if _matches_any(query_variants, series_name_variants) or _matches_any(query_variants, id_variants):
        return MatchResult(entry, tier=2, score=1.0)

    # Tier 3: name startswith query.
    if _startswith_any(query_variants, name_variants):
        return MatchResult(entry, tier=3, score=1.0)

    # Tier 4: all query tokens present in the precomputed search haystack.
    haystack_words = set(entry.search.split())
    for qv in query_variants:
        tokens = qv.split()
        if tokens and all(tok in haystack_words for tok in tokens):
            return MatchResult(entry, tier=4, score=1.0)

    # Tier 5: fuzzy ratio against name.
    ratio = _best_ratio(query_variants, name_variants)
    if ratio >= FUZZY_THRESHOLD:
        return MatchResult(entry, tier=5, score=ratio)

    return None


def search(
    entries: list[CatalogEntry],
    query: str,
    language: str | None = None,
) -> list[MatchResult]:
    """Rank entries against `query`, best match first. Empty list if none match."""
    candidates = entries
    if language:
        lang_norm = normalize(language)
        candidates = [e for e in candidates if normalize(e.language).startswith(lang_norm) or normalize(e.language) == lang_norm]

    qvariants = normalized_variants(query)
    results = []
    for entry in candidates:
        result = rank_entry(entry, qvariants)
        if result is not None:
            results.append(result)

    results.sort(key=lambda r: (r.tier, -r.score, r.entry.language, r.entry.series, r.entry.name))
    return results


def suggest(entries: list[CatalogEntry], query: str, limit: int = 5) -> list[CatalogEntry]:
    """Best-effort 'did you mean' suggestions, ignoring the fuzzy threshold."""
    qvariants = normalized_variants(query)
    scored = []
    for entry in entries:
        name_variants = normalized_variants(entry.name)
        ratio = _best_ratio(qvariants, name_variants)
        scored.append((ratio, entry))
    scored.sort(key=lambda t: -t[0])
    return [entry for _ratio, entry in scored[:limit]]


@dataclass(frozen=True)
class ResolveResult:
    outcome: str  # "single" | "ambiguous" | "none"
    entry: CatalogEntry | None = None
    candidates: list[CatalogEntry] | None = None
    suggestions: list[CatalogEntry] | None = None


def resolve(
    entries: list[CatalogEntry],
    query: str,
    language: str | None = None,
    pick: int | None = None,
) -> ResolveResult:
    """Resolve a query to a single catalog entry, applying the language-narrowing
    and disambiguation rules from the plan (see §8.3)."""
    results = search(entries, query, language=language)

    if not results:
        return ResolveResult(outcome="none", suggestions=suggest(entries, query))

    if len(results) == 1:
        return ResolveResult(outcome="single", entry=results[0].entry)

    top_tier = results[0].tier
    top_results = [r for r in results if r.tier == top_tier]

    if len(top_results) == 1:
        return ResolveResult(outcome="single", entry=top_results[0].entry)

    # If not narrowed by --language but all top matches share one language, prefer it.
    if language is None:
        languages = {r.entry.language for r in top_results}
        if len(languages) == 1:
            return ResolveResult(outcome="single", entry=top_results[0].entry)

    candidates = [r.entry for r in top_results]

    if pick is not None:
        if 1 <= pick <= len(candidates):
            return ResolveResult(outcome="single", entry=candidates[pick - 1])
        return ResolveResult(outcome="ambiguous", candidates=candidates)

    return ResolveResult(outcome="ambiguous", candidates=candidates)

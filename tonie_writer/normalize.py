"""Shared text normalization for the catalog index and the search matcher.

Used by both scripts/build_index.py (to precompute the `search` haystack) and
tonie_writer/catalog.py (to normalize user queries the same way), so the two
stay in lockstep.
"""

from __future__ import annotations

import re
import unicodedata

_GERMAN_TRANSLIT = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def transliterate_german(text: str) -> str:
    """Replace German umlauts/ß with their ASCII digraphs (ä->ae, ß->ss, ...)."""
    for src, dst in _GERMAN_TRANSLIT.items():
        text = text.replace(src, dst)
    return text


def strip_diacritics(text: str) -> str:
    """Unicode NFKD decompose and drop combining marks (é -> e)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Lowercase, collapse any run of non-alphanumeric characters to one space."""
    text = strip_diacritics(text.lower())
    text = _NON_ALNUM.sub(" ", text)
    return text.strip()


def normalized_variants(text: str) -> list[str]:
    """Both normalization paths: as-is, and with German umlauts transliterated
    first (ä->ae, ...) before diacritics are stripped, since upstream filenames
    already use the transliterated form and users may type either.
    """
    variants = {normalize(text), normalize(transliterate_german(text))}
    return [v for v in variants if v]


def build_haystack(*parts: str) -> str:
    """Deduplicated, whitespace-joined bag of normalized words across all variants."""
    seen: set[str] = set()
    words: list[str] = []
    for part in parts:
        if not part:
            continue
        for variant in normalized_variants(part):
            for word in variant.split():
                if word not in seen:
                    seen.add(word)
                    words.append(word)
    return " ".join(words)


def slugify(text: str) -> str:
    """URL/id-safe slug: lowercase, diacritics stripped, non-alnum runs -> '-'."""
    text = strip_diacritics(text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")

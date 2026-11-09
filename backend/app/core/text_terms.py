"""Splits text into search terms, the same way for documents and queries in every keyword index: BM25
keyword search over the indexed chunks and the full-text index over the text cache.

A term is a run of letters, marks and digits in any script; spaces, punctuation and "_" end it. Each term
is folded so that spellings of the same word match: case is folded, accents and other marks are dropped
(réunion → reunion, ёлка → елка, اَلْمُدِيرُ → مدير, which also turns أ إ آ into ا), and Arabic letters
written several ways become one (ٱ → ا, ى → ي, ة → ه, tatweel removed, Arabic-Indic digits → 0-9).

Arabic writes "the", "and", "for" and "with" onto the front of a word, so an Arabic word also loses a leading
و and then one of ال، لل، بال، كال، فال، وال, as the prefix step of the light10 stemmer does, as long as three
letters remain: الحرارة, للحرارة and والحرارة all become حراره. Short words keep their letters (ولد, الي).

Chinese, Japanese, Thai, Lao, Khmer and Burmese are written without spaces between words, so a run in those
scripts is split into overlapping pairs of characters (会议记录 → 会议 议记 记录); a word of two or more
characters then matches anywhere inside a run. A single character only matches a run of one.

Dropping marks costs a little precision in scripts that write some vowels as marks (Hindi, Thai), but the
same folding runs on both sides, so a word always finds itself. Changing anything here changes the terms
stored in the text cache, so EXTRACTOR_VERSION (extractors.py) has to go up with it.
"""

import functools
import unicodedata

import regex

# Scripts written without spaces between words, plus the Japanese long-vowel and repeat marks inside them.
_UNSPACED = r"\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}\p{Lao}\p{Khmer}\p{Myanmar}ー々"
# Group 1 is a run in an unspaced script; otherwise the match is a word of letters, marks and digits.
_WORD_RE = regex.compile(rf"([{_UNSPACED}]+)|(?:(?![{_UNSPACED}])[\p{{L}}\p{{M}}\p{{N}}])+")
_ARABIC_FORMS = str.maketrans(
    {
        "ـ": None,  # tatweel
        "ٱ": "ا",  # alef wasla → alef
        "ى": "ي",  # alef maksura → yeh
        "ة": "ه",  # teh marbuta → heh
        **{chr(0x0660 + digit): str(digit) for digit in range(10)},
        **{chr(0x06F0 + digit): str(digit) for digit in range(10)},
    }
)
_ARABIC_WORD = regex.compile(r"\p{Arabic}+")
# Longest first, so للحراره loses لل rather than nothing.
_ARABIC_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")
# A prefix is only removed when at least this many letters remain, so short words keep their meaning.
_MIN_ARABIC_STEM = 3


@functools.lru_cache(maxsize=100_000)
def fold(word):
    """The word in the form every index stores: case folded, marks dropped, Arabic letter forms unified."""
    if word.isascii():
        return word.lower()
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    bare = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    folded = unicodedata.normalize("NFC", bare).translate(_ARABIC_FORMS)
    return _strip_arabic_prefix(folded) if _ARABIC_WORD.fullmatch(folded) else folded


def _strip_arabic_prefix(word):
    # The prefix step of the light10 stemmer: "and", then "the" or "the" joined to a preposition.
    if word.startswith("و") and len(word) - 1 >= _MIN_ARABIC_STEM:
        word = word[1:]
    for prefix in _ARABIC_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= _MIN_ARABIC_STEM:
            return word[len(prefix) :]
    return word


def terms(text):
    """Each search term in `text`, in order, as (term, start, end), where text[start:end] is what it came from."""
    found = []
    for match in _WORD_RE.finditer(text):
        if match.group(1) is None:
            term = fold(match.group())
            if term:
                found.append((term, match.start(), match.end()))
            continue
        chars = [(fold(char), match.start() + offset) for offset, char in enumerate(match.group())]
        chars = [(char, start) for char, start in chars if char]
        if len(chars) == 1:
            found.append((chars[0][0], chars[0][1], match.end()))
        for (first, start), (second, end) in zip(chars, chars[1:]):
            found.append((first + second, start, end + 1))
    return found


def tokenize(text):
    """The search terms in `text`, in order."""
    return [term for term, _, _ in terms(text)]

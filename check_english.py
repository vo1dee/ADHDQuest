"""Verifies every summary in adhd_quest_cache.json looks like English.

Flags: non-Latin scripts, Latin-script non-English words (accents, foreign
stopwords), empty/very short entries, and unfilled {placeholders}.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

ENGLISH = set("the a an to and of in you your is are for with that wants needs kill bring find has his her "
              "their them it be on at by from as this who was were will".split())
FOREIGN = set("le la les des est une du pour avec der die das und ist nicht el los las es por con una para "
              "il di che è per non и в на не что".split())


JUNK = re.compile(r"^\W*(?:no quest|no summary|quest details|tbd)|no quest (?:text|details)|insufficient input"
                  r"|is a placeholder|are placeholders|not yet implemented|no implemented text", re.I)
BRACKET_TOKEN = re.compile(r"\[[A-Za-z]{1,10}\]")  # model-invented stand-ins like [Name], [NPC], [class]


def hard_problems(text: str) -> list[str]:
    """Defects that make a summary unusable; pregenerate.py retries these instead of caching them."""
    found = []
    if {unicodedata.name(c, "?").split()[0] for c in text if c.isalpha()} - {"LATIN"}:
        found.append("non-Latin script")
    if len(text.strip()) < 25 or not re.search(r"[.!?\"'’”)]$", text.strip()):
        found.append("too short / truncated")
    if JUNK.search(text):
        found.append("no-content junk")
    if BRACKET_TOKEN.search(text):
        found.append("bracket token")
    return found


def problems(text: str) -> list[str]:
    found = []
    if not text.strip():
        return ["empty"]
    scripts = {unicodedata.name(c, "?").split()[0] for c in text if c.isalpha()} - {"LATIN"}
    if scripts:
        found.append(f"non-Latin script: {sorted(scripts)}")
    if re.search(r"[À-ÿ]", text):
        found.append("accented letters")
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if sum(w in FOREIGN for w in words) >= 2:
        found.append("foreign stopwords")
    if len(words) < 8 or sum(w in ENGLISH for w in words) / len(words) < 0.15:
        found.append("too short / few English words")
    if re.search(r"\{\w+\}", text):
        found.append("unfilled {placeholder}")  # fine: the addon fills {name}/{class}/{race} at runtime
    found += [h for h in hard_problems(text) if h not in found and not h.startswith("non-Latin")]
    return found


def main() -> int:
    cache = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "adhd_quest_cache.json").read_text(encoding="utf-8"))
    bad = {k: problems(v) for k, v in cache.items() if problems(v)}
    for key, why in bad.items():
        print(f"{key}: {'; '.join(why)}\n    {cache[key]}")
    print(f"{len(cache)} summaries checked, {len(bad)} flagged.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

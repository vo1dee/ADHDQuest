"""
ADHDQuest companion.

Watches the addon's SavedVariables file on disk. Whenever it sees new
pending quest text, checks a local cache (so nothing is ever summarized
twice), calls an OpenRouter model for anything new, and writes the result
back so the addon shows it after your next /reload.

Setup:
    pip install requests slpp
    Sign up at openrouter.ai, create a key, add ~$5 in credits (Settings ->
    Credits) -- Qwen3 32B isn't on the free tier, but at this script's
    volume (a handful of quests per play session) $5 will last a long time.
    export OPENROUTER_API_KEY=sk-or-...

Uses Qwen3 32B by default -- cheap, stable, no free-tier slug churn.
Override with a comma-separated OPENROUTER_MODEL env var if you want
something else; check https://openrouter.ai/models for current pricing.

Then edit SAVED_VARS_PATH below and run:
    python companion.py
"""

import json
import os
import re
import time
from pathlib import Path

import requests
from slpp import slpp as lua

# ---- CONFIGURE THESE ----
SAVED_VARS_PATH = Path(r"F:\Battle.net\World of Warcraft\_retail_\WTF\Account\134305248#3\SavedVariables\ADHDQuest.lua")
CACHE_JSON_PATH = Path("adhd_quest_cache.json")  # durable local cache, survives addon reinstalls
POLL_SECONDS = 5
OPENROUTER_MODELS = [m.strip() for m in os.environ.get(
    "OPENROUTER_MODEL",
    "qwen/qwen3-32b",  # cheap ($0.08/$0.28 per M tokens) and stable -- no more free-tier
                       # slugs disappearing mid-session. At companion.py's actual volume
                       # (a handful of quests per play session) this costs pennies a month.
).split(",")]
# --------------------------

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """\
You shorten World of Warcraft quest text for a player who wants the gist, fast.

Input: a quest title, the flavor/description text WoW shows the player, and
(when given) the game's own Objectives line stating exactly what to kill,
collect, or do, and how many.

Output 2-3 short, plain sentences a player could read in five seconds.
Always state the concrete objective plainly -- what to kill/collect/do and
the target count -- using the Objectives line when one is given; never
invent a count that isn't there. Keep who's asking and why, if the flavor
text has that. If the flavor text is thin, repetitive, or purely
mechanical, just state the objective directly -- never refuse, hedge, or
say something like "no summary provided."

Cut: scene-setting, lore-padding, repeated exposition, flowery language, and
anything that doesn't change what the player does or why.

Style: casual and direct, like a friend paraphrasing what an NPC just said.
Third person, no stage directions, no quotation marks, no exclamation-point
marketing tone. Never invent facts that aren't in the source text.

Output ONLY the summary. No preamble, no "Summary:", no extra formatting.

Example:
Title: A Cold One
Quest text: [three paragraphs of a dwarf named Grimtok describing an
exhausting day defending the outpost from orc raiders, the heat, his
aching arms, his fallen comrades, and how the only thing keeping him
going is the thought of a cold pint waiting at the tavern, asking the
player to fetch him one from the barkeep]
Objectives: Bring Grimtok a Cold Beer.
Summary: Grimtok's been fighting orcs at the outpost all day and he's
exhausted. All he wants right now is a cold beer from the tavern — go
grab him one.
"""


def load_cache() -> dict:
    if CACHE_JSON_PATH.exists():
        return json.loads(CACHE_JSON_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_JSON_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_saved_variables() -> dict:
    raw = SAVED_VARS_PATH.read_text(encoding="utf-8", errors="ignore")
    tables = {}
    for name in ("ADHDQuest_Cache", "ADHDQuest_Pending"):
        m = re.search(name + r"\s*=\s*(\{.*?\n\})\s*\n", raw, re.S)
        tables[name] = lua.decode(m.group(1)) if m else {}
    return tables


def summarize(title: str, text: str, objectives: str | None = None) -> str:
    """Tries each model in OPENROUTER_MODELS in order. Free models occasionally
    go stale (404) or get pulled without notice -- when that happens, move on
    to the next one instead of erroring out. Retries the same model a couple
    times only for 429 (rate limited), since that means it exists and works,
    just needs a moment."""
    user_content = f"Quest title: {title}\n\nQuest text:\n{text}"
    if objectives:
        user_content += f"\n\nObjectives (from the game): {objectives}"

    last_error = None
    for model in OPENROUTER_MODELS:
        for attempt in range(3):
            resp = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://vo1dee.com",  # identifies your app to OpenRouter, optional
                    "X-Title": "ADHDQuest",
                },
                json={
                    "model": model,
                    "max_tokens": 1000,  # generous headroom in case the routed model does hidden reasoning
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=30,
            )
            if resp.status_code == 429:
                print(f"{model}: rate limited, waiting 30s before retrying...")
                time.sleep(30)
                continue
            if resp.status_code >= 400:
                print(f"{model}: HTTP {resp.status_code} — {resp.text[:300]}")
                last_error = RuntimeError(f"{model} HTTP {resp.status_code}: {resp.text[:300]}")
                break  # try the next model in the list
            content = resp.json()["choices"][0]["message"].get("content")
            if not content:
                print(f"{model}: returned empty content, trying next model")
                last_error = RuntimeError(f"{model} returned empty content: {resp.json()}")
                break
            return content.strip()
    raise last_error or RuntimeError("All configured models failed")
    raise RuntimeError("Gave up after repeated rate limiting")


def lua_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_back(cache: dict) -> None:
    lines = ["ADHDQuest_Cache = {"]
    for key, summary in cache.items():
        lines.append(f'  ["{lua_escape(key)}"] = "{lua_escape(summary)}",')
    lines.append("}")
    lines.append("ADHDQuest_Pending = {}")  # clear the processed queue
    SAVED_VARS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    cache = load_cache()
    print(f"Loaded {len(cache)} cached summaries. Watching {SAVED_VARS_PATH} ...")
    last_mtime = None

    while True:
        try:
            mtime = SAVED_VARS_PATH.stat().st_mtime
            if mtime != last_mtime:
                pending = parse_saved_variables().get("ADHDQuest_Pending", {}) or {}
                new = 0
                for key, entry in pending.items():
                    if key in cache or not entry.get("text"):
                        continue
                    summary = summarize(entry.get("title") or "", entry["text"], entry.get("objectives"))
                    cache[key] = summary
                    new += 1
                    print(f"Summarized: {entry.get('title')!r} -> {summary}")
                if new:
                    save_cache(cache)
                    write_back(cache)
                    print(f"Wrote {new} new summaries. /reload in-game to see them.")
                last_mtime = mtime  # only advance once this batch fully succeeded
        except FileNotFoundError:
            pass  # file doesn't exist until you've logged in with the addon at least once
        except Exception as e:
            print("Error (will retry next poll):", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

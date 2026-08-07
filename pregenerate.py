"""
ADHDQuest pregenerate.py

Bulk-seeds adhd_quest_cache.json (the same cache companion.py uses) by
pulling quest descriptions from Blizzard's official Game Data API and
summarizing them with an OpenRouter model — all before you ever log into
the game.

Coverage caveat: Blizzard's public quest API is known to be incomplete —
plenty of quest IDs 404 or come back with an empty description, especially
older/Classic content. Treat this as a free head start, not a full
database. Anything it misses (or any custom quest on a private server)
still gets picked up automatically by companion.py the first time you
actually see it in-game.

Setup:
    pip install requests
    Create a client at https://develop.battle.net (free) -> client ID/secret
    export BNET_CLIENT_ID=...
    export BNET_CLIENT_SECRET=...
    Sign up at openrouter.ai, create a key, add ~$5 in credits (Settings ->
    Credits — Qwen3 32B isn't on the free tier, but this whole bulk run
    only costs a few dollars total, see note below)
    export OPENROUTER_API_KEY=sk-or-...

Free-model IDs on OpenRouter rotate often (and get pulled outright), so this
script doesn't use one: for a bulk one-time run across tens of thousands of
quests, that churn plus free-tier rate limits would make this unreliable and
slow. Qwen3 32B below costs roughly $4 total for ~50,000 quests (cached
forever after, so this is a one-time cost), isn't on any retirement
schedule, and matches what companion.py uses by default too.

Usage:
    python pregenerate.py --start 1 --end 2000 --region us --namespace static-us
    (namespace is usually static-<region> for retail; for Classic namespaces
    check https://develop.battle.net/documentation/world-of-warcraft/guides/namespaces)
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests

CACHE_JSON_PATH = Path("adhd_quest_cache.json")
STATIC_LUA_PATH = Path("Summaries.lua")  # ships inside the addon folder
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-32b")
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """\
You shorten World of Warcraft quest text for a player who wants the gist, fast.

Input: a quest title and the raw text WoW shows the player (flavor/description
text, and sometimes objective or turn-in text).

Output 2-3 short, plain sentences a player could read in five seconds. Keep:
- who is talking and what they want
- why (their situation or motivation)
- anything the player needs to understand their actual objective

Cut: scene-setting, lore-padding, repeated exposition, flowery language, and
anything that doesn't change what the player does or why.

Style: casual and direct, like a friend paraphrasing what an NPC just said.
Third person, no stage directions, no quotation marks, no exclamation-point
marketing tone. Never invent facts that aren't in the source text.

Output ONLY the summary. No preamble, no "Summary:", no extra formatting.
"""


def get_bnet_token(region: str) -> str:
    resp = requests.post(
        f"https://{region}.battle.net/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(os.environ["BNET_CLIENT_ID"], os.environ["BNET_CLIENT_SECRET"]),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_quest(region: str, namespace: str, token: str, quest_id: int) -> dict | None:
    resp = requests.get(
        f"https://{region}.api.blizzard.com/data/wow/quest/{quest_id}",
        params={"namespace": namespace, "locale": "en_US"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def summarize(title: str, text: str) -> str:
    for attempt in range(3):
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://vo1dee.com",
                "X-Title": "ADHDQuest",
            },
            json={
                "model": OPENROUTER_MODEL,
                "max_tokens": 1500,
                "reasoning": {"enabled": False},  # Qwen3 is a hybrid reasoning model; without this
                                                    # it sometimes burns the whole token budget on
                                                    # invisible "thinking" and returns nothing
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Quest title: {title}\n\nQuest text:\n{text}"},
                ],
            },
            timeout=30,
        )
        if resp.status_code == 429:
            print("Rate limited, waiting 30s before retrying...")
            time.sleep(30)
            continue
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content")
        if not content:
            raise RuntimeError(f"Model returned empty content (raw response: {resp.json()})")
        return content.strip()
    raise RuntimeError("Gave up after repeated rate limiting")


def lua_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_static_lua(cache: dict) -> None:
    lines = ["-- Auto-generated by pregenerate.py — do not edit by hand.",
             "ADHDQuest_StaticSummaries = {"]
    for key, summary in cache.items():
        lines.append(f'  ["{lua_escape(key)}"] = "{lua_escape(summary)}",')
    lines.append("}")
    STATIC_LUA_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--region", default="us")
    ap.add_argument("--namespace", default="static-us")
    args = ap.parse_args()

    cache = json.loads(CACHE_JSON_PATH.read_text(encoding="utf-8")) if CACHE_JSON_PATH.exists() else {}
    token = get_bnet_token(args.region)
    hits, misses, failures = 0, 0, 0

    for qid in range(args.start, args.end + 1):
        key = f"id:{qid}"
        if key in cache:
            continue
        data = fetch_quest(args.region, args.namespace, token, qid)
        text = (data or {}).get("description", "")
        if not text:
            misses += 1
            continue
        title = data.get("title", "")
        try:
            cache[key] = summarize(title, text)
        except Exception as e:
            failures += 1
            print(f"{qid}: {title!r} -- FAILED, skipping ({e})")
            continue  # not cached, so a future run will retry it automatically
        hits += 1
        print(f"{qid}: {title!r} -> {cache[key]}")
        if hits % 50 == 0:
            CACHE_JSON_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        time.sleep(0.1)  # be polite to Blizzard's API

    CACHE_JSON_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    write_static_lua(cache)
    print(f"Done. {hits} new summaries, {misses} quest IDs had no description, "
          f"{failures} failed and will retry next run. {len(cache)} total cached.")
    print(f"Copy {STATIC_LUA_PATH} into the ADHDQuest addon folder and add it to the .toc.")


if __name__ == "__main__":
    main()

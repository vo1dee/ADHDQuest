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
    (or copy .env.example to .env and fill it in -- loaded automatically)
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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from envfile import load_dotenv

load_dotenv()  # keys can live in a gitignored .env next to this script

CACHE_JSON_PATH = Path("adhd_quest_cache.json")
FAILED_JSON_PATH = Path("failed_ids.json")  # IDs that errored; retried first on the next run
STATIC_LUA_PATH = Path("ADHDQuest/Summaries.lua")  # ships inside the addon folder
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


class FatalError(Exception):
    """Errors retrying can't fix (out of credits, bad key) -- stop the run instead of failing every ID."""


class BnetToken:
    """Shared across worker threads; refreshes once when Blizzard says the token expired (24h life)."""

    def __init__(self, region: str):
        self.region, self.value, self.lock = region, get_bnet_token(region), threading.Lock()

    def refresh(self, stale: str) -> None:
        with self.lock:
            if self.value == stale:  # another thread may have refreshed already
                self.value = get_bnet_token(self.region)


def fetch_quest(region: str, namespace: str, token: BnetToken, quest_id: int) -> dict | None:
    """Returns the quest, or None if Blizzard has no such quest (404). Retries transient
    failures (timeouts, 429, 5xx); raises if it still can't get a definite answer, so a
    flaky request is never mistaken for a missing quest."""
    last = None
    for attempt in range(6):
        sent = token.value
        try:
            resp = requests.get(
                f"https://{region}.api.blizzard.com/data/wow/quest/{quest_id}",
                params={"namespace": namespace, "locale": "en_US"},
                headers={"Authorization": f"Bearer {sent}"},
                timeout=30,
            )
        except requests.exceptions.RequestException as e:  # timeouts, resets, DNS blips
            last = e
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        if resp.status_code == 401:
            token.refresh(sent)
            last = RuntimeError("HTTP 401")
        elif resp.status_code == 429:  # Blizzard's per-second / hourly quota
            time.sleep(int(resp.headers.get("Retry-After", 2)))
            last = RuntimeError("HTTP 429")
        elif resp.status_code >= 500:
            time.sleep(2 ** attempt)
            last = RuntimeError(f"HTTP {resp.status_code}")
        else:
            raise RuntimeError(f"Blizzard API HTTP {resp.status_code}: {resp.text[:200]}")
    raise RuntimeError(f"Blizzard API gave up after retries ({last})")


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
            timeout=60,
        )
        if resp.status_code == 429:
            print("Rate limited, waiting 30s before retrying...")
            time.sleep(30)
            continue
        if resp.status_code in (401, 402, 403):
            raise FatalError(f"OpenRouter HTTP {resp.status_code} ({'out of credits' if resp.status_code == 402 else 'bad key'}): {resp.text[:200]}")
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content")
        if not content:  # Qwen sometimes spends the whole budget on hidden reasoning; a retry usually works
            continue
        return content.strip()
    raise RuntimeError("Gave up: rate limited or empty responses on every attempt")


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
    ap.add_argument("--start", type=int, help="default: highest cached quest ID + 1")
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--region", default="us")
    ap.add_argument("--namespace", default="static-us")
    ap.add_argument("--workers", type=int, default=16, help="concurrent fetch+summarize workers")
    args = ap.parse_args()

    cache = json.loads(CACHE_JSON_PATH.read_text(encoding="utf-8")) if CACHE_JSON_PATH.exists() else {}
    if args.start is None:
        args.start = max((int(k[3:]) for k in cache if k.startswith("id:")), default=0) + 1
    print(f"Scanning quest IDs {args.start}-{args.end} ({len(cache)} already cached).")
    token = BnetToken(args.region)
    hits, misses, failures = 0, 0, 0

    failed = set(json.loads(FAILED_JSON_PATH.read_text())) if FAILED_JSON_PATH.exists() else set()
    todo = sorted(q for q in {*range(args.start, args.end + 1), *failed} if f"id:{q}" not in cache)
    if failed:
        print(f"Also retrying {len(failed)} IDs that failed last time.")
    def save() -> None:
        CACHE_JSON_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        FAILED_JSON_PATH.write_text(json.dumps(sorted(failed)), encoding="utf-8")

    consecutive_errors = 0

    def work(qid: int):
        """Runs in a worker thread: fetch, then summarize. Returns (qid, title, summary, error)."""
        title = ""
        try:
            data = fetch_quest(args.region, args.namespace, token, qid)
            text = (data or {}).get("description", "")
            if not text:
                return qid, "", None, None
            title = data.get("title", "")
            return qid, title, summarize(title, text), None
        except Exception as e:  # one bad quest must never kill a multi-hour run
            return qid, title, None, e

    pool = ThreadPoolExecutor(max_workers=args.workers)
    try:
        # map() yields in ID order while the workers run ahead concurrently
        for qid, title, summary, error in pool.map(work, todo):
            if isinstance(error, FatalError):
                print(f"{qid}: STOPPING -- {error}\nFix that (top up credits / check the key) and re-run; progress is saved.")
                failed.add(qid)
                break
            if error:
                failures += 1
                failed.add(qid)  # remembered in failed_ids.json, retried on the next run
                consecutive_errors += 1
                print(f"{qid}: {title!r} -- FAILED, skipping ({error})")
                if consecutive_errors >= 25:
                    print("STOPPING -- 25 failures in a row (network down?). Progress is saved; re-run when fixed.")
                    break
                continue
            consecutive_errors = 0
            failed.discard(qid)
            if summary is None:
                misses += 1
                continue
            cache[f"id:{qid}"] = summary
            hits += 1
            print(f"{qid}: {title!r} -> {summary}")
            if hits % 50 == 0:
                save()
    except KeyboardInterrupt:
        print("Interrupted -- saving what we have. Re-run to continue (cached IDs are skipped).")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # don't run the whole queue after Ctrl-C
        save()
    write_static_lua(cache)
    print(f"Done. {hits} new summaries, {misses} quest IDs had no description, "
          f"{failures} failed and will retry next run. {len(cache)} total cached.")
    print(f"Copy the ADHDQuest folder into your WoW AddOns directory (Summaries.lua is already in the .toc).")


if __name__ == "__main__":
    main()

# ADHDQuest — 0 to hero

## 0. Confirm your setup
- Find your WoW install path and figure out which folder applies: `_retail_`,
  `_classic_`, or `_classic_era_` (or your private server's equivalent).
- Open `ADHDQuest.toc` and set `## Interface:` to match your client. In-game,
  type `/dump select(4, GetBuildInfo())` to get the right number. Some
  private servers don't enforce this at all — try `110200` first, lower it
  if the client refuses to load the addon.

## 1. Install the addon (capture only, no AI yet)
- Copy the `ADHDQuest` folder into `.../WoW/_yourversion_/Interface/AddOns/`.
- Log in, make sure it's enabled at the character select screen.
- Walk up to any quest giver, open a quest. Type `/adhdquest` — you should see
  "1 waiting to be summarized" (or more, depending how many quests you opened).
- This step alone proves the capture side works, with zero AI involved yet.

## 2. Set up the companion script
- `pip install requests slpp`
- Sign up at openrouter.ai, create an API key, add ~$5 in credits (Settings
  -> Credits — Qwen3 32B isn't on the free tier, but at this script's
  volume — a handful of quests per play session — $5 lasts a long time),
  `export OPENROUTER_API_KEY=...`
- Edit `SAVED_VARS_PATH` in `companion.py` to point at:
  `.../WoW/_retail_/WTF/Account/YOURACCOUNT/SavedVariables/ADHDQuest.lua`
  (this file only appears after step 1, once you've logged out or `/reload`ed
  at least once with the addon active)
- Run `python companion.py` and leave it running in a terminal while you play.

## 3. Close the loop
- In-game: open a quest, then type `/reload` (SavedVariables only get
  written to disk on logout/reload, not live — this is the one bit of
  lag in the whole design).
- The companion script should print `Summarized: '...' -> ...` within a
  few seconds and write the result back to the SavedVariables file.
- Log back in (or `/reload` — note: `/reload` only works if this is a
  *fresh* login/reload, not one where the old empty cache is still sitting
  in memory; logging fully out and back in is the reliable way) — open the
  same quest (or revisit the quest log) and the quest text itself should
  now show the short version, with a "Show full text" button right below
  it to expand back to the original.

## 4. Let it grow
- No manual steps beyond playing normally with companion.py running.
  Every quest you see gets captured once, summarized once, and cached
  forever — reopening it, relogging, or visiting on an alt costs nothing.

## 5. Optional: give it a head start with pregenerate.py
- Doesn't need the game open. Pulls quest descriptions from Blizzard's
  official API and pre-seeds the cache before you ever see them in-game.
- Uses the same paid model as companion.py (Qwen3 32B) rather than a free
  one, since a one-time bulk run across tens of thousands of quests would
  hit free-tier rate limits and slug churn hard. Add ~$5 in credits at
  openrouter.ai (Settings -> Credits) — the whole run costs roughly $4 for
  ~50,000 quests, one time,
  cached forever after.
- `python pregenerate.py --start 1 --end 2000 --region us --namespace static-us`
  (raise `--end` as far as you like; it skips anything already cached)
- Copy the `Summaries.lua` it produces into the `ADHDQuest` addon folder.

## Hero-tier upgrades (optional)
- **Near-real-time instead of reload-based**: some existing addons (e.g.
  the "Quest Reader Addon" TTS mod) use a hotkey + clipboard bridge — the
  addon selects text in a hidden edit box, a companion app simulates
  Ctrl+C to grab it and Ctrl+V to paste a result back in. It removes the
  reload step but relies on OS-level keystroke simulation into the game
  window, which is a flakier, more "unsupported automation" pattern than
  the file-based approach above. Worth it only if the reload lag actually
  bothers you.
- **Share the cache**: once you've built up a decent `adhd_quest_cache.json`
  from your own play, you can bake it into a static `Summaries.lua` and
  ship that as a normal addon update — no companion script needed for
  people who just want to consume your cache.

## Notes
- The cache key is quest text, not just quest ID, so custom/private-server
  quests get summarized correctly even though no public database has them.
- Cost stays trivial either way: each unique quest is summarized exactly
  once, ever. companion.py runs on a free model since play generates new
  quests a handful at a time; pregenerate.py's one-time bulk run costs a
  few dollars total even across tens of thousands of quests.

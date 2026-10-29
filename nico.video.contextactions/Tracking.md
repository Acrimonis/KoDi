# Tracking

Working log for addon changes. Updated after each confirmed step.

## Status

| Task | State |
|------|-------|
| README: rename Watch in Past → Watched to Past... | done |
| README: add Move to Top section, five-action wording, `t` keymap | done |
| README: Move to Top notification text and season 0 rule | done |
| Tracking.md created | done |
| `resources/lib/move_to_top.py` | done — untested in live Kodi |
| `addon.xml`: add `Move to Top` menu item | done — untested in live Kodi |
| `addon.xml`: drop the `Silent` prefix from the five action labels (now start with `•`) | done — needs Kodi restart |
| Docs aligned to the new names (README headings, `copilot-instructions.md`) | done |
| `addon.xml`: add `nICo Dev • Reload Modules` menu item (runs `common_locks.py` reloader) | done |
| `deploy.bat` (D: portable, symlinked to repo) and `deploy-qpc.bat` (P:\.kodi_d\addons) | done — repo root |
| README: Development section (reload entry, deploy scripts, enable note) | done |
| Enable addon in Kodi (portable profile had it `enabled=0` in `Addons33.db`) | todo — user |
| Live Kodi test (all four dbtypes, all-watched fallback, queued case) | todo |
| Version bump to 1.0.7 (`addon.xml`, README) | done |

## Plan (1.0.8)

| # | Step | State |
|---|------|-------|
| A | Live verify (see "Verification checklist") | in progress (local) — passed 2, 4, 5, 7, 9 (season), 10; open 1, 3, 6, 8, 9 (movie), 11–14 |
| H | Fixes from code review R1–R5 (see "Review (2026-10-29)") | done — R3 fallback seen (`Default play (Play)`); R1, R2, R4 untested |
| B | Persist fixes (`smart_cmd.py`, `service.py`): automatic save for `episode` only; abort without show ID; automatic mode takes the show title from the library; create profile silently on playback start if none exists | done — verified live (checklist 2) |
| C | Position tracking (`service.py`): sample every 1s in memory, write every 30s (silent, no fsync, skipped when paused/unchanged), stop = exact last sample, end = `completed` | done — stop/end verified live; ticks not yet (checklist 3) |
| D | Smart Play (`smart_play.py`, new) incl. derived profile creation, `Smart resume` toast | done — verified live (checklist 7, 9 season, 10); autoplay open (8) |
| E | Snapshot fix: `common_locks.update_snapshot_entries`, called by `watched_past.py` and `move_to_top.py` | done — untested in Kodi |
| F | README: per-entry visibility table, Persist/Smart Play sections, remote keymap example | done |
| G | Release 1.0.8: version bumped in `addon.xml` and README; work committed 2026-10-29 (not pushed); zip + push held until A passes | partial |

Implementation notes (2026-10-28):
- Syntax checked with Python 3.8 grammar only (`ast.parse`); no runtime test outside Kodi.
- `persist_show_by_id` gained `create_only`, `position`, `duration`, `strategy`, `source`, `durable` keyword args; existing callers unchanged. New helpers `profile_path`, `load_profile`.
- Service loop now wakes every 1s (`waitForAbort(1)`) instead of 10s.
- Service changes need a Kodi restart (the reloader does not restart the running service).
- 2026-10-29 QPC: 1.0.8 deployed (`deploy-qpc.bat`); `P:\.kodi_d\userdata\keymaps\keyboard.xml` `<Videos>` binds Smart Play to `<p>` (fallback `Play`, the remote seems to send keys), `<play_pause>` and `<remote><play>` (fallback `PlayPause`). Backup: `keyboard.xml.bak-20261029`. Which one fires: to confirm via `OnKey` (debug log).
- 2026-10-29 local: step A runs on the local portable instance (QPC not at hand). Local `D:\.kodi\portable_data\userdata\keymaps\keyboard.xml` = copy of the QPC one (incl. Smart Play bindings, `b` = Stop); `script.keymap` / `script.tagoverview` are not installed locally.
- 2026-10-29 live (local): Smart Play via `p` works — `Player.Open` honors the resume time exactly (wanted 557.2s, started 557.2s), seek fallback not needed. Stop position exact (checklist 4, 7 passed; stop toast not visually confirmed, log shows `Silent:False`).
- 2026-10-29: Smart Play toast added (decided wording): `Smart resume • S01E01 at 9:17`, standard info, 2500 ms, only when resuming from the profile. Derived profile → suffix `(from Kodi)` (decided).
- 2026-10-29 (step H): `persist_show_by_id` gained `quiet`; service gained `on_exit` and the switch save in `onPlayBackStarted`; `smart_play.py` reads its fallback action from `sys.argv[1]`.

### Review (2026-10-29)

Code review of the uncommitted 1.0.8 diff plus the first live run (local instance, 2026-10-28 22:07).

| # | Finding | Proposed fix | State |
|---|---------|--------------|-------|
| R1 | Kodi quit during playback: `onPlayBackStopped` is not delivered, the service loop just exits → up to 30s of position lost. Observed: `4.json` stayed at 0 after quitting ~15s into S01E01 (no `Playback Stopped` in log). | `service.py`: after the `waitForAbort` loop ends, if an episode is tracked, persist the last sample (`in_progress`, silent). Best-effort: Kodi gives services only a few seconds. | done (`on_exit`) |
| R2 | Item change without Stopped/Ended (next playlist episode, `Player.Open` over a playing episode): if Kodi does not deliver Stopped/Ended, `onPlayBackStarted` resets state → previous episode's last ≤30s lost, its `completed` never written, status keeps the old episode until the new one's first tick (30s). | `onPlayBackStarted`: if an episode is still tracked, persist it (last sample) before reset. Checklist 8 shows whether Kodi sends Ended between episodes (`Playback Switched` in the log = it did not). | done |
| R3 | Keymap `<keyboard><play_pause>` in Videos: the fallback `Action(Play)` replaces `PlayPause`, so with background playback the key no longer pauses. On a show/season while a video plays, Smart Play replaces the playing video. | `smart_play.py` falls back to the key's original action: script argument, default `PlayPause` (Kodi's default keymaps bind both remote `play` and keyboard `play_pause` to `PlayPause`; checked in `D:\.kodi\system\keymaps`). When a video is playing/paused, the fallback runs instead of Smart Play. README snippet unchanged (default fits). | done |
| R4 | Stop in the end credits: Kodi marks the episode watched past ~92% (`ignorepercentatend` 8%), the service saves `in_progress` → Smart Play resumes in the credits instead of Kodi's default play. Decided (2026-10-29): every automatic in_progress save (stop, tick, switch, exit) at ≥ 92% of duration → `completed`. Constant `_COMPLETED_RATIO` in `service.py`. | done |
| R5 | Log noise: each 30s tick writes ~5 INFO lines from `persist_show_by_id` (Entry, Processing, Playback, Saved) although the tick line itself is DEBUG. `persist_show_by_id(quiet=True)` for ticks: routine lines at DEBUG. | done |

Checked, no change needed:
- Snapshot update (`update_snapshot_entries`) runs under the show lock like every other snapshot reader/writer; key/value format matches `merge_and_save_snapshot` (`''` for Never).
- `move_to_top.py`: `target['episodeid']` present for episode/season/tvshow targets; movie path skipped as planned.
- `watched_past.py`: snapshot updated only for `affected` idFiles, with `target_str` (`None` → `''`).
- `Player.Open` `options.resume` as a time object is valid per the JSON-RPC schema.
- `create_only`, history archiving (ticks don't archive; first write for a new episode does), derived-profile rules match the plan; `source` is dropped by the next non-derived write.
- Reloader imports `move_to_top`, `smart_play`.

### Verification checklist (step A)

1. Restart Kodi. Menu: labels start with `•`, Refresh (Local) absent, order acceptable.
2. Persist start: play an episode of a show with no `{showid}.json` → file appears in `<portable_data>\userdata\addon_data\nico.video.contextactions\` within ~1s, no toast. — **passed 2026-10-28** (`4.json`, A Man in Full S01E01).
3. Persist ticks: keep playing > 60s → `status.resume.position` advances about every 30s; pause → no change.
4. Persist stop: stop mid-episode → toast `… Progress saved (NN%)`, position = where you stopped. — **passed 2026-10-29** (position exact, e.g. 562.245s; toast not visually confirmed).
5. Persist end: let an episode finish → `completed`. — **passed 2026-10-29** (Deadliest Catch S15E01, `Playback Ended … strategy=completed`).
6. Movie playback → no profile written (log: no `Tracking playback`).
7. Smart Play: bind the remote Play button (README), restart. On the show from step 4 press Play → same episode starts ~5s before the stop position. Log `[SMART_PLAY:…]`: `Player.Open … -> {'result': 'OK'}` and `Playback started at X (wanted Y)`. — **passed 2026-10-29** (4 shows, start = wanted every time, no seek fallback).
8. Smart Play autoplay: let that episode end → does the next episode start? (report result) — **likely no** (2026-10-29): S15E01 started by Smart Play ended 09:43:34; the next playback (9s later) was the same episode, no `SMART_PLAY` line (looks manual). To confirm with the user; fix if confirmed: playlist from that episode.
9. Smart Play fallbacks: on a season that doesn't contain the saved episode → Kodi's normal play; on a movie → normal play. — season part **passed 2026-10-29** (`saved episode is in season 15, not 22` → `Default play (Play)`); movie not tested.
10. Smart Play derived: on a show without profile → `{showid}.json` with `"source": "derived"` is created, then playback per rules. — **passed 2026-10-29**: never played → S01E01 at 0 (A Gentleman in Moscow, A Knight of the Seven Kingdoms); last played fully watched → `completed` → default play (A Nearly Normal Family); Deadliest Catch → S15E01 at 0. `(from Kodi)` toast added after these runs, not yet seen.
11. Snapshot fix: Watched to Past... on a show, immediately Watched Toggle on the same show (queues) → after both, dates are the Watched to Past... date (log: `SNAPSHOT updated`).
12. Persist exit (R1): quit Kodi mid-episode → profile position = where you quit (log: `Playback Exit`).
13. Credits (R4): stop at > 92% → `completed`; Smart Play on that show → Kodi's default play.
14. Play key during playback (R3): Videos window with a video playing, focus a show, press Play → pause/resume as usual, no new episode.

### Smart Play (design)

Reads `{showid}.json` when a show or season is active and plays accordingly:

| Saved strategy | Behavior |
|----------------|----------|
| `in_progress` | Play the saved episode, resume 5s before the saved position (clamped ≥ 0) |
| `completed` | Kodi's default play (decided) |
| `manual_save` on an episode | Resume that episode at the saved position |
| `manual_save` on a show/season (no resume data) | Kodi's default play |

- Fallback everywhere = Kodi's default play (decided). `priority_stack` stays in the file but is not used. No profile → one is created from the library first (see "Profile creation").
- Net effect: Smart Play only changes behavior when the profile says `in_progress` on a valid episode in scope; then it resumes 5s before the saved position.
- Starts playback with `Player.Open` on the episode ID with resume; the existing service then saves the profile on stop. Read-only, no lock.
- **Trigger (decided): hijack regular Play on a show/season.** An addon cannot override Kodi's built-in Play, so this is done with a keymap: the Play key/button in the Videos window runs `smart_play.py`. For any item that isn't a tvshow/season, or while a video plays, the script runs the key's original action, `Action(PlayPause)` by default (builtin, not routed through the keymap, so no loop). Not covered: the built-in context menu "Play", skin/info-dialog Play buttons, mouse/touch. **Bound input (decided): the remote's Play button only.** The exact keymap tag depends on how the remote reaches Kodi (CEC → `<remote><play>`, IR/MCE → usually keyboard media key `<play_pause>`; phone apps like Kore/Yatse call JSON-RPC directly and cannot be intercepted). To identify: enable Kodi debug logging, press Play, read the `OnKey` line in `kodi.log`.
- **Season active, saved episode in another season (decided):** Kodi's default play for that season.
- **Saved episode missing from the library (decided):** Kodi's default play.
- **Starting playback (decided: try `Player.Open`, user verifies in Kodi):** `Player.Open` with the episode ID and a resume time = saved position − 5s; the RPC response is logged. User checks: right episode, right start time, and whether the next episode plays afterwards. If the resume time is not honored → fallback: start the episode, then `seekTime(saved − 5)` once playback starts. If playback stops after the episode → build a playlist starting at that episode.
- Profile location: `special://profile/addon_data/nico.video.contextactions/{showid}.json`.

### Snapshot fix (planned, step E)

- Problem: `{showid}.snap.json` (in `special://temp/nico.locks/`) holds each episode's `lastPlayed` as captured by the first action in a queue; later actions never overwrite entries; Refresh (Local/Internet) and Toggle restore from it; deleted when the last lock is released. An intentional date change made inside the queue is not in the snapshot, so a later restorer undoes it.
  - Watched to Past...: it creates the snapshot itself (old dates), then shifts dates. One queued Toggle/Refresh behind it is enough to undo the shift.
  - Move to Top: does not touch the snapshot. Needs a snapshot already alive (an earlier action still queued/running) plus a restorer behind it.
- Fix: new `common_locks.update_snapshot_entries(root_id, {idFile: lastPlayed}, tag)` — if the snapshot file exists, overwrite those entries (intentional writes are the new truth) and save; if it doesn't exist, do nothing (the next action captures the DB, which already has the new date).
- Callers:
  - `watched_past.py`: after the RPC + SQL writes, update all affected idFiles with the new date (`''` for Never).
  - `move_to_top.py`: after a successful episode write, look up the target's idFile (`_episodes_to_idfile`) and update it. Movies: not covered (see key collision open item).
- Restorers (`toggle_watch.py`, `refresh_internet.py`, local refresh in `common_actions.py`) unchanged.
- Test (live): on one show, run Watched to Past..., immediately run Watched Toggle on the same show (it queues). After both: `lastPlayed` equals the Watched to Past... date. Before the fix the old dates come back.

### Profile creation (decided)

- **On Smart Play with no profile:** build and write `{showid}.json` from the library, then play from it:
  - Most recently played episode (by `lastPlayed`) with a resume point → `in_progress` at that position.
  - Most recently played episode with a date but not watched (e.g. a Move to Top target) → `in_progress` at 0 (refined during review).
  - Most recently played episode fully watched → `completed` → Kodi's default play.
  - Show never played → profile starts at the first unwatched episode (season 0 last).
  - Marked with `status.source = "derived"`; strategy stays `in_progress`/`completed` so Smart Play's rules apply unchanged (refined during review, replaces a `derived` strategy label).
- **On playback start (episodes only):** write the profile only if none exists yet (confirmed), strategy `in_progress`, so a crash or force-quit mid-episode on a never-saved show still leaves a profile. Position is the library's resume point (0 for a fresh episode). If a profile already exists, start writes nothing; the first 30s tick updates it. Silent (no toast) at start (confirmed); stop/end keep their toast.
- **On playback stop/end:** create the profile if missing (already how `persist_show_by_id` behaves: it always writes the file, creating `addon_data/...` if needed). Episodes only.

### Periodic updates (decided)

- While an episode plays, the service samples `getTime()`/`getTotalTime()` from the player every 1s, in memory only (no write).
- Every 30s (fixed, not configurable) it writes the profile: strategy `in_progress`, position = latest sample. Applies to existing profiles too.
- Tick writes are silent (no toast), skip `fsync`, and are skipped when paused or when the position hasn't changed since the last write.
- Ticks within one episode don't archive history (paths unchanged); the first write for a new episode archives the previous status, as stop does.
- Position comes from the player, not the library resume point (stale during playback). This replaces the old conditional step C and the stop-time timing question.
- **On stop:** write `in_progress` with position = last sample (exact, no delta). Toast kept.
- **−5s rewind is applied on resume, not on save** (decided): Smart Play starts 5s before the saved position, clamped to ≥ 0. Covers stop and crash alike; saved positions stay exact.
- **On end:** `completed`, no delta. Toast kept.
- Crash: the profile holds the last 30s tick. Kodi's own resume point is not updated periodically, so Smart Play should resume from the profile position, not Kodi's (passing an explicit position to `Player.Open` — to verify).

- Interplay: Move to Top sets `lastPlayed` to now on its target, so a derived profile on that show points at that episode. Watched to Past... can leave several episodes with the same `lastPlayed`, so ties need a deterministic order (season, then episode).

## Decisions

- Move to Top sets `lastPlayed` to now on the target; watched status unchanged.
- Target: Episode → itself. Season → first unwatched of the season, else its first episode. TV Show → first unwatched of the show, else its first episode. Movie → itself.
- Ordering: by season then episode, season 0 (specials) last.
- Fixed 5s countdown (5s…1s), no cancel, not configurable.
- Show lock is taken after the countdown; target computed after the countdown.
- Write: one `SetEpisodeDetails` / `SetMovieDetails` RPC with `lastplayed` (single item, no SQL batch), then `Container.Refresh`.
- Notification taxonomy (as other actions): heading = show title, message = `<phrase> • <detail>`.
  - Countdown: `Moving to top in 5s…` — grey, silent, via `common_locks.notificationStatus`, 1000 ms each.
  - Queued: `Move to top queued…`.
  - Result: `Moved to top • S01E03` (movie: `Moved to top`) — standard `common_locks.notification`, 2500 ms.
- Persist: automatic save only for episodes (confirmed). Reload entry `nICo Dev • Reload Modules` stays visible (confirmed). Snapshot fix planned (step E).
- Script `move_to_top.py`, label `• Move to Top`, key `t`, visible for movie/tvshow/season/episode.
- README heading follows the `addon.xml` label: `Watched to Past...`.

## Open items

- `• Refresh (Local)` menu entry is commented out in `addon.xml` for now. The README notes it as disabled; `refresh_local.py` is untouched, and the README keymap `l` binding still works.
- Trailing `…` on the countdown message and standard (not grey) result toast: implemented as defaults, not explicitly confirmed.
- Lock/snapshot key collision: `_resolve_root_id` returns the movie ID for movies and the show ID for shows, so movie 5 and show 5 share the same lock and snapshot file. Effects: a movie action waits for an action on show 5, and a restore on show 5 also rewrites the movie's `lastPlayed` from the snapshot. Not planned. (Profile file collision is fixed: profiles are written only with a show ID.)
- Snapshot fix does not cover Move to Top on movies (no idFile lookup for movies).
- Smart Play does not cover Kodi's built-in context menu "Play", info-dialog Play buttons, mouse/touch, or phone remote apps.
- `Player.Open` single-episode playback may not continue to the next episode — to verify (checklist 8); fix if needed: build a playlist from that episode.
- No local test harness: code is only syntax-checked; behavior can only be validated in live Kodi.

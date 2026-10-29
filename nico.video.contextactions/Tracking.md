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
| A | Live verify (see "Verification checklist") | closed 2026-10-29 for 1.0.9 — passed 2, 4, 5, 7, 9 (season), 10, 12, 13, 14*, 11*; partial 8; open 1, 3, 6, 9 (movie) (*user-reported, not yet in `kodi.log`) |
| H | Fixes from code review R1–R5 (see "Review (2026-10-29)") | done — R3 fallback seen (`Default play (Play)`); R1, R2, R4 untested |
| B | Persist fixes (`smart_cmd.py`, `service.py`): automatic save for `episode` only; abort without show ID; automatic mode takes the show title from the library; create profile silently on playback start if none exists | done — verified live (checklist 2) |
| C | Position tracking (`service.py`): sample every 1s in memory, write every 30s (silent, no fsync, skipped when paused/unchanged), stop = exact last sample, end = `completed` | done — stop/end verified live; ticks not yet (checklist 3) |
| D | Smart Play (`smart_play.py`, new) incl. derived profile creation, `Smart resume` toast | done — verified live (checklist 7, 9 season, 10); autoplay open (8); changes 2026-10-29 below, user-reported working |
| D2 | Smart Play: open the single episode with resume (no start at 0.1s + seek), append later episodes to the video playlist after playback starts (only if the playlist is exactly the playing episode); `completed` → play the next unwatched episode (first unwatched after the saved one, else first unwatched; season scope; resume point − 5s or 0; toast `S01E04 (next)`; nothing unwatched → Kodi's default play) | done — user-reported working 2026-10-29; not yet checked in `kodi.log` (look for `Playlist before append`, `Completed — next unwatched`) |
| E | Snapshot fix: `common_locks.update_snapshot_entries`, called by `watched_past.py` and `move_to_top.py` | done — untested in Kodi |
| F | README: per-entry visibility table, Persist/Smart Play sections, remote keymap example | done |
| I | Navigation to the saved season/episode (`nav_focus.py`, service loop 0.1s) | done — user-reported working |
| J | Smart Play ignores an `in_progress` profile when the library resume point is empty | done — user-reported working |
| G | Release: 1.0.8 was never zipped; superseded by **1.0.9** (2026-10-29; re-released under the same version later that day with orphan-profile adoption, the 180s guard, navigation fixes and the autoplay resume menu — zip regenerated, QPC redeployed): version bumped in `addon.xml` and README, `nico.video.contextactions-1.0.9.zip` generated (addon files only, no dev docs), deployed to QPC (`deploy-qpc.bat`), committed and pushed. Step A closed with items 3, 6, 9 (movie), 11 (queued) unproven/skipped by decision | done |

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
| R6 | Refresh (Internet) recreated the show (dbid 6 → 12, new episode IDs; seen 2026-10-29 11:09:59) → `6.json` orphaned, history and `manual_save` lost; Smart Play then derived a new `12.json` from Kodi's resume point (`"source": "derived"`). Profiles are keyed by show ID. | Open: match/migrate profiles by another key (title, path) or rename on refresh. Not decided. | open |

Checked, no change needed:
- Snapshot update (`update_snapshot_entries`) runs under the show lock like every other snapshot reader/writer; key/value format matches `merge_and_save_snapshot` (`''` for Never).
- `move_to_top.py`: `target['episodeid']` present for episode/season/tvshow targets; movie path skipped as planned.
- `watched_past.py`: snapshot updated only for `affected` idFiles, with `target_str` (`None` → `''`).
- `Player.Open` `options.resume` as a time object is valid per the JSON-RPC schema.
- `create_only`, history archiving (ticks don't archive; first write for a new episode does), derived-profile rules match the plan; `source` is dropped by the next non-derived write.
- Reloader imports `move_to_top`, `smart_play`.

### Navigation to the saved path (step I, done 2026-10-29, user-reported working)

Entering a show selects the saved season, entering a season selects the saved episode (cursor only; nothing plays).

- Decided: both levels; automatic on entering (no key); `completed` profile → next unwatched episode (same pick as Smart Play; in a season list, that episode's season); release 1.0.9.
- `nav_focus.py` (`FocusNavigator`), ticked by the service loop. The loop now runs every 0.1s (`_LOOP_SECONDS`); player sampling stays at 1s (every 10th loop). Reacts when `Container.FolderPath` changes in the Videos window to `videodb://tvshows/titles/{id}/` (season list) or `…/{id}/{n}/` (episode list). Waits up to 8s for the list (`Container.IsUpdating`, `NumItems`), finds the item (`Season` label for seasons, `DBID` for episodes), `SetFocus(<view>,<index>,absolute)` on the visible standard view container (tested on skin Amber).
- Not re-triggered when going back up a level (parent path of the previous one), when returning from playback or non-Videos windows, or on list refresh (path unchanged). Empty paths ignored.
- The season segment of `videodb://` paths is not trusted (profile shows 18 for season 1): seasons are matched by `ListItem.Season`.
- Needs a Kodi restart after an update (service). `smart_play._next_unwatched` renamed `next_unwatched` (used by `nav_focus`).
- Visual lag: 1s polling replaced by 0.1s; a flash of the first item before the jump remains possible (Kodi draws the list first).

### Smart Play: library resume point reset (step J, done 2026-10-29, user-reported working)

An `in_progress` profile with position > 0 is ignored (start at 0) when the episode's library resume point is empty (reset, marked watched). `manual_save` still honored; `completed` unchanged. Trade-off: if Kodi quits/crashes during playback without storing its resume point, the profile's last position is ignored too (log: `Library resume point is empty`).

### Verification checklist (step A)

1. Restart Kodi. Menu: labels start with `•`, Refresh (Local) absent, order acceptable.
2. Persist start: play an episode of a show with no `{showid}.json` → file appears in `<portable_data>\userdata\addon_data\nico.video.contextactions\` within ~1s, no toast. — **passed 2026-10-28** (`4.json`, A Man in Full S01E01).
3. Persist ticks: keep playing > 60s → `status.resume.position` advances about every 30s; pause → no change. — **unproven 2026-10-29**: an 84s run was done, but the stop write overwrote the file and tick writes log at DEBUG only. To prove: read the file during playback, or enable debug logging.
4. Persist stop: stop mid-episode → toast `… Progress saved (NN%)`, position = where you stopped. — **passed 2026-10-29** (position exact, e.g. 562.245s; toast not visually confirmed).
5. Persist end: let an episode finish → `completed`. — **passed 2026-10-29** (Deadliest Catch S15E01, `Playback Ended … strategy=completed`).
6. Movie playback → no profile written (log: no `Tracking playback`).
7. Smart Play: bind the remote Play button (README), restart. On the show from step 4 press Play → same episode starts ~5s before the stop position. Log `[SMART_PLAY:…]`: `Player.Open … -> {'result': 'OK'}` and `Playback started at X (wanted Y)`. — **passed 2026-10-29** (4 shows, start = wanted every time, no seek fallback).
8. Smart Play autoplay: let that episode end → does the next episode start? (report result) — playlist fix works (`Playlist.Add N episodes`), but **autoplay after a `p`-started episode is not in `kodi.log`** (user reported yes 10:38; the logs 10:37:50–10:44 show no `Playback Ended` after any Smart Play start — the one near-end run, 10:42:56, was a `Stopped` at ≥92%). Redo once and leave it alone to the end.: S15E01 started by Smart Play ended 09:43:34; the next playback (9s later) was the same episode, no `SMART_PLAY` line (looks manual). User confirmed the replay was manual. Baseline (10:02, Kodi's own play via Enter on S15E01): next episode did not start either → Kodi's `videoplayer.autoplaynextitem` is at its default (off for episodes) on both instances; not a Smart Play bug. Kodi delivered `Playback Ended` (R2 safety net not needed there). Re-test with the setting enabled (`videoplayer.autoplaynextitem` = `2,3`): run A (Enter) **passed** 10:30 — S15E01 ended → `Playback Ended` (completed) → S15E02 tracked 0.5s later, so Kodi advances by itself and delivers Ended between episodes. Run B (`p`, A Spy Among Friends S01E01, let it end) **failed** 10:32 — `Playback Ended`, nothing followed: `Player.Open` on one episode queues nothing. Fix (decided: rest of the show, also when Play is pressed on a season): `smart_play.py` fills video playlist 1 with the saved episode + all later episodes (season 0 last), `Player.Open` playlist position 0 with the same resume time; fallback to the single episode. Result 10:37 (A Spy Among Friends): `Playlist.Add 5 episodes from 36 -> OK`, `Player.Open {'playlistid': 1, 'position': 0}` OK. **The resume time is not honored for playlist items** (started at 0.1s, wanted 642.6s) → the existing `seekTime` fallback fixed it (log `Resume time not honored — seekTime(642.6)`); a start within 10s of the wanted time needs no seek. **Seek fallback fires on every playlist start** (Kodi never honors the resume option for playlist items: always starts at 0.1s, then seeks; cosmetic blip). **Autoplay through the playlist not yet confirmed**: both Smart Play runs were stopped by hand; the two episodes that ended 10:36–10:37 were started with Enter, not `p`. Redo run B result (user report, 2026-10-29 ~10:38): **passed** — next episode started at the end of a `p`-started episode. Not yet seen in `kodi.log` (log last flushed 10:37:49). Note: a Smart Play attempt at 10:04 fell back to default play because run A had just saved `completed` — Kodi's resume prompt for S15E02 was Kodi's, as designed.
9. Smart Play fallbacks: on a season that doesn't contain the saved episode → Kodi's normal play; on a movie → normal play. — season part **passed 2026-10-29** (`saved episode is in season 15, not 22` → `Default play (Play)`); movie not tested.
10. Smart Play derived: on a show without profile → `{showid}.json` with `"source": "derived"` is created, then playback per rules. — **passed 2026-10-29**: never played → S01E01 at 0 (A Gentleman in Moscow, A Knight of the Seven Kingdoms); last played fully watched → `completed` → default play (A Nearly Normal Family); Deadliest Catch → S15E01 at 0. `(from Kodi)` toast added after these runs, not yet seen.
11. Snapshot fix: Watched to Past... on a show, immediately Watched Toggle on the same show (queues) → after both, dates are the Watched to Past... date (log: `SNAPSHOT updated`). — **partial 2026-10-29**: `SNAPSHOT updated — 2 idFiles overwritten` logged and dates persisted across two consecutive Watched to Past runs; the queued case: user reports it looks fine (2026-10-29), not yet in `kodi.log`. Retried 2026-10-29 11:05 and 11:10: `SNAPSHOT updated` logged each time, but every action finished (lock released, snapshot deleted) before the next started — no `queued` line, so the queued path is **still untested** (Watched to Past takes ~25-50ms; queue it behind a running Refresh (Internet) instead).
12. Persist exit (R1): quit Kodi mid-episode → profile position = where you quit (log: `Playback Exit`). — **passed 2026-10-29 10:41** (`Playback Exit … position=754.968` before `Application stopped`; next `p` resumed at 750.0s).
13. Credits (R4): stop at > 92% → `completed`; Smart Play on that show → Kodi's default play. — **passed 2026-10-29 10:42** (stop near the end → `strategy=completed`, `100.0%`; next `p` → `Default play (Play) — strategy=completed`).
14. Play key during playback (R3): Videos window with a video playing, focus a show, press Play → pause/resume as usual, no new episode. — **passed (user report 2026-10-29)**: `p` during playback is a no-op; not yet in `kodi.log` (log buffered).

### Smart Play (design)

Reads `{showid}.json` when a show or season is active and plays accordingly:

| Saved strategy | Behavior |
|----------------|----------|
| `in_progress` | Play the saved episode, resume 5s before the saved position (clamped ≥ 0); if Kodi's library resume point is empty → start at 0 (step J) |
| `completed` | Play the next unwatched episode (step D2): first unwatched after the saved one, else first unwatched (season scope); starts at its library resume point − 5s or 0; nothing unwatched → Kodi's default play |
| `manual_save` on an episode | Resume that episode at the saved position (library resume point not consulted) |
| `manual_save` on a show/season (no resume data) | Kodi's default play |

- Fallback = Kodi's default play (decided). `priority_stack` stays in the file but is not used. No profile → one is created from the library first (see "Profile creation").
- Net effect: Smart Play changes behavior when the profile says `in_progress` on a valid episode in scope (resume 5s before the saved position) or `completed` (next unwatched episode).
- Starts playback with `Player.Open` on the single episode ID with resume (honored; playlist items ignore it), then appends the later episodes to the video playlist for autoplay; the existing service saves the profile on stop. Read-only, no lock.
- **Trigger (decided): hijack regular Play on a show/season.** An addon cannot override Kodi's built-in Play, so this is done with a keymap: the Play key/button in the Videos window runs `smart_play.py`. For any item that isn't a tvshow/season, or while a video plays, the script runs the key's original action, `Action(PlayPause)` by default (builtin, not routed through the keymap, so no loop). Not covered: the built-in context menu "Play", skin/info-dialog Play buttons, mouse/touch. **Bound input (decided): the remote's Play button only.** The exact keymap tag depends on how the remote reaches Kodi (CEC → `<remote><play>`, IR/MCE → usually keyboard media key `<play_pause>`; phone apps like Kore/Yatse call JSON-RPC directly and cannot be intercepted). To identify: enable Kodi debug logging, press Play, read the `OnKey` line in `kodi.log`.
- **Season active, saved episode in another season (decided):** Kodi's default play for that season.
- **Saved episode missing from the library (decided):** Kodi's default play.
- **Starting playback (done, verified live):** `Player.Open` with the episode ID and a resume time = saved position − 5s; the RPC response is logged. If the resume time is not honored → fallback: `seekTime(saved − 5)` once playback starts. Autoplay: later episodes appended to the video playlist after playback starts (see step D2).
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
  - Most recently played episode fully watched → `completed` → next unwatched episode (Kodi's default play if none).
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

- Remote Play button (2026-10-29): on a Windows media remote the button is an app command, not `<keyboard>`/`<remote>`; without `<appcommand><play_pause>` in `<Videos>` Kodi's global `PlayPause` ran and showed its own resume prompt. Fixed in the user's `keyboard.xml` (local and QPC), user-confirmed; documented in README. Smart Play falling back to Kodi's default play on a season whose saved episode is in another season (and on episodes) is by design; a season-scope improvement (play that season's in-progress/first unwatched episode without Kodi's prompt) was proposed, not decided.
- Review of 1.0.9 (2026-10-29):
  1. Step J guard — done: ignore an `in_progress` profile only when its position is past `video.ignoresecondsatstart` (advancedsettings.xml, default 180s). A crash/quit after that point where Kodi stored nothing still restarts at 0.
  2. Navigation re-entry — done: leaving the Videos window without playback resets the last-path memory, so reopening a show from a widget jumps again. Side effect: returning to the same folder from Home/Settings jumps the cursor to the saved item. Also fixed: the "going back" test compared paths including Kodi's `?xsp=…`/`?tvshowid=…` query, so it never matched and going back to the season list re-jumped (seen in the 11:35/11:39 log); the query is now stripped. INFO logging added for each decision (`entered … list`, `back to … — left to Kodi`, `gave up after 8s: <reason>`, `no profile`, `nothing to select …`). A service that was not restarted after an update looked like broken navigation.
  3. Playlist items (autoplay) ignore the library resume point: a partially watched later episode starts at 0 (Kodi behavior) — done (step K): `service.py` shows Kodi's resume menu ("Resume from mm:ss" with Kodi's localized string 12022 / "Restart"; first entry default, cancel = resume; episode info in a toast) when an episode starts < 10s after another one's `Ended` and a saved position ≥ 30s exists (profile status/history first, else Kodi's resume point; reset rule as in step J). Waits for the user, no timeout; dialog in a thread so the service loop keeps running. Verified live (prompt worked); menu restyled 2026-10-29, restyle not yet seen live. `min_resume_seconds()` moved to `smart_cmd.py`.
  4. R6 — done: `smart_cmd.adopt_orphan_profile` (called by `load_profile` and `persist_show_by_id`): renames the profile of the same-named show whose old ID is gone to the new ID and remaps episodes by season/episode (history too). Unit-checked with stubs (adoption, same-name-existing show skipped); not yet live. Live test: delete the new `{id}.json` of a show that Refresh (Internet) recreated, press Play on it.
  5. `nav_focus` keeps the `smart_play` it first imported until Kodi restarts (Reload Modules does not reach the service).
  6. Unproven: checklist 3 (ticks) and 11 (queued snapshot).
- `• Refresh (Local)` menu entry is commented out in `addon.xml` for now. The README notes it as disabled; `refresh_local.py` is untouched, and the README keymap `l` binding still works.
- Trailing `…` on the countdown message and standard (not grey) result toast: implemented as defaults, not explicitly confirmed.
- Lock/snapshot key collision: `_resolve_root_id` returns the movie ID for movies and the show ID for shows, so movie 5 and show 5 share the same lock and snapshot file. Effects: a movie action waits for an action on show 5, and a restore on show 5 also rewrites the movie's `lastPlayed` from the snapshot. Not planned. (Profile file collision is fixed: profiles are written only with a show ID.)
- Snapshot fix does not cover Move to Top on movies (no idFile lookup for movies).
- Smart Play does not cover Kodi's built-in context menu "Play", info-dialog Play buttons, mouse/touch, or phone remote apps.
- Kodi's `Player.Open` ignores `options.resume` when the item is a `playlistid` (source: `PlayerOperations.cpp`); that is why the playlist start always began at 0.1s. Replaced by single-episode open + playlist append (step D2).
- No local test harness: code is only syntax-checked; behavior can only be validated in live Kodi.

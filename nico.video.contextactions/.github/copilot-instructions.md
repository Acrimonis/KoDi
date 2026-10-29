# nICo Video Context Actions — Copilot Instructions

## Project overview

A Kodi Python addon (`nico.video.contextactions`) providing five context-menu actions for silent library management: **Watched Toggle**, **Watched to Past...**, **Move to Top**, **Refresh (Local)**, **Refresh (Internet)**. Targets Kodi's `xbmc.python` 3.0.1+ API.

## Dev environment

- **Live path (no deploy step):** `Y:\.kodi_d\addons\nico.video.contextactions\`
- **Kodi log:** `\\Qpc\p\.kodi_d\kodi.log`
- **Kodi DB:** `\\Qpc\p\.kodi_d\userdata\database\MyVideos131.db`
- **SQLite CLI:** `C:\Users\nbadino\Programs_nICo\_Dev_\sqlite-tools\sqlite3.exe`
- **No Python on PATH** — syntax checking is visual; validation is live Kodi testing.
- **No build, test, or lint toolchain exists.**
- **Always allowed:** Read `kodi.log` at `\\Qpc\p\.kodi_d\kodi.log` at any time to investigate behaviour, errors, or verify changes — no confirmation needed.
- **Always allowed:** Read `\\Qpc\p\.kodi_d\userdata\database\MyVideos131.db` (SQLite) at any time to inspect library state — no confirmation needed. May run the SQLite CLI (`C:\Users\nbadino\Programs_nICo\_Dev_\sqlite-tools\sqlite3.exe`) against this database freely (read queries; write only when explicitly requested).

## Architecture

### Entry points
Each action is a standalone script invoked directly by Kodi via `RunScript()` or the context menu (`addon.xml`). Each runs as its own **thread (sub-interpreter)** inside Kodi's process:

| Script | Action |
|---|---|
| `resources/lib/toggle_watch.py` | Watched Toggle |
| `resources/lib/watched_past.py` | Watched to Past... |
| `resources/lib/move_to_top.py` | Move to Top |
| `resources/lib/refresh_local.py` | Refresh (Local NFO) |
| `resources/lib/refresh_internet.py` | Refresh (Internet scraper) |
| `resources/lib/smart_cmd.py` | Persist • Save Show Profile (also called by `service.py`: on episode start if no profile, every 30s while playing, on stop/end). Also `load_profile`, `adopt_orphan_profile` (takes over the profile of a show that Refresh (Internet) recreated under a new ID: same show name, old ID gone from the library, exactly one match; episodes remapped by season/episode) and `min_resume_seconds` (Kodi's `video.ignoresecondsatstart`, default 180) |
| `resources/lib/smart_play.py` | Smart Play — bound to the remote Play button via keymap, not a menu entry; `in_progress` → resume the saved episode (episode opened alone with the resume time, later episodes appended to the video playlist afterwards because playlist items ignore the resume time; ignored if Kodi's resume point is empty and the saved position is past the Kodi minimum), `completed` → next unwatched episode, otherwise the key's original action (`PlayPause`, overridable by script argument) |
| `resources/lib/service.py` | Background service (loop 0.1s): tracks episode playback position (1s samples, 30s writes), ticks the library navigator, and on autoplay (an episode starting < 10s after another's end) with a saved position ≥ 30s pauses and shows Kodi's resume context menu (Resume from mm:ss / Restart; first entry default, cancel = resume; position from profile status/history, else Kodi's resume point) |
| `resources/lib/nav_focus.py` | Library navigation: on entering a show/season in the Videos window, moves the cursor to the saved season/episode from `{showid}.json` (`SetFocus`); used by `service.py` |
| `resources/lib/common_locks.py` (run as script) | nICo Dev • Reload Modules |

### Shared modules
- **`common_actions.py`** — All shared utilities + the full local refresh logic (`refresh()`). Contains `get_episodes()`, `_get_canonical_snapshot()`, `_restore_lastplayed()`, `_snapshot_playcount()`, `_restore_playcount()`, `_resolve_root_id()`, `execute_rpc()`, `_navigate_list()`, `_fetch_show_title()`, `_wait_for_db_change()`, `_wait_for_all_changed()`, etc.
- **`refresh_local.py`** — 4-line thin wrapper; all real logic lives in `common_actions.refresh()`.
- **`common_locks.py`** — Per-show file mutex, shared snapshot persistence, queue-status notifications.
- **`common_db.py`** — SQLite context manager (`kodi_db_context()`) targeting the latest `MyVideos*.db`.

### Sub-interpreter isolation
Kodi runs each plugin invocation in a **separate Python sub-interpreter**. `id(sys.modules)` differs between concurrent calls, so **Python globals are never shared across actions**. All inter-thread state sharing uses **lock files + JSON snapshot files** in `special://temp/nico.locks/` (resolved to `%APPDATA%\Kodi\cache\nico.locks\`).

## Key conventions

### Lock pattern — every action must follow this
```python
root_id = common_actions._resolve_root_id(dbid, dbtype)  # always use tvshowid as mutex key
lock_path, was_queued = common_locks.acquire(root_id, tag=tag, show_name=show_title,
    on_queue=lambda: xbmcgui.Dialog().notification(..., "Action queued…", …))
if not was_queued:
    xbmcgui.Dialog().notification(...)  # start notification only if not waiting
try:
    # ... do work ...
finally:
    common_locks.release(lock_path, root_id, tag=tag, show_name=show_title)
```
- `_resolve_root_id` converts season/episode dbid → tvshowid so the mutex is per-show, not per-item.
- `acquire()` writes a `queued` lock file immediately on first contention so the snapshot system sees us as active before the current holder releases.

### Lock file statuses
Lock file content (written by `_write_lock_status()`):
- `'held'` — action is running
- `'queued'` — action is waiting for the lock
- `'inet'` — internet refresh running (blocks like `held`, shown separately in queue banner)

### Shared snapshot system (lastPlayed)
`_get_canonical_snapshot(episode_ids, root_id)` → `{idFile: lastPlayed}`:
- **First action** for a show: creates `{root_id}.snap.json` from current DB state (truth before any action).
- **Subsequent queued actions**: inherit the file, only add new idFiles — **existing entries are never overwritten**.
- Purpose: prevents a queued TOGGLE from restoring a scanner-corrupted intermediate state when REFRESH releases its lock while the background scanner is still running.
- `_delete_snapshot_if_last()` removes the file when the last lock for that show is released.

### Playcount snapshot (separate from lastPlayed snapshot)
`_snapshot_playcount(idfile_list)` is **not** merged into the canonical snapshot. It is taken **immediately after lock acquisition** (not at queue time), so it captures the state after any prior queued action (e.g., a TOGGLE that ran before a REFRESH in the queue). Restored via `_restore_playcount()` after the refresh completes.

### Post-toggle navigation (single episode → Watched)
When a single episode is toggled to **Watched**, `_navigate_list(target_idx)` is called to move the active container focus to the first remaining unwatched episode in the season.
- Uses `Action(Down)` / `Action(Up)` builtins with a 30ms sleep per step.
- Only fires when `new_val == 1` (marking watched) and a next unwatched episode exists.

### Watch in Past — preference persistence
The last-used delta is saved to `special://profile/addon_data/nico.video.contextactions/prefs.json` (key `watch_past_days`). Default is 10 days. The dialog pre-selects the saved value on each invocation.

### Nudge+SQL pattern (bulk toggle / watch-in-past)
For batch operations across many episodes:
1. **1 `SetEpisodeDetails` RPC per season** — fires Kodi's item-level `OnUpdate` event → UI badges update.
2. **SQL batch for remaining episodes** — direct `UPDATE files SET playCount = ?` (~10ms regardless of count).
3. **UNWATCHED = `NULL` (not `0`)** in `files.playCount` — `COUNT(files.playCount)` in `season_view` excludes NULLs, so season watched counts are correct.
4. `lastPlayed` is **never** passed to `SetEpisodeDetails` — always restored separately via `_restore_lastplayed()`.

### Local refresh flow (tvshow/season)
1. Snapshot `lastPlayed` and `playcount` after lock acquisition.
2. `RefreshEpisode` per episode (synchronous RPC, no background scanner).
3. `RefreshTVShow(ignorenfo=False)` — triggers Kodi's async background scanner.
4. Poll marker file (`_wait_for_db_change`) until `lastPlayed` changes (signals scanner started writing).
5. `_wait_for_all_changed` — wait until all monitored files changed. Exits on: (1) all files changed, (2) idle timeout (no change for 5s), (3) `Library.IsScanningVideo == False` once at least one file changed, (4) hard timeout (adaptive: `interval_estimate × remaining × 10`).
6. Restore `lastPlayed` via `_restore_lastplayed()`, then `playcount` via `_restore_playcount()`.

Single episode local refresh uses the same snapshot/restore cycle but calls `RefreshEpisode` once and polls with a 5s timeout.

### Internet refresh flow
- Handles all four dbtypes. For `tvshow`/`season`: uses `VideoLibrary.RefreshTVShow(ignorenfo=True, refreshepisodes=True)` and expects `1 + N episode` `OnUpdate` events. For `movie`/`episode`: calls the corresponding `Refresh{Movie|Episode}` RPC (expects 1 event).
- Tracks completion via `xbmc.Monitor.onNotification` counting `VideoLibrary.OnUpdate` events (expected = 1 show + N episodes).
- **Idle timeout only** (10s no `OnUpdate`) — no hardcoded wall-clock limit so large shows don't time out mid-scrape.
- Restores `playcount` after completion (internet scraper can reset it when recreating episode entries).
- Lock status written as `'inet'` after acquire so queue banner shows "internet fetch" separately.

### Episode resolution (Tier 1 + Tier 2 fallback)
`get_episodes(dbid, dbtype)` tries:
1. `VideoLibrary.GetEpisodes(tvshowid=…)` or `GetEpisodes(filter={seasonid})` (Tier 1).
2. If Tier 1 returns 0: for tvshow → `GetSeasons` then `GetEpisodes(tvshowid, season=N)` per season. For season → regex parse `ListItem.FolderPath` videodb URL to extract showid + season number.

### Notification pattern
- **Start**: show immediately if `not was_queued` (queued actions get a "queued…" notif from `on_queue` callback instead).
- **End**: always show completion/error notification (2500ms for action results, 3000ms for refresh).
- **Queue banner** (`_show_queue_notification()`): shown every 2–3s while polling; call `suppress_queue_notification(duration_ms)` after each end notification to prevent it from immediately overwriting the result.

### Logging convention
All log lines use the format: `nICo Context: [{tag}] message` where `tag = "ACTION:ShowTitle"` (e.g., `TOGGLE:Les Sisters`, `REFRESH_Internet:A Knight of the Seven Kingdoms`). This makes grepping the log per-show trivial.

### RPC helper
```python
common_actions.execute_rpc("VideoLibrary.SetEpisodeDetails", {"episodeid": 123, "playcount": 1})
```
Returns the full parsed JSON response dict. Always check `response.get('result') == 'OK'` for write RPCs.

### Kodi DB key tables
- `files` — `idFile`, `playCount` (NULL = unwatched), `lastPlayed`, `strFilename`, `idPath`
- `episode` — `idEpisode`, `idShow`, `idFile`, `c00` (title), `c12` (season), `c13` (episode num)
- `tvshow` — `idShow`, `c00` (title)
- `path` — `idPath`, `strPath`
- `tvshowlinkpath` — links show to its source paths (used for multi-path shows)

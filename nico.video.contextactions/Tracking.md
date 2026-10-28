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
- Script `move_to_top.py`, label `• Move to Top`, key `t`, visible for movie/tvshow/season/episode.
- README heading follows the `addon.xml` label: `Watched to Past...`.

## Open items

- `• Refresh (Local)` menu entry is commented out in `addon.xml` for now. The README notes it as disabled; `refresh_local.py` is untouched, and the README keymap `l` binding still works.
- Trailing `…` on the countdown message and standard (not grey) result toast: implemented as defaults, not explicitly confirmed.
- Refresh risk: a Refresh/Toggle queued behind Move to Top may restore an older `lastPlayed` from the shared snapshot. Same exposure as Watched to Past...; accepted, not fixed. Fix would be a snapshot-overwrite helper in `common_locks.py`.
- README "all five actions visible for movie/tvshow/season/episode" is wrong for Watched to Past... (not shown for movies; `addon.xml` visibility is tvshow/season/episode).
- Persist (`smart_cmd.py` + `service.py`), found while documenting, not fixed:
  - Automatic save runs on playback stopped/ended for any library item with a DBID, including movies.
  - Profile file is `{show_id or dbid}.json`: a movie and a TV show with the same numeric ID write the same file.
  - Show title comes from `ListItem.TVShowTitle`/`ListItem.Label` (the focused list item), not the item that was playing; after playback ends the focus may be on another show, so `info.show_name`, `location` and the toast can name the wrong show. The file name (show ID) stays correct.
  - Whether Kodi has already written the final resume point when `onPlayBackStopped` fires is unverified (affects `in_progress` vs `completed`).
  - Nothing reads the profile.
- No Python toolchain: the script can only be validated in live Kodi.

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
| `addon.xml`: add `Silent • Move to Top` menu item | done — untested in live Kodi |
| `addon.xml`: add `nICo Dev • Reload Modules` menu item (runs `common_locks.py` reloader) | done |
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
- Script `move_to_top.py`, label `Silent • Move to Top`, key `t`, visible for movie/tvshow/season/episode.
- README heading follows the `addon.xml` label: `Watched to Past...`.

## Open items

- Trailing `…` on the countdown message and standard (not grey) result toast: implemented as defaults, not explicitly confirmed.
- Refresh risk: a Refresh/Toggle queued behind Move to Top may restore an older `lastPlayed` from the shared snapshot. Same exposure as Watched to Past...; accepted, not fixed. Fix would be a snapshot-overwrite helper in `common_locks.py`.
- README is out of date vs `addon.xml`: `Persist • Save Show Profile` (`smart_cmd.py`) undocumented, Refresh/Toggle labels differ. Not addressed in this pass.
- `.github/copilot-instructions.md` still says "Silent Watch in Past" and "four actions".
- No Python toolchain: the script can only be validated in live Kodi.

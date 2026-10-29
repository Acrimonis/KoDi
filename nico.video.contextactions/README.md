# nICo Video Context Actions for Kodi

**Addon ID:** `nico.video.contextactions`  
**Version:** 1.0.8 
**Author:** nICo BaD  
**License:** GPL-2.0-only

A lightweight Kodi addon that adds silent, high-performance library management actions to the right-click context menu. Supports Movies, Episodes, TV Shows, and Seasons.

---

## Features

### Watched to Past...
Clamps the `lastPlayed` date of recently-watched episodes back in time, without changing their watched/unwatched status.
- **Scope:** Episode → that episode only. Season → all episodes in that season. TV Show → all episodes across all seasons.
- **Delta selection:** On each invocation a dialog prompts for how far back to shift: `Yesterday / 3 days / 1 week / 10 days / 1 month / 6 months / Never (clear dates)`. The last choice is remembered across restarts (saved to `addon_data/.../prefs.json`).
- **Logic:** Any episode whose `lastPlayed` is **more recent than `now − delta`** is clamped to exactly `now − delta`. Episodes already older, or never watched, are untouched. **Never** clears `lastPlayed` entirely for all watched episodes.
- **UI refresh:** 1 `SetEpisodeDetails` RPC per affected season fires the UI event; remaining episodes written via SQL batch.
- **Notification:** `Watch date to 14 May 26 • 8 episodes` / `Watch date cleared • 8 episodes`.
- **Use case:** Prevents a binge-watched show from jumping to the top of your "last played" sort order.

### Move to Top
Sets the `lastPlayed` date of a target item to now, without changing its watched status.
- **Target:** Episode → the episode itself. Season → first unwatched episode of the season, or its first episode if all are watched. TV Show → first unwatched episode of the show, or its first episode if all are watched (specials, season 0, are considered last). Movie → the movie itself.
- **Delay:** Fixed 5-second countdown, not cancellable. The show lock is taken after the countdown and the target is computed then.
- **Notification:** Non-blocking toasts with the show title as heading. Countdown (grey): `Moving to top in 5s…` → 4s → 3s → 2s → 1s. Result: `Moved to top • S01E03` (movies: `Moved to top`).
- **Use case:** Brings a show to the top of your "last played" sort order so it is the next one to continue.

### Watched Toggle
Intelligently switches an item between "Watched" and "Unwatched" status.
- **Movies & Episodes:** Toggles the individual item. After toggling an episode, automatically moves focus to the first unwatched episode in the season (if any).
- **TV Shows & Seasons:** Batch-updates all episodes. If any episode is unwatched, the entire set is marked watched; otherwise all are marked unwatched.
- **Preserves Last Played dates:** Uses one `SetEpisodeDetails` RPC per season (fired before SQL so Kodi detects the change and fires item-level events → badges update in both directions), then writes the remaining episodes directly via SQL batch (~10ms regardless of episode count). Original `lastPlayed` dates are silently restored via SQL after the toggle — no corruption, no sort-order side effects.
- **Season state awareness:** When toggling a single episode, the notification indicates if the season's watched state changed (e.g. all episodes just became watched/unwatched).
- **Rich notification:** Shows result as `[Show Name] • Changed to Watched: 3 seasons, 22 episodes` (singular/plural aware). Single episodes and movies are also notified.
- **Path Fallback:** Includes a Tier 2 regex parser for `videodb://` paths to ensure reliability even when standard InfoLabels fail.

### Refresh (Internet)
Rescrapers the selected item's metadata from the internet (equivalent to `ignorenfo=True`).
- If the internet scraper returns no data and the item would be lost, the addon automatically falls back to a Local NFO refresh to prevent accidental deletion.
- Supported for: `movie`, `tvshow`, `season`, `episode`.

### Refresh (Local)
> **Currently disabled:** the context menu entry is commented out in `addon.xml`. The script (`refresh_local.py`) is unchanged and can still be bound to a key (see Manual Keyboard Mapping).

Refreshes the selected item's metadata using local NFO files (equivalent to `ignorenfo=False`).
- **Movies & Episodes:** Refreshes the single item.
- **TV Shows & Seasons:** Recursively refreshes the container and all child episodes. Notification shows count (e.g. `1 show, 3 seasons, 62 episodes`). Any per-episode failures are reported in the notification.
- Supported for: `movie`, `tvshow`, `season`, `episode`.

### Persist • Save Show Profile
Bookmarks where you are in a show by writing a profile to `addon_data/nico.video.contextactions/{showid}.json`. Available for TV Shows, Seasons and Episodes.
- **Content:** show name/ID, readable location (`Show • Season 2 • Episode 5`), timestamp, `videodb://` paths (show/season/episode), episode title, and for episodes the resume info (position, total, percentage, strategy). Keeps the last 5 previous locations in `history`; a location is archived only when it changed. Profiles built by Smart Play carry `"source": "derived"`.
- **Triggers:**
  - **Manual:** the context menu entry (strategy `manual_save`).
  - **Automatic:** a background service (`service.py`, starts with Kodi) watches playback of **library episodes only** (movies are ignored):
    - **Start:** if the show has no profile yet, one is created silently (`in_progress`, library resume point). An existing profile is not touched at start.
    - **While playing:** the position is sampled every second in memory and the profile is written silently every 30 seconds (`in_progress`), skipped while paused or if the position hasn't changed.
    - **Stop:** `in_progress` at the exact last position.
    - **End:** `completed`.
    - **Next item starts without a stop/end** (playlist advance, Smart Play over a playing episode): the previous episode is saved silently at its last position first.
    - **Kodi quits during playback:** the last position is saved silently (best-effort; Kodi does not report a stop on exit).
    - Any automatic save at ≥ 92% of the duration is recorded as `completed` (Kodi's default watched threshold), so a stop in the end credits is not resumed.
  - In automatic saves the show name comes from the library, not the focused list item.
- **Notification:** `Location bookmarked.` (manual, show/season) or `Season 02 Episode 05 • Progress saved (37%)` (manual on an episode, and automatic stop/end). Start and 30-second writes are silent.
- **Location:** `special://profile/addon_data/nico.video.contextactions/{showid}.json` (portable install: `<portable_data>\userdata\addon_data\nico.video.contextactions\`). The folder is created on first write.
- Read by Smart Play.

### Smart Play
Replaces the regular **Play** on a TV show or season. Bound to the remote's Play button through a keymap (see "Smart Play on the remote's Play button" below); not a context menu entry. Reads that show's `{showid}.json`:
- `in_progress` (or a manual save) on an episode in scope → play that episode, starting 5 seconds before the saved position.
- Anything else → Kodi's default play: `completed`, no resume data, saved episode missing from the library, or (season active) saved episode in another season.
- No profile → one is created from the library first (`"source": "derived"`): the most recently played episode (resume point, or dated but unwatched → `in_progress`; watched → `completed`), or the first unwatched episode if the show was never played (season 0 last).
- Any other item (movie, episode, non-library), or a video already playing/paused → Kodi's default play, unchanged.
- "Kodi's default play" = the button's original action, `PlayPause` (what Kodi's default keymaps bind to the remote's `play` and the keyboard's `play_pause`). Another action can be passed as a script argument: `RunScript(…/smart_play.py,Play)`.
- Notification when it resumes from the profile: `Smart resume • S01E01 at 9:17` (start position, i.e. saved − 5s); suffix `(from Kodi)` when the profile was just built from Kodi's watch history (`"source": "derived"`). Fallbacks show nothing (Kodi's default play).
- Playback starts with `Player.Open` and an explicit resume time. The start position is checked after playback begins; if Kodi ignored the resume time, the script seeks. Everything is logged under `[SMART_PLAY:<show>]`.

### Concurrent Action Safety
All actions use a **per-show file-based mutex** (`{showid}_{pid}.lock` in Kodi's temp dir) to prevent two operations running on the same show at the same time.
- If an action is already running on a show, new actions queue automatically and show a **"queued…"** notification.
- If the lock owner process crashes, stale locks are detected and removed on the next invocation using the Win32 `OpenProcess` API.
- **Notification rules:** Free lock → start notif + end notif. Queued → queued notif + end notif only (no duplicate start notif).

---

## Supported Item Types

Context menu entries per item type (`addon.xml` visibility):

| Entry | Movie | TV Show | Season | Episode |
|-------|:-----:|:-------:|:------:|:-------:|
| • Refresh (Internet) | ✓ | ✓ | ✓ | ✓ |
| • Refresh (Local) — *disabled* | – | – | – | – |
| • Watched to Past... | – | ✓ | ✓ | ✓ |
| • Watched Toggle | ✓ | ✓ | ✓ | ✓ |
| • Move to Top | ✓ | ✓ | ✓ | ✓ |
| nICo Dev • Reload Modules | ✓ | ✓ | ✓ | ✓ |
| Persist • Save Show Profile | – | ✓ | ✓ | ✓ |

Smart Play has no menu entry (remote Play button via keymap).

---

## Installation

1. Place the `nico.video.contextactions` folder into your Kodi addons directory:
   - **Windows:** `%APPDATA%\Kodi\addons\`
   - **Linux:** `~/.kodi/addons/`
   - **macOS:** `~/Library/Application Support/Kodi/addons/`

2. Restart Kodi or enable the addon via **Settings → Add-ons → My add-ons**.

3. The context menu entries appear automatically on supported library items (see Supported Item Types). Smart Play needs the keymap entry below.

> A newly installed addon may be **disabled** (e.g. a fresh portable profile). If no entries appear, enable it in **Settings → Add-ons → My add-ons**.

---

## Development

- **Reload Modules:** the context menu entry `nICo Dev • Reload Modules` runs `resources/lib/common_locks.py`, which reloads the addon's cached Python modules without restarting Kodi (toast: `nICo Dev PlugiN: N modules reloaded`). Changes to `addon.xml` and to the background service (`service.py`, `smart_cmd.py` as used by it) still require a Kodi restart.
- **Deploy scripts** (repo root, `robocopy /MIR` into a Kodi addons folder, excluding `.git`, `.github`, `__pycache__`, `AGENTS.md`, `Tracking.md`, `*.zip`, `*.bat`):
  - `deploy.bat` → `D:\.kodi\portable_data\addons\nico.video.contextactions`
  - `deploy-qpc.bat` → `P:\.kodi_d\addons\nico.video.contextactions`
- **Tracking.md** logs the status, decisions and open items of ongoing work.

---

## Advanced: Manual Keyboard Mapping

To bind any action to a keyboard shortcut, edit your local `keyboard.xml`.

**File Location:** `%APPDATA%\Kodi\userdata\keymaps\keyboard.xml`

Add the following inside the `<keymap>` tags. This targets the Video Library specifically to avoid conflicts with global navigation:

```xml
<keymap>
    <Videos>
        <keyboard>
            <!-- Watch Toggle -->
            <q>RunScript(special://home/addons/nico.video.contextactions/resources/lib/toggle_watch.py)</q>
            <!-- Watch in Past -->
            <w>RunScript(special://home/addons/nico.video.contextactions/resources/lib/watched_past.py)</w>
            <!-- Internet Refresh -->
            <i>RunScript(special://home/addons/nico.video.contextactions/resources/lib/refresh_internet.py)</i>
            <!-- Local Refresh -->
            <l>RunScript(special://home/addons/nico.video.contextactions/resources/lib/refresh_local.py)</l>
            <!-- Move to Top -->
            <t>RunScript(special://home/addons/nico.video.contextactions/resources/lib/move_to_top.py)</t>
        </keyboard>
    </Videos>
</keymap>
```

> **Note for AZERTY Users:** Kodi maps keys based on physical position. The `<q>` tag corresponds to the key physically at the 'A' position on an AZERTY layout.

### Smart Play on the remote's Play button

Add inside `<Videos>` (same file, or `remote.xml`). Which tag fires depends on how the remote reaches Kodi:

```xml
<Videos>
    <!-- CEC (TV remote over HDMI) and most remotes handled by Kodi's remote keymap -->
    <remote>
        <play>RunScript(special://home/addons/nico.video.contextactions/resources/lib/smart_play.py)</play>
    </remote>
    <!-- IR/MCE remotes on Windows usually send the keyboard media key instead -->
    <keyboard>
        <play_pause>RunScript(special://home/addons/nico.video.contextactions/resources/lib/smart_play.py)</play_pause>
    </keyboard>
</Videos>
```

To find out which one your remote sends: enable debug logging (**Settings → System → Logging**), press Play in the library, and look for the `OnKey` line in `kodi.log`. Phone remote apps (Kore, Yatse) call JSON-RPC directly and cannot be intercepted. Keymap changes need a Kodi restart.
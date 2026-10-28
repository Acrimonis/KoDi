# nICo Video Context Actions for Kodi

**Addon ID:** `nico.video.contextactions`  
**Version:** 1.0.7 
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

### Silent Watch Toggle
Intelligently switches an item between "Watched" and "Unwatched" status.
- **Movies & Episodes:** Toggles the individual item. After toggling an episode, automatically moves focus to the first unwatched episode in the season (if any).
- **TV Shows & Seasons:** Batch-updates all episodes. If any episode is unwatched, the entire set is marked watched; otherwise all are marked unwatched.
- **Preserves Last Played dates:** Uses one `SetEpisodeDetails` RPC per season (fired before SQL so Kodi detects the change and fires item-level events → badges update in both directions), then writes the remaining episodes directly via SQL batch (~10ms regardless of episode count). Original `lastPlayed` dates are silently restored via SQL after the toggle — no corruption, no sort-order side effects.
- **Season state awareness:** When toggling a single episode, the notification indicates if the season's watched state changed (e.g. all episodes just became watched/unwatched).
- **Rich notification:** Shows result as `[Show Name] • Changed to Watched: 3 seasons, 22 episodes` (singular/plural aware). Single episodes and movies are also notified.
- **Path Fallback:** Includes a Tier 2 regex parser for `videodb://` paths to ensure reliability even when standard InfoLabels fail.

### Silent Refresh (Internet)
Rescrapers the selected item's metadata from the internet (equivalent to `ignorenfo=True`).
- If the internet scraper returns no data and the item would be lost, the addon automatically falls back to a Local NFO refresh to prevent accidental deletion.
- Supported for: `movie`, `tvshow`, `season`, `episode`.

### Silent Refresh (Local)
Refreshes the selected item's metadata using local NFO files (equivalent to `ignorenfo=False`).
- **Movies & Episodes:** Refreshes the single item.
- **TV Shows & Seasons:** Recursively refreshes the container and all child episodes. Notification shows count (e.g. `1 show, 3 seasons, 62 episodes`). Any per-episode failures are reported in the notification.
- Supported for: `movie`, `tvshow`, `season`, `episode`.

### Concurrent Action Safety
All actions use a **per-show file-based mutex** (`{showid}_{pid}.lock` in Kodi's temp dir) to prevent two operations running on the same show at the same time.
- If an action is already running on a show, new actions queue automatically and show a **"queued…"** notification.
- If the lock owner process crashes, stale locks are detected and removed on the next invocation using the Win32 `OpenProcess` API.
- **Notification rules:** Free lock → start notif + end notif. Queued → queued notif + end notif only (no duplicate start notif).

---

## Supported Item Types

All five actions are visible in the context menu for:

| Type | DBType |
|------|--------|
| Movie | `movie` |
| TV Show | `tvshow` |
| Season | `season` |
| Episode | `episode` |

---

## Installation

1. Place the `nico.video.contextactions` folder into your Kodi addons directory:
   - **Windows:** `%APPDATA%\Kodi\addons\`
   - **Linux:** `~/.kodi/addons/`
   - **macOS:** `~/Library/Application Support/Kodi/addons/`

2. Restart Kodi or enable the addon via **Settings → Add-ons → My add-ons**.

3. The five actions will appear automatically in the **right-click context menu** on any supported library item.

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
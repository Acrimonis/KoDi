# nICo Video Context Actions for Kodi

**Addon ID:** `nico.video.contextactions`  
**Version:** 1.0.10
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
- **Show profile:** for episodes, seasons and shows, the show's saved position (see Persist) is moved to the target episode, so Smart Play and library navigation continue there: `in_progress` at its resume point if it has one or is unwatched, otherwise `completed`. Movies have no profile.
- **Use case:** Brings a show to the top of your "last played" sort order so it is the next one to continue.

### Watched Toggle
Intelligently switches an item between "Watched" and "Unwatched" status.
- **Movies & Episodes:** Toggles the individual item. After toggling an episode, automatically moves focus to the first unwatched episode in the season (if any).
- **TV Shows & Seasons:** Batch-updates all episodes. If any episode is unwatched, the entire set is marked watched; otherwise all are marked unwatched.
- **Preserves Last Played dates:** Uses one `SetEpisodeDetails` RPC per season (fired before SQL so Kodi detects the change and fires item-level events → badges update in both directions), then writes the remaining episodes directly via SQL batch (~10ms regardless of episode count). Original `lastPlayed` dates are silently restored via SQL after the toggle — no corruption, no sort-order side effects.
- **Marking watched clears the resume point** (as Kodi's own "mark as watched" does; this cannot be undone by marking unwatched again). Marking unwatched leaves it, and the next Smart Play or autoplay start of such an episode asks first: **Restart** (default, first entry) / **Resume from mm:ss**, same menu as the autoplay prompt. The episodes concerned are remembered in `addon_data/.../restart_marks.json`; a mark is used once (any start of the episode consumes it) and cleared when the episode is marked watched. A manual start (Enter) goes through Kodi's own resume prompt, whose default cannot be changed.
- **Show profile follows:** if the show's saved episode is among the toggled ones, marking watched sets the profile to `completed` (Smart Play then plays the next unwatched episode); marking unwatched turns a `completed` profile into `in_progress` at 0. An in-progress profile is left alone, and toggles that don't include the saved episode don't touch the profile.
- **Scope:** only the selected episodes are written, even when a queued action holds a larger snapshot of the show.
- **Season state awareness:** When toggling a single episode, the notification indicates if the season's watched state changed (e.g. all episodes just became watched/unwatched).
- **Rich notification:** Shows result as `[Show Name] • Changed to Watched: 3 seasons, 22 episodes` (singular/plural aware). Single episodes and movies are also notified.
- **Path Fallback:** Includes a Tier 2 regex parser for `videodb://` paths to ensure reliability even when standard InfoLabels fail.

### Refresh (Internet)
Rescrapers the selected item's metadata from the internet (equivalent to `ignorenfo=True`).
- Last played dates and play counts are restored after the scrape. The addon waits for Kodi's update events (idle timeout) and reports a timeout in the notification if they stop early.
- Supported for: `movie`, `tvshow`, `season`, `episode`.

### Refresh (Local)
> **Currently disabled:** the context menu entry is commented out in `addon.xml`. The script (`refresh_local.py`) is unchanged and can still be bound to a key (see Manual Keyboard Mapping).

Refreshes the selected item's metadata using local NFO files (equivalent to `ignorenfo=False`).
- **Movies & Episodes:** Refreshes the single item.
- **TV Shows & Seasons:** Recursively refreshes the container and all child episodes. Notification shows count (e.g. `1 show, 3 seasons, 62 episodes`). Any per-episode failures are reported in the notification.
- Supported for: `movie`, `tvshow`, `season`, `episode`.

### Persist (automatic show profile)
Bookmarks where you are in a show by writing a profile to `addon_data/nico.video.contextactions/{showid}.json`. There is no context menu entry: profiles are written only by the background service and by Smart Play.
- **Content:** show name/ID, readable location (`Show • Season 2 • Episode 5`), timestamp, `videodb://` paths (show/season/episode), episode title, and for episodes the resume info (position, total, percentage, strategy). Keeps the last 5 previous locations in `history`; a location is archived only when it changed. Profiles built by Smart Play carry `"source": "derived"`.
- **Triggers:** a background service (`service.py`, starts with Kodi) watches playback of **library episodes only** (movies are ignored):
  - (Profiles saved by earlier versions with the removed menu entry carry strategy `manual_save`; Smart Play and navigation still honor them.)
    - **Start:** if the show has no profile yet, one is created silently (`in_progress`, library resume point). An existing profile is not touched at start.
    - **While playing:** the position is sampled every second in memory and the profile is written silently every 30 seconds (`in_progress`), skipped while paused or if the position hasn't changed.
    - **Stop:** `in_progress` at the exact last position.
    - **End:** `completed`.
    - **Next item starts without a stop/end** (playlist advance, Smart Play over a playing episode): the previous episode is saved silently at its last position first.
    - **Kodi quits during playback:** the last position is saved silently (best-effort; Kodi does not report a stop on exit).
    - Any automatic save at ≥ 92% of the duration is recorded as `completed` (Kodi's default watched threshold), so a stop in the end credits is not resumed.
  - In automatic saves the show name comes from the library, not the focused list item.
- **Notification:** `Season 02 Episode 05 • Progress saved (37%)` on stop/end. Start and 30-second writes are silent.
- **Location:** `special://profile/addon_data/nico.video.contextactions/{showid}.json` (portable install: `<portable_data>\userdata\addon_data\nico.video.contextactions\`). The folder is created on first write.
- Read by Smart Play and by library navigation.
- **Recreated shows:** profiles are keyed by the show's database ID, and Refresh (Internet) can recreate a show under a new ID. When a show has no profile, the add-on adopts the orphaned profile of the same show name whose old ID is gone from the library (exactly one match required): the file is renamed to the new ID and the saved episodes, including `history`, are remapped by season/episode number (`info.adopted_from` records the old ID). If the saved episode no longer exists, nothing is adopted and Smart Play builds a new profile from Kodi's watch history. A profile that already exists for the new ID is never replaced.

### Smart Play
Replaces the regular **Play** on a TV show or season. Bound to the remote's Play button through a keymap (see "Smart Play on the remote's Play button" below); not a context menu entry. Reads that show's `{showid}.json`:
- `in_progress` (or a manual save) on an episode in scope → play that episode, starting 5 seconds before the saved position. If Kodi's own resume point for that episode is empty (reset, marked watched) and the saved position is past Kodi's minimum (`video.ignoresecondsatstart` in `advancedsettings.xml`, default 180s; Kodi stores no resume point before that), an `in_progress` profile is ignored and the episode starts at 0; a manual save is still honored.
- `completed` → plays the next unwatched episode: the first unwatched one after the saved episode, else the first unwatched one of the show (season 0 last; with a season active, only that season). It starts at that episode's library resume point minus 5 seconds, or at 0, without Kodi's resume prompt. Nothing unwatched → Kodi's default play.
- Anything else → Kodi's default play: no resume data, saved episode missing from the library, or (season active) saved episode in another season.
- No profile → one is created from the library first (`"source": "derived"`): the most recently played episode (resume point, or dated but unwatched → `in_progress`; watched → `completed`), or the first unwatched episode if the show was never played (season 0 last).
- Any other item (movie, episode, non-library), or a video already playing/paused → Kodi's default play, unchanged.
- "Kodi's default play" = the button's original action, `PlayPause` (what Kodi's default keymaps bind to the remote's `play` and the keyboard's `play_pause`). Another action can be passed as a script argument: `RunScript(…/smart_play.py,Play)`.
- Notification when it resumes from the profile: `Smart resume • S01E01 at 9:17` (start position, i.e. saved − 5s); suffix `(from Kodi)` when the profile was just built from Kodi's watch history (`"source": "derived"`). When it plays the next episode after a `completed` one: `Smart resume • S01E04 (next)`. Fallbacks show nothing (Kodi's default play).
- If the episode to play was marked unwatched while Kodi still held a resume point (see Watched Toggle) and would start at 30 s or more, the Kodi-style menu is shown first: **Restart** (default) / **Resume from mm:ss**; Restart starts at 0 (toast `S01E01 from the start`).
- The episode is opened on its own with an explicit resume time (Kodi ignores the resume time for playlist items, so a playlist start would begin at 0 and then jump). Once it plays, the background service builds the queue (see "Playlist queue" below). The start position is checked after playback begins; if Kodi ignored the resume time, the script seeks. Everything is logged under `[SMART_PLAY:<show>]`.

### Playlist queue
When any library episode starts (Smart Play, Enter in the library, a season/show Play...), the background service makes the video playlist after it match these rules, so Kodi's "Play next video automatically" (Settings → Player → Videos) moves on the same way whatever started it:
- **From a regular episode:** the later **unwatched** (playcount 0) regular episodes, across seasons. Specials (season 0) are never queued.
- **From a special:** the later unwatched specials, then the unwatched regular episodes from the first season that has any.
- Whatever Kodi had queued after the episode (e.g. the rest of the visible list, watched episodes included) is replaced; if the queue is already as wanted, nothing is touched. Built once at the start: it is not recomputed when an autoplay moves on, nor when watched states change later.
- **Left alone:** shuffled playlists, and playlists holding anything but episodes of this show (movies, other shows, files). A playlist of this show's episodes that you built yourself is replaced.
- Logged as `nICo Service: [QUEUE] …` (kept / removed / added counts). Needs a Kodi restart after an update (service).

### Resume prompt on autoplay
When Kodi's "Play next video automatically" moves on to an episode that was left part-way, Kodi starts it from 0. The background service catches this (an episode of the **same show** starting within 10 seconds of another one's end) and, if a saved position of at least 30 seconds exists, pauses and shows Kodi's own resume menu — **Resume from 20:00** (Kodi's translated string) / **Restart**, with a toast `Show • S01E04 • left at 20:00 (21%)` for the details. The first entry is the default, and cancelling the menu also picks it. For an episode marked unwatched (see Watched Toggle) the order is swapped: **Restart** first, so it is the default. It waits for your answer; resume seeks to the saved position, the other choice just continues from 0.
- **Saved position:** the Persist profile (current status, then `history`, newest entry for that episode) is used first — it is exact and exists even when Kodi stored no resume point (stops under `video.ignoresecondsatstart`, default 180s). Otherwise Kodi's library resume point. If Kodi's resume point was cleared (reset) and the profile position is past that minimum, nothing is offered.
- Manual starts (Enter) are not affected (Kodi's own prompt applies); Smart Play only asks for episodes marked unwatched (see above). Needs a Kodi restart after an update (service).

### Start toast
The ` • ` separators the addon puts inside any toast message are drawn white (`[COLOR white]`), matching the dot Amber draws between heading and message (Amber's `LabelTextColor`, white unless changed in the skin settings); the grey "queued/running" status toasts are left as they are.

When any video starts, the background service shows a 6 s toast (no sound): for an episode the heading is the show title and the message `S01E02 • Episode title`; for a movie the heading is the title and the message `year • h:mm:ss` (release year and runtime, each only when known; neither → no message); for any other video (non-library file) the heading is the title, or the file name when there is none. Skin Amber draws heading and message on one line joined by a hard-coded ` • `, so a toast without a message ends in a dot (skin limitation; patching the skin was rejected, it would not survive a skin update). Music is not announced. After Smart Play, the title toast always comes after its `Smart resume` toast (Kodi queues toasts): Smart Play sets the Home-window property `nico.smartplay_pending` before opening the episode and clears it once done (toast shown or given up); the service holds the title until then, for at most 15 s. Needs a Kodi restart after an update (service).

### Library navigation to the saved position
When you enter a show or a season in the video library, the cursor jumps to where you left off. Nothing starts playing; only the selection moves. Done by the background service (`nav_focus.py`, polling every 0.1s while the Videos window is open).
- **Show (season list):** selects the saved season.
- **Season (episode list):** selects the saved episode.
- **Profile `completed`:** selects the next unwatched episode (same pick as Smart Play); in a season list, that episode's season. In an "All seasons" episode list (several seasons) the whole show is searched.
- After **Watched Toggle** on a single episode, the same cursor logic moves to the first remaining unwatched episode of the season (matched by episode ID; if it is not in the visible list the cursor stays).
- No profile, or the saved item isn't in the list → nothing moves.
- It acts once when the folder is entered. Going back up a level, returning from playback, and refreshing the list don't re-trigger it, so Kodi's own cursor restore is untouched. Leaving the Videos window without playing anything (Home, Settings) and coming back counts as a fresh entry, so the cursor jumps again even in the same folder.
- Focus is set on the visible standard view container (IDs 50–58, 501, 502, 511, 551, 600); tested on skin Amber. A short flash of the first item before the jump is possible, since Kodi draws the list first.
- Logged as `[NAV:<showid>]`. Needs a Kodi restart after an update (service).

### Concurrent Action Safety
All actions use a **per-show file-based mutex** (`{showid}_{threadid}.lock` in Kodi's temp dir; each action runs in its own thread) to prevent two operations running on the same show at the same time.
- If an action is already running on a show, new actions queue automatically and show a **"queued…"** notification.
- If the lock owner thread is gone, stale locks are detected and removed on the next invocation (Win32 `OpenThread` on Windows).
- A queued action stops waiting when Kodi shuts down.
- Every action first announces itself with a `queued` lock file and then checks for competitors (order = timestamp, then thread id), so two actions started together cannot both run. Movies use the key `m<id>`, so a movie and a show with the same ID don't block each other.
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
  - `deploy-qpc.bat` → `P:\.kodi_d\addons\nico.video.contextactions`; also builds `nico.video.contextactions-<version>.zip` (version read from `addon.xml`) in the repo root and copies it to `P:\.kodi_d\X__WorkinG__X`
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

Add inside `<Videos>` (same file, or `remote.xml`). Which tag fires depends on how the remote reaches Kodi (`<remote>`, `<keyboard>` or `<appcommand>`):

```xml
<Videos>
    <!-- CEC (TV remote over HDMI) and most remotes handled by Kodi's remote keymap -->
    <remote>
        <play>RunScript(special://home/addons/nico.video.contextactions/resources/lib/smart_play.py)</play>
    </remote>
    <!-- Keyboards with media keys -->
    <keyboard>
        <play_pause>RunScript(special://home/addons/nico.video.contextactions/resources/lib/smart_play.py)</play_pause>
    </keyboard>
    <!-- Windows media remotes / MCE receivers: the button arrives as an app command (Kodi's appcommand.xml maps it to PlayPause globally) -->
    <appcommand>
        <play_pause>RunScript(special://home/addons/nico.video.contextactions/resources/lib/smart_play.py)</play_pause>
        <play>RunScript(special://home/addons/nico.video.contextactions/resources/lib/smart_play.py,Play)</play>
    </appcommand>
</Videos>
```

A Windows media remote's Play/Pause button is an **app command**, not a `<keyboard>` or `<remote>` key. Without the `<appcommand>` block the button never reaches Smart Play: Kodi's global `PlayPause` runs instead and shows its own "Continue watching / Play from beginning" prompt on a show.

To find out which one your remote sends: enable debug logging (**Settings → System → Logging**), press Play in the library, and look for the `OnKey` line in `kodi.log`. Phone remote apps (Kore, Yatse) call JSON-RPC directly and cannot be intercepted. Keymap changes need a Kodi restart.
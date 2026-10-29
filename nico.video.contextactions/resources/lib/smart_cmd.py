import os
import json
import time
import xml.etree.ElementTree as ET
import xbmc
import xbmcgui
import xbmcvfs
import common_locks
import common_actions

_CFG_DIR = 'special://profile/addon_data/nico.video.contextactions/'
_DEFAULT_MIN_RESUME = 180  # Kodi's video.ignoresecondsatstart default


def profile_path(show_id):
    return os.path.join(xbmcvfs.translatePath(_CFG_DIR), f"{show_id}.json")


def min_resume_seconds():
    """Kodi stores no resume point before this many seconds (advancedsettings.xml, default 180)."""
    try:
        root = ET.parse(xbmcvfs.translatePath('special://profile/advancedsettings.xml')).getroot()
        return int(root.findtext('video/ignoresecondsatstart'))
    except Exception:
        return _DEFAULT_MIN_RESUME


def _read_profile(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def load_profile(show_id):
    """Return the saved profile dict for show_id, or None if missing/unreadable.

    A show recreated by Refresh (Internet) has a new ID: its old profile is adopted first.
    """
    path = profile_path(show_id)
    if not os.path.exists(path):
        adopt_orphan_profile(show_id)
    return _read_profile(path)


def _remap_status(status, show_id, episodes):
    """Re-point a status block (paths, resume.episode_id) at the recreated show.

    episodes: {(season, episode): episode details} of the new show. Returns None if the saved
    episode no longer exists. Season/episode paths are rebuilt only for statuses that carry resume info.
    """
    status = dict(status)
    paths = {"show": f"videodb://tvshows/titles/{show_id}/"}
    resume = status.get('resume')
    if resume:
        ep = episodes.get((resume.get('season_num'), resume.get('episode_num')))
        if not ep:
            return None
        status['resume'] = dict(resume, episode_id=ep['episodeid'])
        season_id = ep.get('seasonid')
        if season_id:
            paths["season"] = f"videodb://tvshows/titles/{show_id}/{season_id}/"
            paths["episode"] = f"videodb://tvshows/titles/{show_id}/{season_id}/{ep['episodeid']}/"
    status['paths'] = paths
    return status


def adopt_orphan_profile(show_id, show_title=None):
    """Take over the profile of a show that Refresh (Internet) recreated under a new ID.

    Acts only when show_id has no profile and exactly one other profile has the same show name and
    an ID that is gone from the library. Saved episodes (current and history) are remapped by
    season/episode number. Returns True if a profile was adopted.
    """
    new_path = profile_path(show_id)
    if os.path.exists(new_path):
        return False
    show_title = show_title or common_actions._fetch_show_title(show_id, fallback="")
    if not show_title:
        return False
    cfg_dir = xbmcvfs.translatePath(_CFG_DIR)
    try:
        names = os.listdir(cfg_dir)
    except OSError:
        return False

    candidates = []
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext != '.json' or not stem.isdigit() or int(stem) == int(show_id):
            continue
        old = _read_profile(os.path.join(cfg_dir, name))
        if not old or str((old.get('info') or {}).get('show_name', '')).casefold() != show_title.casefold():
            continue
        res = common_actions.execute_rpc("VideoLibrary.GetTVShowDetails", {"tvshowid": int(stem)})
        if res.get('result', {}).get('tvshowdetails'):
            continue  # that show still exists: a different show with the same name
        candidates.append((int(stem), old))

    tag = f"PERSIST:{show_title}"
    if len(candidates) != 1:
        if candidates:
            xbmc.log(f"nICo Context: [{tag}] Profile adoption skipped — {len(candidates)} orphaned profiles match "
                     f"{[c[0] for c in candidates]}", xbmc.LOGWARNING)
        return False
    old_id, old = candidates[0]

    res = common_actions.execute_rpc("VideoLibrary.GetEpisodes", {"tvshowid": int(show_id), "properties": ["season", "episode", "seasonid"]})
    episodes = {(e.get('season'), e.get('episode')): e for e in res.get('result', {}).get('episodes', [])}
    status = _remap_status(old.get('status') or {}, show_id, episodes)
    if status is None:
        xbmc.log(f"nICo Context: [{tag}] Profile adoption skipped — saved episode of profile {old_id} not in show {show_id}", xbmc.LOGINFO)
        return False
    history = [h for h in (_remap_status(h, show_id, episodes) for h in old.get('history', [])) if h is not None]

    profile = {
        "info": {"show_name": show_title, "show_id": int(show_id), "adopted_from": old_id},
        "status": status,
        "priority_stack": old.get('priority_stack', ["smart_play", "resume_native", "play_beginning", "view_history"]),
        "history": history
    }
    try:
        tmp = new_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
        os.replace(tmp, new_path)
        os.remove(profile_path(old_id))
    except Exception as ex:
        xbmc.log(f"nICo Context: [{tag}] Profile adoption failed: {ex}", xbmc.LOGERROR)
        return False
    xbmc.log(f"nICo Context: [{tag}] Adopted profile {old_id} -> {show_id} ({len(history)} history entries kept)", xbmc.LOGINFO)
    return True


def persist_show():
    """Entry point for context menu actions."""
    dbid, dbtype = common_actions.get_target_info()
    if not dbid or dbid == "-1":
        return
    persist_show_by_id(dbid, dbtype)


def persist_show_by_id(dbid, dbtype, silent=False, automated=False, create_only=False,
                       position=None, duration=None, strategy=None, source=None, durable=True, quiet=False):
    """Refactored logic to support background events (no UI context) or direct ID calls.

    automated:   called by the service / Smart Play; show title comes from the library, not ListItem.
    create_only: write only if the show has no profile yet (playback start).
    position, duration: playback position/total from the player; override the library resume point.
    strategy:    force the resume strategy instead of deriving it.
    source:      optional origin marker stored in status (e.g. "derived").
    durable:     fsync the write; False for frequent periodic ticks.
    quiet:       log the routine steps at DEBUG instead of INFO (periodic ticks).
    """
    info = xbmc.LOGDEBUG if quiet else xbmc.LOGINFO
    # Resolve hierarchy for path abstraction
    show_id = None
    season_id = None
    episode_id = None
    ep_title = None
    s_num = None
    e_num = None
    details = {}

    xbmc.log(f"nICo Context: [PERSIST] Entry -> ID:{dbid} Type:{dbtype} (Silent:{silent})", info)
    xbmc.log(f"nICo Context: [PERSIST] Starting resolution for {dbtype} ID {dbid}", xbmc.LOGDEBUG)

    try:
        if dbtype == 'tvshow':
            show_id = int(dbid)
        elif dbtype == 'season':
            season_id = int(dbid)
            res = common_actions.execute_rpc("VideoLibrary.GetSeasonDetails", {"seasonid": season_id, "properties": ["tvshowid", "season"]})
            s_details = res.get('result', {}).get('seasondetails', {})
            show_id = s_details.get('tvshowid')
            s_num = s_details.get('season')
        elif dbtype == 'episode':
            episode_id = int(dbid)
            res = common_actions.execute_rpc("VideoLibrary.GetEpisodeDetails", {"episodeid": episode_id, "properties": ["tvshowid", "seasonid", "season", "episode", "title", "resume", "runtime"]})
            details = res.get('result', {}).get('episodedetails', {})
            show_id = details.get('tvshowid')
            season_id = details.get('seasonid')
            s_num, e_num = details.get('season'), details.get('episode')
            ep_title = details.get('title')
    except Exception as e:
        xbmc.log(f"nICo Context: [PERSIST] Failed to resolve hierarchy for {dbtype} {dbid}: {e}", xbmc.LOGWARNING)

    xbmc.log(f"nICo Context: [PERSIST] Resolved hierarchy: show={show_id}, season={season_id}, episode={episode_id}", xbmc.LOGDEBUG)

    if not show_id:
        xbmc.log(f"nICo Context: [PERSIST] Aborted — no show ID for {dbtype} {dbid}", xbmc.LOGWARNING)
        return

    adopt_orphan_profile(show_id)  # no-op unless the show was recreated under a new ID

    if create_only and os.path.exists(profile_path(show_id)):
        xbmc.log(f"nICo Context: [PERSIST] Profile exists for show {show_id}, create_only — nothing written", xbmc.LOGDEBUG)
        return

    # Resolve show title robustly. Background events: the focused ListItem is unrelated to the
    # item that played, so always ask the library.
    if automated:
        show_title = common_actions._fetch_show_title(show_id, fallback=f"ID:{show_id}")
    else:
        show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
        if not show_title or show_title == 'Label':
            show_title = common_actions._fetch_show_title(show_id, fallback=f"ID:{show_id}")
    
    if not show_title:
        show_title = f"{dbtype}:{dbid}"

    tag = f"PERSIST:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] Processing state | dbid='{dbid}' dbtype='{dbtype}'", info)

    # Construct human-readable location
    location = show_title
    if s_num is not None:
        if e_num is not None:
            location = f"{show_title} {common_locks.DOT} Season {s_num} {common_locks.DOT} Episode {e_num}"
        else:
            location = f"{show_title} {common_locks.DOT} Season {s_num}"

    xbmc.log(f"nICo Context: [PERSIST] Final location string: {location}", xbmc.LOGDEBUG)

    # Construct status block: paths (location)
    # raw_path = xbmc.getInfoLabel('ListItem.FolderPath') or xbmc.getInfoLabel('Container.FolderPath')
    paths = {
        "show": f"videodb://tvshows/titles/{show_id}/" if show_id else None,
        "season": f"videodb://tvshows/titles/{show_id}/{season_id}/" if show_id and season_id else None,
        "episode": f"videodb://tvshows/titles/{show_id}/{season_id}/{episode_id}/" if show_id and season_id and episode_id else None,
        "movie": f"videodb://movies/titles/{dbid}/" if dbtype == 'movie' else None,
        # "current_raw": raw_path if raw_path else None
    }
    # Filter out N/A paths
    paths = {k: v for k, v in paths.items() if v}

    status = {
        "location": location,
        "ts": int(time.time()),
        "time": time.strftime('[%Y %b %d - %H:%M:%S]')
    }
    if ep_title:
        status["episode_title"] = ep_title
    if source:
        status["source"] = source

    if paths:
        status["paths"] = paths

    notification_msg = "Location bookmarked." if not automated else "Progress updated."

    # Resume (target) - Only persist if currently on an episode
    if dbtype == 'episode' and episode_id:
        resume_info = details.get('resume', {})
        runtime = details.get('runtime', 0)
        pos = position if position is not None else resume_info.get('position', 0)
        total = duration or resume_info.get('total') or runtime

        # Determine Strategy
        if not strategy:
            strategy = "manual_save"
            if automated: # Triggered by Service
                strategy = "in_progress" if pos > 0 else "completed"

        # If completed, reflect the full progress instead of 0
        if strategy == "completed" and total > 0:
            pos = total

        percentage = round((pos / total * 100), 2) if total > 0 else 0

        status["resume"] = {
            "episode_id": episode_id,
            "season_num": s_num,
            "episode_num": e_num,
            "position": round(pos, 2),
            "total": round(total, 2),
            "percentage": percentage,
            "strategy": strategy
        }

        notification_msg = f" Season {s_num:02} Episode {e_num:02} {common_locks.DOT_SPC} Progress saved ({int(percentage)}%)"
        xbmc.log(f"nICo Context: [{tag}] Playback {strategy} -> S{s_num:02}E{e_num:02} stopped at {round(pos, 2)}s / {round(total, 2)}s ({percentage}%)", info)

    cfg_dir = xbmcvfs.translatePath(_CFG_DIR)
    try:
        if not xbmcvfs.exists(cfg_dir):
            xbmcvfs.mkdirs(cfg_dir)
    except Exception:
        # Best-effort fallback if xbmcvfs mkdirs isn't available
        try:
            os.makedirs(cfg_dir, exist_ok=True)
        except Exception:
            pass

    path = profile_path(show_id)

    # Load existing data to update history and preserve stack
    history = []
    priority_stack = ["smart_play", "resume_native", "play_beginning", "view_history"]
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                history = old_data.get('history', [])
                old_status = old_data.get('status')
                
                # Prepend to history only if the target object has changed and status is a dict.
                if isinstance(old_status, dict):
                    # We compare canonical paths (built from IDs) and ignore the raw URL params.
                    old_paths = old_status.get('paths') or {}
                    new_paths = status.get('paths') or {}
                    old_nav = {k: v for k, v in old_paths.items() if k != 'current_raw'}
                    new_nav = {k: v for k, v in new_paths.items() if k != 'current_raw'}

                    if old_nav != new_nav:
                        xbmc.log(f"nICo Context: [{tag}] Status changed, archiving previous to history", xbmc.LOGDEBUG)
                        history.insert(0, old_status)
                    else:
                        xbmc.log(f"nICo Context: [{tag}] Status unchanged (ignoring raw params), skipping history archive", xbmc.LOGDEBUG)
                
                # Enforce max 5 entries
                history = history[:5]
                priority_stack = old_data.get('priority_stack', priority_stack)
        except Exception:
            pass

    profile = {
        "info": {
            "show_name": show_title,
            "show_id": show_id or dbid
        },
        "status": status,
        "priority_stack": priority_stack,
        "history": history
    }

    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
            f.flush()
            if durable:
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        os.replace(tmp, path)
        xbmc.log(f"nICo Context: [{tag}] Saved profile -> {path}", info)
        if not silent:
            common_locks.notification(show_title, notification_msg, xbmcgui.NOTIFICATION_INFO, 2500)
    except Exception as ex:
        xbmc.log(f"nICo Context: [{tag}] Failed to save profile: {ex}", xbmc.LOGERROR)
        common_locks.notification(show_title, "Failed to save show profile.", xbmcgui.NOTIFICATION_ERROR, 3500)


if __name__ == '__main__':
    try:
        xbmc.log("nICo Context: [DEBUG] Entry point smart_cmd.py started", xbmc.LOGINFO)
        common_locks._log_thread_info("PERSIST")
        common_locks.cleanup_stale_locks()
        persist_show()
    except Exception as e:
        xbmc.log(f"nICo Context: [FATAL] smart_cmd main crashed: {e}", xbmc.LOGERROR)

import os
import json
import time
import xbmc
import xbmcgui
import xbmcvfs
import common_locks
import common_actions




def persist_show():
    """Entry point for context menu actions."""
    dbid, dbtype = common_actions.get_target_info()
    if not dbid or dbid == "-1":
        return
    persist_show_by_id(dbid, dbtype)


def persist_show_by_id(dbid, dbtype, silent=False, automated=False):
    """Refactored logic to support background events (no UI context) or direct ID calls."""
    # Resolve hierarchy for path abstraction
    show_id = None
    season_id = None
    episode_id = None
    ep_title = None
    s_num = None
    e_num = None
    details = {}

    xbmc.log(f"nICo Context: [PERSIST] Entry -> ID:{dbid} Type:{dbtype} (Silent:{silent})", xbmc.LOGINFO)
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

    # Resolve show title robustly (UI labels might be empty in background events)
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    if (not show_title or show_title == 'Label') and show_id:
        show_title = common_actions._fetch_show_title(show_id, fallback=f"ID:{show_id}")
    
    if not show_title:
        show_title = f"{dbtype}:{dbid}"

    tag = f"PERSIST:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] Processing state | dbid='{dbid}' dbtype='{dbtype}'", xbmc.LOGINFO)

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

    if paths:
        status["paths"] = paths

    notification_msg = "Location bookmarked." if not automated else "Progress updated."

    # Resume (target) - Only persist if currently on an episode
    if dbtype == 'episode' and episode_id:
        resume_info = details.get('resume', {})
        runtime = details.get('runtime', 0)
        pos = resume_info.get('position', 0)
        total = resume_info.get('total') or runtime
        
        # Determine Strategy
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
        xbmc.log(f"nICo Context: [{tag}] Playback {strategy} -> S{s_num:02}E{e_num:02} stopped at {round(pos, 2)}s / {round(total, 2)}s ({percentage}%)", xbmc.LOGINFO)

    cfg_dir = xbmcvfs.translatePath('special://profile/addon_data/nico.video.contextactions/')
    try:
        if not xbmcvfs.exists(cfg_dir):
            xbmcvfs.mkdirs(cfg_dir)
    except Exception:
        # Best-effort fallback if xbmcvfs mkdirs isn't available
        try:
            os.makedirs(cfg_dir, exist_ok=True)
        except Exception:
            pass

    path = os.path.join(cfg_dir, f"{show_id or dbid}.json")

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
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        xbmc.log(f"nICo Context: [{tag}] Saved profile -> {path}", xbmc.LOGINFO)
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

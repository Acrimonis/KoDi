import xbmc, xbmcgui, time
import common_locks
import common_actions

_COUNTDOWN_SECONDS = 5


def _countdown(show_title):
    """Grey, non-blocking 5s..1s toasts. Returns False if Kodi is shutting down."""
    monitor = xbmc.Monitor()
    for remaining in range(_COUNTDOWN_SECONDS, 0, -1):
        common_locks.notificationStatus(show_title, f"Moving to top in {remaining}s…", "", 1000)
        if monitor.waitForAbort(1):
            return False
    return True


def _pick_target(dbid, dbtype):
    """Episode -> itself. Season/tvshow -> first unwatched episode, else first episode.
    Order: season then episode, specials (season 0) last."""
    if dbtype == 'episode':
        res = common_actions.execute_rpc("VideoLibrary.GetEpisodeDetails", {
            "episodeid": int(dbid), "properties": ["season", "episode"]})
        return res.get('result', {}).get('episodedetails')
    episodes = common_actions.get_episodes(dbid, dbtype, extra_props=["playcount", "episode"])
    if not episodes:
        return None
    episodes.sort(key=lambda e: (e.get('season', 0) == 0, e.get('season', 0), e.get('episode', 0)))
    return next((e for e in episodes if not e.get('playcount')), episodes[0])


def move_to_top():
    dbid, dbtype = common_actions.get_target_info()
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    tag = f"MOVE_TOP:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] RAW dbid='{dbid}' dbtype='{dbtype}'", xbmc.LOGINFO)

    if not dbid or dbid == "-1" or dbtype not in ('movie', 'tvshow', 'season', 'episode'):
        xbmc.log(f"nICo Context: [{tag}] Aborted — invalid dbid/dbtype", xbmc.LOGINFO)
        return

    if not _countdown(show_title):
        xbmc.log(f"nICo Context: [{tag}] Aborted — Kodi shutting down", xbmc.LOGINFO)
        return

    root_id = common_actions._resolve_root_id(dbid, dbtype)
    lock_path, was_queued = common_locks.acquire(root_id, tag=tag, show_name=show_title,
        on_queue=lambda: common_locks.notification(show_title, "Move to top queued…", xbmcgui.NOTIFICATION_INFO, 3000))
    xbmc.log(f"nICo Context: [{tag}] Starting for {dbtype} (ID: {dbid}) root_id={root_id}", xbmc.LOGINFO)
    try:
        now_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        label = None
        if dbtype == 'movie':
            res = common_actions.execute_rpc("VideoLibrary.SetMovieDetails",
                                             {"movieid": int(dbid), "lastplayed": now_str})
        else:
            target = _pick_target(dbid, dbtype)
            if not target:
                xbmc.log(f"nICo Context: [{tag}] FAILED — no episode resolved", xbmc.LOGERROR)
                common_locks.notification(show_title, "No episodes — nothing to do", xbmcgui.NOTIFICATION_INFO, 2500)
                return
            label = f"S{target.get('season', 0):02d}E{target.get('episode', 0):02d}"
            res = common_actions.execute_rpc("VideoLibrary.SetEpisodeDetails",
                                             {"episodeid": target['episodeid'], "lastplayed": now_str})

        if res.get('result') != 'OK':
            xbmc.log(f"nICo Context: [{tag}] FAILED — RPC response: {res}", xbmc.LOGERROR)
            common_locks.notification(show_title, "Move to top failed", xbmcgui.NOTIFICATION_ERROR, 2500)
            return

        xbmc.log(f"nICo Context: [{tag}] Complete | lastPlayed={now_str} target={label or dbtype}", xbmc.LOGINFO)
        xbmc.executebuiltin('Container.Refresh')
        body = "Moved to top" + (f"{common_locks.DOT_SPC}{label}" if label else "")
        common_locks.notification(show_title, body, xbmcgui.NOTIFICATION_INFO, 2500)
    finally:
        common_locks.release(lock_path, root_id, tag=tag, show_name=show_title)


if __name__ == '__main__':
    common_locks._log_thread_info("MOVE_TOP")
    common_locks.cleanup_stale_locks()
    xbmc.log("nICo Context: Triggering Move to Top", xbmc.LOGINFO)
    move_to_top()

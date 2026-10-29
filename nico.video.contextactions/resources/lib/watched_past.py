import os, xbmc, xbmcvfs, xbmcgui, json, time
import common_locks
import common_actions
import common_db

_PREFS_PATH = xbmcvfs.translatePath('special://profile/addon_data/nico.video.contextactions/prefs.json')
_WATCH_PAST_NEVER = -1
_WATCH_PAST_OPTIONS = [
    ("Yesterday",  1),
    ("3 days",     3),
    ("1 week",     7),
    ("10 days",    10),
    ("1 month",    30),
    ("6 months",   180),
    ("Never (clear dates)", _WATCH_PAST_NEVER),
]
_WATCH_PAST_DEFAULT_DAYS = 10


def _load_watch_past_days():
    try:
        with open(_PREFS_PATH, 'r') as f:
            return json.load(f).get('watch_past_days', _WATCH_PAST_DEFAULT_DAYS)
    except Exception:
        return _WATCH_PAST_DEFAULT_DAYS


def _save_watch_past_days(days):
    try:
        prefs_dir = os.path.dirname(_PREFS_PATH)
        if not os.path.isdir(prefs_dir):
            xbmcvfs.mkdirs(prefs_dir)
        existing = {}
        try:
            with open(_PREFS_PATH, 'r') as f:
                existing = json.load(f)
        except Exception:
            pass
        existing['watch_past_days'] = days
        with open(_PREFS_PATH, 'w') as f:
            json.dump(existing, f)
    except Exception as e:
        xbmc.log(f"nICo Context: failed to save watch_past_days: {e}", xbmc.LOGWARNING)


def _select_watch_past_delta(show_title=""):
    """Show a list dialog to pick the delta. Returns selected days int, or None if cancelled."""
    saved = _load_watch_past_days()
    option_labels = [label for label, _ in _WATCH_PAST_OPTIONS]
    option_days  = [days  for _, days  in _WATCH_PAST_OPTIONS]
    preselect = option_days.index(saved) if saved in option_days else 0
    title = f"{show_title} {common_locks.DOT} Shift watch date to" if show_title else "Shift watch date to"
    idx = xbmcgui.Dialog().select(title, option_labels, preselect=preselect)
    if idx < 0:
        return None
    chosen = option_days[idx]
    _save_watch_past_days(chosen)
    return chosen


def shift_watched_to_past():
    """For all episodes in scope, clamp lastPlayed to (now - delta_back_in_days).
    Episodes already older than the cutoff, or never watched, are untouched."""
    dbid, dbtype = common_actions.get_target_info()
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    tag = f"WATCH_PAST:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] RAW dbid='{dbid}' dbtype='{dbtype}'", xbmc.LOGINFO)

    if not dbid or dbid == "-1":
        xbmc.log(f"nICo Context: [{tag}] Aborted — invalid dbid", xbmc.LOGINFO)
        return

    delta_back_in_days = _select_watch_past_delta(show_title)
    if delta_back_in_days is None:
        xbmc.log(f"nICo Context: [{tag}] Aborted — user cancelled delta selection", xbmc.LOGINFO)
        return

    root_id = common_actions._resolve_root_id(dbid, dbtype)
    lock_path, was_queued = common_locks.acquire(root_id, tag=tag, show_name=show_title,
        on_queue=lambda: common_locks.notification(show_title, "Watch-in-past queued\u2026", xbmcgui.NOTIFICATION_INFO, 3000))
    xbmc.log(f"nICo Context: [{tag}] Starting for {dbtype} (ID: {dbid}) root_id={root_id}", xbmc.LOGINFO)
    try:
        if dbtype in ['tvshow', 'season']:
            episodes = common_actions.get_episodes(dbid, dbtype, extra_props=["playcount"])
        elif dbtype == 'episode':
            ep_data = common_actions.execute_rpc("VideoLibrary.GetEpisodeDetails", {
                "episodeid": int(dbid), "properties": ["season", "playcount"]
            }).get('result', {}).get('episodedetails', {})
            episodes = [{'episodeid': int(dbid), 'season': ep_data.get('season', 0),
                         'playcount': ep_data.get('playcount', 0)}]
        else:
            xbmc.log(f"nICo Context: [{tag}] Aborted — unhandled dbtype '{dbtype}'", xbmc.LOGWARNING)
            return

        if not episodes:
            xbmc.log(f"nICo Context: [{tag}] FAILED — no episodes resolved", xbmc.LOGERROR)
            return

        if not was_queued:
            common_locks.notification(show_title, "Shifting watch date...", xbmcgui.NOTIFICATION_INFO, 3000)

        saved_lastplayed = common_actions._get_canonical_snapshot([ep['episodeid'] for ep in episodes], root_id, tag=tag)

        dated = [lp for lp in saved_lastplayed.values() if lp and str(lp) not in ('None', '')]
        if not dated:
            xbmc.log(f"nICo Context: [{tag}] Nothing to do — no watched episodes", xbmc.LOGINFO)
            common_locks.notification(show_title, "No watched episodes — nothing to do", xbmcgui.NOTIFICATION_INFO, 2500)
            return

        if delta_back_in_days == _WATCH_PAST_NEVER:
            target_str = None
            affected = {fid: lp for fid, lp in saved_lastplayed.items()
                        if lp and str(lp) not in ('None', '')}
            xbmc.log(f"nICo Context: [{tag}] NEVER — clearing lastPlayed for {len(affected)} episodes", xbmc.LOGINFO)
        else:
            target_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - delta_back_in_days * 86400))
            xbmc.log(f"nICo Context: [{tag}] target={target_str} (delta={delta_back_in_days}d)", xbmc.LOGINFO)
            affected = {fid: lp for fid, lp in saved_lastplayed.items()
                        if lp and str(lp) not in ('None', '') and str(lp) > target_str}
            if not affected:
                xbmc.log(f"nICo Context: [{tag}] Nothing to shift — all lastPlayed ≤ {target_str}", xbmc.LOGINFO)
                common_locks.notification(show_title, "Already in past, nothing to shift", xbmcgui.NOTIFICATION_INFO, 2500)
                return

        xbmc.log(f"nICo Context: [{tag}] {len(affected)}/{len(saved_lastplayed)} episodes to update \u2192 {target_str}", xbmc.LOGINFO)

        # Build episodeid → idFile map for nudge selection
        ep_to_idfile = common_actions._episodes_to_idfile(episodes, tag=tag)

        # Pick 1 nudge ep per affected season
        seen_seasons = set()
        nudge_eids = []
        nudge_idfiles = set()
        for ep in episodes:
            eid = ep['episodeid']
            fid = ep_to_idfile.get(eid)
            if fid not in affected:
                continue
            s = ep.get('season', 0)
            if s not in seen_seasons:
                seen_seasons.add(s)
                nudge_eids.append(eid)
                nudge_idfiles.add(fid)

        sql_idfiles = [fid for fid in affected if fid not in nudge_idfiles]

        t0 = common_actions._ms()
        # Step 1: RPC nudge per season — fires OnUpdate for UI refresh
        # For Never: pass lastplayed="" so Kodi clears it. For normal: pass target_str.
        nudge_lp = target_str if target_str is not None else ""
        for eid in nudge_eids:
            common_actions.execute_rpc("VideoLibrary.SetEpisodeDetails", {"episodeid": eid, "lastplayed": nudge_lp})

        # Step 2: SQL batch for remaining — None maps to NULL for the Never case
        if sql_idfiles:
            try:
                with common_db.kodi_db_context() as conn:
                    for fid in sql_idfiles:
                        conn.execute("UPDATE files SET lastPlayed = ? WHERE idFile = ?", [target_str, fid])
            except Exception as e:
                xbmc.log(f"nICo Context: [{tag}] SQL EXCEPTION: {e}", xbmc.LOGERROR)

        # Intentional write: make it the snapshot truth so a restorer queued behind us keeps it
        common_locks.update_snapshot_entries(root_id, {fid: target_str for fid in affected}, tag=tag)

        xbmc.log(
            f"nICo Context: [{tag}] shift: {len(nudge_eids)} RPC + {len(sql_idfiles)} SQL "
            f"in {common_actions._ms()-t0}ms | target={target_str}",
            xbmc.LOGINFO
        )
        xbmc.executebuiltin('Container.Refresh')
        if target_str is None:
            body = f"Watch date cleared {common_locks.DOT} {common_actions._plural(len(affected), 'episode')}."
        else:
            target_t = time.strptime(target_str, '%Y-%m-%d %H:%M:%S')
            readable_date = str(target_t.tm_mday) + time.strftime(' %b %y', target_t)
            body = f"Watch date to {readable_date} {common_locks.DOT_SPC} {common_actions._plural(len(affected), 'episode')}."
        xbmc.log(f"nICo Context: [{tag}] Complete | total={common_actions._ms()-t0}ms", xbmc.LOGINFO)
        common_locks.notification(show_title, body, xbmcgui.NOTIFICATION_INFO, 2500)
    finally:
        common_locks.release(lock_path, root_id, tag=tag, show_name=show_title)


if __name__ == '__main__':
    common_locks._log_thread_info("WATCH_PAST")
    common_locks.cleanup_stale_locks()
    xbmc.log("nICo Context: Triggering Watch in Past", xbmc.LOGINFO)
    shift_watched_to_past()

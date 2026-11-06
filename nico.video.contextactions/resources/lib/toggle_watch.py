import xbmc, xbmcgui
import common_locks
import common_actions
import common_db
import nav_focus
import smart_cmd


def _nudge_and_sql_toggle(episodes, target_playcount, tag=""):
    """Toggle watched state: 1 SetEpisodeDetails per season (fires UI event),
    SQL batch for remaining episodes (fast, no UI events), then SQL restore lastPlayed.

    - Nudge ep (1 per season): RPC BEFORE SQL — DB still has old value → Kodi detects
      the change → fires item-level OnUpdate → season/show badges update correctly.
    - Remaining episodes: SQL batch directly to files.playCount (fast, ~10ms).
    - UNWATCHED stores NULL (not 0) in files.playCount so COUNT(files.playCount) in
      season_view remains correct.
    - lastPlayed is NOT passed to SetEpisodeDetails; _restore_lastplayed handles it via SQL.
    """
    t = common_actions._ms()

    ep_to_idfile = common_actions._episodes_to_idfile(episodes, tag=tag)
    if not ep_to_idfile:
        raise RuntimeError("could not resolve idFiles for the selected episodes")

    # Pick 1 nudge episode per season (first encountered)
    seen_seasons = set()
    nudge_eps = []
    for ep in episodes:
        s = ep.get('season', 0)
        if s not in seen_seasons:
            seen_seasons.add(s)
            nudge_eps.append(ep)
    nudge_idfiles = {ep_to_idfile[eid] for ep in nudge_eps if (eid := ep['episodeid']) in ep_to_idfile}

    # Step 1: RPC nudge BEFORE SQL — DB still has old playcount → change detected → event fires
    rpc_count = 0
    for ep in nudge_eps:
        common_actions.execute_rpc("VideoLibrary.SetEpisodeDetails",
                    {"episodeid": ep['episodeid'], "playcount": target_playcount})
        rpc_count += 1

    # Step 2: SQL batch for remaining episodes — UNWATCHED must be NULL (not 0) so
    # COUNT(files.playCount) in season_view correctly excludes them from watched counts.
    sql_pc = target_playcount if target_playcount > 0 else None
    # Scope = the idFiles of `episodes` only (the shared snapshot may hold other episodes of the show)
    sql_idfiles = [f for f in set(ep_to_idfile.values()) if f not in nudge_idfiles]
    # Marked watched = done: drop the resume bookmark (type 1) like Kodi's own "mark as watched" does
    clear_idfiles = list(set(ep_to_idfile.values())) if target_playcount > 0 else []
    sql_count = 0
    if sql_idfiles or clear_idfiles:
        try:
            with common_db.kodi_db_context() as conn:
                for file_id in sql_idfiles:
                    conn.execute("UPDATE files SET playCount = ? WHERE idFile = ?",
                                 [sql_pc, file_id])
                    sql_count += 1
                for file_id in clear_idfiles:
                    conn.execute("DELETE FROM bookmark WHERE idFile = ? AND type = 1", [file_id])
        except Exception as e:
            xbmc.log(f"nICo Context: [{tag}] SQL toggle EXCEPTION: {e}", xbmc.LOGERROR)

    xbmc.log(
        f"nICo Context: [{tag}] nudge+sql: {rpc_count} RPC ({len(nudge_eps)} season(s)) "
        f"+ {sql_count} SQL in {common_actions._ms()-t}ms | playcount={target_playcount}",
        xbmc.LOGINFO
    )


def _follow_profile(show_id, episode_ids, watched, tag):
    """Let the show profile (Smart Play / navigation) follow the new watched state. Never fails the toggle."""
    if not show_id:
        return
    try:
        smart_cmd.follow_watched_state(show_id, episode_ids, watched, tag=tag)
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] Profile update failed: {e}", xbmc.LOGWARNING)


def _update_restart_marks(episode_ids, resume_ids, watched, tag):
    """Marked unwatched while Kodi still holds a resume point -> remember it, so the next start asks
    (default Restart). Marked watched -> forget. Never fails the toggle."""
    try:
        if watched:
            smart_cmd.clear_restart(episode_ids)
        elif resume_ids:
            smart_cmd.mark_restart(resume_ids)
            xbmc.log(f"nICo Context: [{tag}] {len(resume_ids)} episode(s) marked unwatched with a resume point — next start asks", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] Restart marks update failed: {e}", xbmc.LOGWARNING)


def toggle_watch_state():
    dbid, dbtype = common_actions.get_target_info()
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    tag = f"TOGGLE:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] RAW dbid='{dbid}' dbtype='{dbtype}'", xbmc.LOGINFO)

    if not dbid or dbid == "-1":
        xbmc.log(f"nICo Context: [{tag}] Aborted — invalid dbid", xbmc.LOGINFO)
        return

    root_id = common_actions._resolve_root_id(dbid, dbtype)
    lock_path, was_queued = common_locks.acquire(root_id, tag=tag, show_name=show_title,
        on_queue=lambda: common_locks.notification(show_title, "Toggle queued\u2026", xbmcgui.NOTIFICATION_INFO, 3000))
    xbmc.log(f"nICo Context: [{tag}] Starting for {dbtype} (ID: {dbid}) root_id={root_id}", xbmc.LOGINFO)
    try:
        if dbtype in ['tvshow', 'season']:
            episodes = common_actions.get_episodes(dbid, dbtype, extra_props=["playcount", "lastplayed", "resume"])
            if not episodes:
                xbmc.log(f"nICo Context: [{tag}] FAILED — no episodes resolved for {dbtype} {dbid}", xbmc.LOGERROR)
                return

            # --- EVALUATE ---
            target_playcount = 1 if any(ep.get('playcount', 0) == 0 for ep in episodes) else 0
            state_label = "Watched" if target_playcount else "Unwatched"
            if not was_queued:
                common_locks.notification(show_title, f"Marking {state_label}\u2026", xbmcgui.NOTIFICATION_INFO, 3000)
            # Snapshot by idFile (stable across RefreshEpisode). Shared snapshot ensures queued
            # actions restore the original dates, not a scanner-corrupted intermediate state.
            saved_lastplayed = common_actions._get_canonical_snapshot([ep['episodeid'] for ep in episodes], root_id, tag=tag)
            xbmc.log(f"nICo Context: [{tag}] Decision -> {'WATCHED' if target_playcount else 'UNWATCHED'} | {len(episodes)} episodes", xbmc.LOGINFO)

            # --- TOGGLE via nudge + SQL batch ---
            # 1 SetEpisodeDetails per season (fired BEFORE SQL so Kodi detects the change
            # and fires item-level events → badges update). Rest written via fast SQL batch.
            t0 = common_actions._ms()
            _nudge_and_sql_toggle(episodes, target_playcount, tag=tag)
            common_actions._restore_lastplayed(saved_lastplayed, tag=tag)
            _follow_profile(root_id, [ep['episodeid'] for ep in episodes], bool(target_playcount), tag)
            _update_restart_marks([ep['episodeid'] for ep in episodes],
                                  [ep['episodeid'] for ep in episodes if (ep.get('resume') or {}).get('position', 0) > 0],
                                  bool(target_playcount), tag)
            xbmc.executebuiltin('Container.Refresh')
            num_seasons = len(set(ep.get('season', 0) for ep in episodes))
            body = f"Changed to {state_label}: {common_actions._plural(num_seasons, 'season')}, {common_actions._plural(len(episodes), 'episode')}"
            xbmc.log(f"nICo Context: [{tag}] Complete | total={common_actions._ms()-t0}ms", xbmc.LOGINFO)
            common_locks.notification(show_title, body, xbmcgui.NOTIFICATION_INFO, 2500)

        else:
            # Single movie/episode — one RPC = one notification, no SQL needed
            xbmc.log(f"nICo Context: [{tag}] Single item path for {dbtype} {dbid}", xbmc.LOGINFO)
            rpc_types = {'movie': 'Movie', 'episode': 'Episode'}
            type_name = rpc_types.get(dbtype)
            if type_name:
                item_data = common_actions.execute_rpc(f"VideoLibrary.Get{type_name}Details", {f"{dbtype}id": int(dbid), "properties": ["playcount", "tvshowid", "season", "resume"]})
                xbmc.log(f"nICo Context: [{tag}] Get{type_name}Details result: {item_data}", xbmc.LOGINFO)
                details = item_data.get('result', {}).get(f'{dbtype}details', {})
                current_pc = details.get('playcount', 0)
                new_val = 1 if current_pc == 0 else 0
                state_label = "Watched" if new_val else "Unwatched"
                xbmc.log(f"nICo Context: [{tag}] current_playcount={current_pc} → new_playcount={new_val}", xbmc.LOGINFO)
                if not was_queued:
                    common_locks.notification(show_title, f"Marking {state_label}...", xbmcgui.NOTIFICATION_INFO, 3000)

                season_tipped = False
                season_eps = []
                if dbtype == 'episode':
                    tvshowid = details.get('tvshowid')
                    season_num = details.get('season')
                    if tvshowid is not None and season_num is not None:
                        season_eps = common_actions.execute_rpc("VideoLibrary.GetEpisodes", {
                            "tvshowid": tvshowid, "season": season_num, "properties": ["playcount"]
                        }).get('result', {}).get('episodes', [])
                        season_tipped = all(bool(e.get('playcount', 0)) == bool(current_pc) for e in season_eps)
                        xbmc.log(f"nICo Context: [{tag}] season_tipped={season_tipped} ({len(season_eps)} eps all {'watched' if current_pc else 'unwatched'})", xbmc.LOGINFO)

                set_params = {f"{dbtype}id": int(dbid), "playcount": new_val}
                if new_val == 1:
                    set_params["resume"] = {"position": 0, "total": 0}  # watched = done: clear the resume point
                set_res = common_actions.execute_rpc(f"VideoLibrary.Set{type_name}Details", set_params)
                xbmc.log(f"nICo Context: [{tag}] Set{type_name}Details result: {set_res}", xbmc.LOGINFO)
                if dbtype == 'episode':
                    _follow_profile(details.get('tvshowid'), [int(dbid)], bool(new_val), tag)
                    _update_restart_marks([int(dbid)], [int(dbid)] if (details.get('resume') or {}).get('position', 0) > 0 else [],
                                          bool(new_val), tag)
                    if season_tipped:
                        body = f"Changed to {state_label}: {common_actions._plural(1, 'season')}, {common_actions._plural(1, 'episode')}."
                    else:
                        body = f"Changed to {state_label}: {common_actions._plural(1, 'episode')}."
                    if season_eps and new_val == 1:
                        post_toggle = {e['episodeid']: (new_val if e['episodeid'] == int(dbid) else e.get('playcount', 0)) for e in season_eps}
                        first_unwatched = next((e for e in season_eps if post_toggle[e['episodeid']] == 0), None)
                        if first_unwatched is not None:
                            xbmc.sleep(100)
                            nav_focus.focus_episode(first_unwatched['episodeid'], tag=tag)
                else:
                    body = f"Changed to {state_label}."
                xbmc.log(f"nICo Context: [{tag}] Complete", xbmc.LOGINFO)
                common_locks.notification(show_title, body, xbmcgui.NOTIFICATION_INFO, 2500)
            else:
                xbmc.log(f"nICo Context: [{tag}] Unhandled dbtype '{dbtype}' — no action taken", xbmc.LOGWARNING)
    finally:
        common_locks.release(lock_path, root_id, tag=tag, show_name=show_title)


if __name__ == '__main__':
    common_locks._log_thread_info("TOGGLE")
    common_locks.cleanup_stale_locks()
    xbmc.log("nICo Context: Triggering Watch Toggle", xbmc.LOGINFO)
    toggle_watch_state()

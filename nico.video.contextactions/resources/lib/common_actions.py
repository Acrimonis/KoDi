import sqlite3, xbmc, xbmcgui, json, time, re
import common_locks
import common_db


def _episodes_to_idfile(episodes, tag=""):
    """Return {episodeid: idFile} for the given episode list via a direct DB read."""
    all_eids = [ep['episodeid'] for ep in episodes]
    if not all_eids:
        return {}
    placeholders = ','.join('?' * len(all_eids))
    try:
        conn = sqlite3.connect(common_db._kodi_db_path(), timeout=5.0)
        try:
            rows = conn.execute(
                f"SELECT idEpisode, idFile FROM episode WHERE idEpisode IN ({placeholders})",
                all_eids
            ).fetchall()
        finally:
            conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] _episodes_to_idfile SQL error: {e}", xbmc.LOGERROR)
        return {}


def _resolve_root_id(dbid, dbtype):
    """Return the tvshowid int that owns this item — used as the mutex key.
    For tvshow: dbid itself. For season/episode: one RPC to get tvshowid.
    For movie/other: use dbid directly (movies have no shared parent)."""
    try:
        dbid_int = int(dbid)
        if dbtype == 'tvshow':
            return dbid_int
        if dbtype == 'season':
            res = execute_rpc("VideoLibrary.GetSeasonDetails", {"seasonid": dbid_int, "properties": ["tvshowid"]})
            return res.get('result', {}).get('seasondetails', {}).get('tvshowid', dbid_int)
        if dbtype == 'episode':
            res = execute_rpc("VideoLibrary.GetEpisodeDetails", {"episodeid": dbid_int, "properties": ["tvshowid"]})
            return res.get('result', {}).get('episodedetails', {}).get('tvshowid', dbid_int)
    except Exception:
        pass
    return int(dbid)

def _ms():
    return int(time.time() * 1000)

def execute_rpc(method, params):
    rpc = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    return json.loads(xbmc.executeJSONRPC(json.dumps(rpc)))

def _plural(n, word):
    return f"{n} {word}{'s' if n != 1 else ''}"


def _fetch_show_title(tvshowid, fallback=""):
    """Re-fetch the current show title from Kodi DB — useful after a scrape that may have updated it."""
    res = execute_rpc("VideoLibrary.GetTVShowDetails", {"tvshowid": int(tvshowid), "properties": ["title"]})
    return res.get("result", {}).get("tvshowdetails", {}).get("title", fallback) or fallback


def _get_canonical_snapshot(episode_ids, root_id, tag=""):
    """Query current lastPlayed from DB and merge into the shared per-show snapshot file.

    The first action for a show creates the snapshot (truth = DB values before any action ran).
    Subsequent queued actions inherit the existing snapshot and only add missing idFiles.

    This prevents a queued TOGGLE from "preserving" a scanner-corrupted intermediate state:
    if REFRESH releases its lock while the background scanner is still running, TOGGLE would
    naively snapshot the half-wiped DB. With the shared snapshot, every action in the queue
    restores the same original dates regardless of scanner activity between actions.

    Returns the canonical {idFile (int): lastPlayed (str)} dict.
    """
    if not episode_ids:
        xbmc.log(f"nICo Context: [{tag}] SNAPSHOT: no episode_ids provided", xbmc.LOGWARNING)
        return {}
    placeholders = ','.join('?' * len(episode_ids))
    try:
        with common_db.kodi_db_context(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT e.idEpisode, e.idFile, f.lastPlayed FROM episode e "
                f"JOIN files f ON f.idFile = e.idFile WHERE e.idEpisode IN ({placeholders})",
                list(episode_ids)
            ).fetchall()
        fresh = {row[1]: row[2] or '' for row in rows}
        sample = next(iter(rows), None)
        if sample:
            xbmc.log(
                f"nICo Context: [{tag}] SNAPSHOT sample: idEpisode={sample[0]} "
                f"idFile={sample[1]} lastPlayed='{sample[2]}'",
                xbmc.LOGINFO
            )
        xbmc.log(
            f"nICo Context: [{tag}] SNAPSHOT queried {len(fresh)} idFiles from DB "
            f"(from {len(episode_ids)} episodeids)",
            xbmc.LOGINFO
        )
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] SNAPSHOT SQL error: {str(e)}", xbmc.LOGERROR)
        return {}
    # Merge into (or create) the shared snapshot file — existing entries never overwritten.
    return common_locks.merge_and_save_snapshot(root_id, fresh, tag=tag)


def _restore_lastplayed(saved_dict, tag=""):
    """Restore {idFile: lastPlayed} via SQL, skipping files already at the correct value.

    Only updates files whose current lastPlayed differs from the snapshot — avoids
    redundant writes and reduces noise when a prior SQL toggle already wrote the correct date.
    """
    t = _ms()
    try:
        with common_db.kodi_db_context() as conn:
            placeholders = ','.join('?' * len(saved_dict))
            current = {r[0]: (r[1] or '') for r in conn.execute(
                f"SELECT idFile, lastPlayed FROM files WHERE idFile IN ({placeholders})",
                list(saved_dict.keys())
            ).fetchall()}
            changed = []
            for file_id, lp in saved_dict.items():
                want = lp or ''
                if current.get(file_id, '') != want:
                    conn.execute("UPDATE files SET lastPlayed = ? WHERE idFile = ?", [lp or None, file_id])
                    changed.append((file_id, lp))
        xbmc.log(
            f"nICo Context: [{tag}] restore SQL={_ms()-t}ms — "
            f"{len(changed)}/{len(saved_dict)} files updated (rest already correct)",
            xbmc.LOGINFO
        )
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] restore SQL EXCEPTION: {str(e)}", xbmc.LOGERROR)


def _snapshot_playcount(idfile_list, tag=""):
    """Read current playCount for the given idFile list. Returns {idFile: playCount}.
    NOT merged into the shared canonical snapshot — taken immediately before refresh runs
    so it captures any playcount set by a prior queued action (e.g. TOGGLE before REFRESH).
    """
    if not idfile_list:
        return {}
    placeholders = ','.join('?' * len(idfile_list))
    try:
        with common_db.kodi_db_context(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT idFile, playCount FROM files WHERE idFile IN ({placeholders})",
                list(idfile_list)
            ).fetchall()
        result = {row[0]: row[1] or 0 for row in rows}
        xbmc.log(f"nICo Context: [{tag}] playcount snapshot: {len(result)} files", xbmc.LOGINFO)
        return result
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] _snapshot_playcount SQL error: {e}", xbmc.LOGERROR)
        return {}


def _restore_playcount(saved_pc, tag=""):
    """Restore playCount for idFiles, skipping those already at the correct value."""
    if not saved_pc:
        return
    t = _ms()
    try:
        with common_db.kodi_db_context() as conn:
            placeholders = ','.join('?' * len(saved_pc))
            current = {r[0]: r[1] or 0 for r in conn.execute(
                f"SELECT idFile, playCount FROM files WHERE idFile IN ({placeholders})",
                list(saved_pc.keys())
            ).fetchall()}
            changed = []
            for file_id, pc in saved_pc.items():
                if current.get(file_id, 0) != pc:
                    conn.execute("UPDATE files SET playCount = ? WHERE idFile = ?", [pc, file_id])
                    changed.append(file_id)
        xbmc.log(
            f"nICo Context: [{tag}] restore playcount SQL={_ms()-t}ms — "
            f"{len(changed)}/{len(saved_pc)} files updated",
            xbmc.LOGINFO
        )
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] restore playcount EXCEPTION: {e}", xbmc.LOGERROR)



def _pick_marker(saved_dict):
    """Return the first idFile with a non-empty lastPlayed, or None."""
    return next((fid for fid, lp in saved_dict.items() if lp and str(lp) != 'None'), None)


def _wait_for_db_change(marker_file, saved_lp, timeout_ms, tag="", poll_ms=100):
    """Poll files.lastPlayed for marker_file until it differs from saved_lp.

    Kodi writes lastPlayed on a background thread after Action(ToggleWatched) and
    after RefreshTVShow's async scan. This detects that write so we can restore
    immediately after. Uses a plain read connection (not BEGIN IMMEDIATE) to avoid
    blocking Kodi's writer.

    Returns True if change detected, False if timed out.
    """
    db_path = common_db._kodi_db_path()
    saved_lp = str(saved_lp or '')
    poll_start = _ms()
    last_log_ms = -1000  # force a log on the first poll
    last_notif_ms = _ms()
    while _ms() - poll_start < timeout_ms:
        xbmc.sleep(poll_ms)
        t_connect = _ms()
        elapsed = _ms() - poll_start
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            t_connected = _ms()
            try:
                row = conn.execute("SELECT lastPlayed FROM files WHERE idFile = ?", [marker_file]).fetchone()
            finally:
                conn.close()
            current = (row[0] or '') if row else ''
            connect_ms = t_connected - t_connect
            if connect_ms > 50:
                xbmc.log(f"nICo Context: [{tag}] Poll BLOCKED on connect for {connect_ms}ms (lock held by writer)", xbmc.LOGWARNING)
        except Exception as ex:
            xbmc.log(f"nICo Context: [{tag}] Poll read error ({_ms()-t_connect}ms): {ex}", xbmc.LOGWARNING)
            current = saved_lp
        if current != saved_lp:
            xbmc.log(f"nICo Context: [{tag}] Change detected at t={elapsed}ms idFile={marker_file} {saved_lp!r} → {current!r}", xbmc.LOGINFO)
            return True
        # Log only once per second to avoid spam
        if elapsed - last_log_ms >= 1000:
            xbmc.log(f"nICo Context: [{tag}] Poll t={elapsed}ms: idFile={marker_file} waiting for change (saved={saved_lp!r})", xbmc.LOGINFO)
            last_log_ms = elapsed
        now = _ms()
        if now - last_notif_ms >= 850:
            common_locks._show_queue_notification()
            last_notif_ms = now
    xbmc.log(f"nICo Context: [{tag}] Poll timed out after {timeout_ms}ms — scanner did not wipe lastPlayed (no-op, restoring as-is)", xbmc.LOGWARNING)
    return False


def _wait_for_all_changed(saved_lastplayed, timeout_ms, tag="", poll_ms=25, idle_timeout_ms=5000, dynamic_idle=False):
    """Wait until Kodi has finished changing all originally-dated files from their snapshot values.

    Used for both REFRESH (async scanner) and TOGGLE (async bulk update).

    Exit conditions (first one wins):
      1. All monitored files have changed — Kodi fully done.
      2. Idle timeout — no file changed for idle_timeout_ms (static) or interval*5 (dynamic).
         Dynamic mode (dynamic_idle=True): idle threshold adapts to the observed gap between
         consecutive change events — ideal for TOGGLE where Kodi processes files sequentially
         at a consistent rate. Static mode (default): fixed idle_timeout_ms for REFRESH where
         some files are simply skipped by the scanner.
      3. Library.IsScanningVideo == False — scanner globally finished (REFRESH only).
         Guard: only checked after at least one file changed to avoid false-negatives before
         the scan is registered as started.
      4. Hard timeout (timeout_ms) as absolute safety net.

    Only files with a non-empty original lastPlayed are monitored — unwatched files
    (original='') are skipped since Kodi does not touch their lastPlayed on UNWATCHED toggle.
    For WATCHED toggle this is fine: files with original='' that get a new date are not
    at risk of corrupting sort order (they had no date to preserve).
    """
    db_path = common_db._kodi_db_path()
    # Only watch files that had a date — those are the ones Kodi will change.
    watching = {fid: lp for fid, lp in saved_lastplayed.items() if lp and str(lp) not in ('', 'None')}
    if not watching:
        xbmc.log(f"nICo Context: [{tag}] _wait_for_all_changed: no dated files to monitor, skipping", xbmc.LOGINFO)
        return
    id_list = ','.join(str(f) for f in watching)
    t0 = _ms()
    last_log_ms = -1000
    still_original = set(watching.keys())
    last_progress_ms = _ms()
    last_notif_ms = _ms()

    # Track interval between consecutive change events.
    # Used by dynamic_idle to self-calibrate the idle threshold, and by both modes
    # to compute an adaptive hard timeout (interval_estimate × remaining × 10).
    last_change_time = None     # wall-clock ms of the most recent change event
    interval_estimate = 2000    # ms — initial estimate, refined on every change batch

    while True:
        elapsed = _ms() - t0
        xbmc.sleep(poll_ms)
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                rows = conn.execute(
                    f"SELECT idFile, lastPlayed FROM files WHERE idFile IN ({id_list})"
                ).fetchall()
            finally:
                conn.close()
            # A file is "done" once its current value differs from the original snapshot.
            new_still_original = {r[0] for r in rows if (r[1] or '') == watching[r[0]]}

            # Detect progress: files that changed since the last poll.
            newly_done = still_original - new_still_original
            if newly_done:
                now = _ms()
                if last_change_time is not None:
                    interval_estimate = now - last_change_time
                last_change_time = now
                last_progress_ms = now
            still_original = new_still_original

            # Exit 1: all our files changed — Kodi fully processed all episodes.
            if not still_original:
                xbmc.log(
                    f"nICo Context: [{tag}] _wait_for_all_changed: all {len(watching)} files "
                    f"changed from original at t={elapsed}ms — done",
                    xbmc.LOGINFO
                )
                return

            idle_ms = _ms() - last_progress_ms

            # Compute effective idle threshold.
            if dynamic_idle:
                # Adapt to observed processing rate: wait 5× the typical inter-change gap.
                # Floor at 1s to avoid premature exits on slow polling or batched writes.
                effective_idle = max(1000, interval_estimate * 5)
            else:
                effective_idle = idle_timeout_ms

            # Exit 2: idle — no file changed for effective_idle ms.
            if idle_ms >= effective_idle:
                done = len(watching) - len(still_original)
                xbmc.log(
                    f"nICo Context: [{tag}] _wait_for_all_changed: no progress for {idle_ms}ms "
                    f"(threshold={effective_idle}ms, interval_est={interval_estimate}ms) "
                    f"— idle exit. {done}/{len(watching)} files changed. "
                    f"{len(still_original)} remaining idFiles={sorted(still_original)} — restoring",
                    xbmc.LOGINFO
                )
                return

            if elapsed - last_log_ms >= 1000:
                done = len(watching) - len(still_original)
                xbmc.log(
                    f"nICo Context: [{tag}] Progress: {done}/{len(watching)} files changed "
                    f"at t={elapsed}ms idle={idle_ms}ms thresh={effective_idle}ms "
                    f"(still waiting on idFiles={sorted(still_original)})",
                    xbmc.LOGINFO
                )
                last_log_ms = elapsed
            now = _ms()
            if now - last_notif_ms >= 850:
                common_locks._show_queue_notification()
                last_notif_ms = now
        except Exception as ex:
            xbmc.log(f"nICo Context: [{tag}] _wait_for_all_changed read error: {ex}", xbmc.LOGWARNING)

        # Exit 4: adaptive safety net — scales with observed processing rate and remaining files.
        # timeout_ms is the floor; actual limit grows to cover large shows at slow rates.
        adaptive_timeout = max(timeout_ms, interval_estimate * max(len(still_original), 1) * 10)
        if elapsed >= adaptive_timeout:
            xbmc.log(
                f"nICo Context: [{tag}] _wait_for_all_changed hard timeout after {elapsed}ms "
                f"(adaptive={adaptive_timeout}ms, interval_est={interval_estimate}ms, "
                f"remaining={len(still_original)}) — "
                f"{len(still_original)} file(s) still unchanged idFiles={sorted(still_original)} — restoring as-is",
                xbmc.LOGWARNING
            )
            return


def get_target_info():
    dbid = xbmc.getInfoLabel('ListItem.DBID')
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE').lower()
    return dbid, dbtype

def get_episodes(dbid, dbtype, extra_props=None):
    """Fetch episodes for a tvshow or season with Tier 1 + Tier 2 fallback.
    Note: 'episodeid' is always returned automatically and must NOT be in properties."""
    props = ["season"] + (extra_props or [])
    params = {"properties": props}
    if dbtype == 'tvshow':
        params["tvshowid"] = int(dbid)
    elif dbtype == 'season':
        res_s = execute_rpc("VideoLibrary.GetSeasonDetails", {"seasonid": int(dbid), "properties": ["tvshowid", "season"]})
        s_details = res_s.get('result', {}).get('seasondetails', {})
        if s_details:
            params["tvshowid"] = s_details['tvshowid']
            params["season"] = s_details['season']

    xbmc.log(f"nICo Context: [EPISODES] GetEpisodes params: {params}", xbmc.LOGINFO)
    res = execute_rpc("VideoLibrary.GetEpisodes", params)
    episodes = res.get('result', {}).get('episodes', [])
    xbmc.log(f"nICo Context: [EPISODES] Tier 1 found: {len(episodes)}", xbmc.LOGINFO)
    if not episodes:
        xbmc.log(f"nICo Context: [EPISODES] Tier 1 raw response: {res}", xbmc.LOGINFO)

    if not episodes and dbtype == 'tvshow':
        # Tier 2: GetEpisodes(tvshowid) can return 0 if episodes aren't linked directly.
        # Fall back to GetSeasons → GetEpisodes per season (uses a different DB path).
        xbmc.log(f"nICo Context: [EPISODES] Tier 2 (tvshow) — fetching via GetSeasons for show {dbid}", xbmc.LOGINFO)
        seasons_res = execute_rpc("VideoLibrary.GetSeasons", {"tvshowid": int(dbid), "properties": ["season"]})
        seasons = seasons_res.get('result', {}).get('seasons', [])
        season_nums = [s.get('season') for s in seasons if s.get('season') is not None]
        xbmc.log(f"nICo Context: [EPISODES] Tier 2 seasons: {season_nums}", xbmc.LOGINFO)
        for season_num in season_nums:
            ep_res = execute_rpc("VideoLibrary.GetEpisodes", {
                "tvshowid": int(dbid), "season": season_num, "properties": props
            })
            eps = ep_res.get('result', {}).get('episodes', [])
            xbmc.log(f"nICo Context: [EPISODES] Tier 2 S{season_num}: {len(eps)} episodes", xbmc.LOGINFO)
            episodes.extend(eps)
        xbmc.log(f"nICo Context: [EPISODES] Tier 2 total: {len(episodes)}", xbmc.LOGINFO)

    if not episodes and dbtype == 'season':
        path = xbmc.getInfoLabel('ListItem.FolderPath')
        xbmc.log(f"nICo Context: [EPISODES] Tier 1 failed. Trying Tier 2. FolderPath='{path}'", xbmc.LOGINFO)
        match = re.search(r'/(\d+)/(\d+)/?(\?.*)?$', path)
        if match:
            show_id, season_num = int(match.group(1)), int(match.group(2))
            xbmc.log(f"nICo Context: [EPISODES] Tier 2 matched: ShowID={show_id}, SeasonNum={season_num}", xbmc.LOGINFO)
            res = execute_rpc("VideoLibrary.GetEpisodes", {
                "tvshowid": show_id, "season": season_num, "properties": props
            })
            episodes = res.get('result', {}).get('episodes', [])
            xbmc.log(f"nICo Context: [EPISODES] Tier 2 found: {len(episodes)}", xbmc.LOGINFO)
        else:
            xbmc.log(f"nICo Context: [EPISODES] Tier 2 regex did NOT match path: '{path}'", xbmc.LOGINFO)

    if not episodes:
        xbmc.log(f"nICo Context: [EPISODES] FAILED — no episodes resolved for {dbtype} {dbid}", xbmc.LOGERROR)
    return episodes


def refresh():
    dbid, dbtype = get_target_info()
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    tag = f"REFRESH_Local:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] Triggered | dbid='{dbid}' dbtype='{dbtype}'", xbmc.LOGINFO)

    if not dbid or dbid == "-1":
        xbmc.log(f"nICo Context: [{tag}] Aborted — no valid DBID.", xbmc.LOGWARNING)
        return

    rpc_map = {'movie': 'Movie', 'tvshow': 'TVShow', 'season': 'Season', 'episode': 'Episode'}
    method_suffix = rpc_map.get(dbtype)
    if not method_suffix:
        xbmc.log(f"nICo Context: [{tag}] Aborted — unhandled dbtype '{dbtype}'.", xbmc.LOGWARNING)
        return

    method = f"VideoLibrary.Refresh{method_suffix}"
    params = {f"{dbtype}id": int(dbid), "ignorenfo": False}

    root_id = _resolve_root_id(dbid, dbtype)
    lock_path, was_queued = common_locks.acquire(root_id, tag=tag, show_name=show_title,
        on_queue=lambda: common_locks.notification(show_title, "Local Refresh queued...", xbmcgui.NOTIFICATION_INFO, 3000))
    xbmc.log(f"nICo Context: [{tag}] Lock acquired root_id={root_id}", xbmc.LOGINFO)
    if not was_queued:
        common_locks.notification(show_title, "Local Refresh...", xbmcgui.NOTIFICATION_INFO, 3000)
    try:
        # Snapshot lastplayed and playcount before any refresh call (local single episode)
        saved_lp_dict = None
        saved_pc_dict = None
        if dbtype == 'episode':
            xbmc.log(f"nICo Context: [{tag}] Pre-snapshot: single episode {dbid}", xbmc.LOGINFO)
            saved_lp_dict = _get_canonical_snapshot([int(dbid)], root_id, tag=tag)
            saved_pc_dict = _snapshot_playcount(list(saved_lp_dict.keys()), tag=tag)

        # Snapshot lastplayed before any refresh call (local recursive tvshow/season)
        pre_episodes = None
        saved_lastplayed = None
        if dbtype in ['tvshow', 'season']:
            xbmc.log(f"nICo Context: [{tag}] Pre-snapshot: fetching child episodes for {dbtype} {dbid}", xbmc.LOGINFO)
            pre_episodes = get_episodes(dbid, dbtype)
            if pre_episodes:
                saved_lastplayed = _get_canonical_snapshot([ep['episodeid'] for ep in pre_episodes], root_id, tag=tag)
                saved_playcount = _snapshot_playcount(list(saved_lastplayed.keys()), tag=tag)
                xbmc.log(f"nICo Context: [{tag}] Pre-snapshot: {len(saved_lastplayed)} idFile entries in canonical snapshot", xbmc.LOGINFO)
            else:
                xbmc.log(f"nICo Context: [{tag}] Pre-snapshot: no episodes found, lastplayed will not be restored.", xbmc.LOGWARNING)

        t0 = _ms()

        if dbtype in ['tvshow', 'season']:
            # Local recursive path: RefreshEpisode per episode first (synchronous, no background scan).
            # Then call Refresh{TVShow|Season} which triggers Kodi's async background scanner.
            # We poll for the scanner's lastPlayed wipe, then restore.
            if not pre_episodes:
                xbmc.log(f"nICo Context: [{tag}] No pre-snapshot — skipping recursive refresh.", xbmc.LOGWARNING)
                return
            num_seasons = len(set(ep.get('season', 0) for ep in pre_episodes))
            ep_count = len(pre_episodes)
            xbmc.log(f"nICo Context: [{tag}] Refreshing {ep_count} episodes across {num_seasons} season(s)", xbmc.LOGINFO)
            t1 = _ms()
            errors = 0
            last_notif_ms = 0
            for ep in pre_episodes:
                xbmc.log(f"nICo Context: [{tag}] Calling RefreshEpisode ep{ep['episodeid']} (S{ep.get('season','?')})", xbmc.LOGINFO)
                ep_res = execute_rpc("VideoLibrary.RefreshEpisode", {"episodeid": ep['episodeid'], "ignorenfo": False})
                if ep_res.get('result') != "OK":
                    errors += 1
                    xbmc.log(f"nICo Context: [{tag}] RefreshEpisode ep{ep['episodeid']} FAILED: {ep_res.get('error')}", xbmc.LOGERROR)
                else:
                    xbmc.log(f"nICo Context: [{tag}] RefreshEpisode ep{ep['episodeid']}: OK", xbmc.LOGINFO)
                now = _ms()
                if now - last_notif_ms >= 850:
                    common_locks._show_queue_notification()
                    last_notif_ms = now
            xbmc.log(f"nICo Context: [{tag}] All episodes done in {_ms()-t1}ms | errors={errors}/{ep_count}", xbmc.LOGINFO)

            marker_file = _pick_marker(saved_lastplayed)
            xbmc.log(f"nICo Context: [{tag}] Scan marker: idFile={marker_file} lastPlayed={saved_lastplayed.get(marker_file)!r}", xbmc.LOGINFO)

            if dbtype == 'tvshow':
                xbmc.log(f"nICo Context: [{tag}] Calling {method} (post-episode) | params={params}", xbmc.LOGINFO)
                show_res = execute_rpc(method, params)
                xbmc.log(f"nICo Context: [{tag}] {method} response={show_res}", xbmc.LOGINFO)

            if marker_file:
                _wait_for_db_change(marker_file, saved_lastplayed[marker_file], timeout_ms=30000, tag=tag, poll_ms=100)
                _wait_for_all_changed(saved_lastplayed, timeout_ms=30000, tag=tag)
            elif saved_lastplayed:
                xbmc.log(f"nICo Context: [{tag}] No watched marker — sleeping 5s for async scan", xbmc.LOGWARNING)
                xbmc.sleep(5000)

            xbmc.log(f"nICo Context: [{tag}] Restoring lastplayed for {len(saved_lastplayed)} files", xbmc.LOGINFO)
            _restore_lastplayed(saved_lastplayed, tag=tag)
            _restore_playcount(saved_playcount, tag=tag)
            xbmc.log(f"nICo Context: [{tag}] Total={_ms()-t0}ms", xbmc.LOGINFO)

            body = f"{_plural(ep_count, 'episode')}"
            if dbtype == 'tvshow':
                body = f"1 show, {_plural(num_seasons, 'season')}, {body}"
            else:
                body = f"{_plural(num_seasons, 'season')}, {body}"
            if errors:
                body += f" ({errors} failed)"
            fresh_title = _fetch_show_title(root_id, show_title)
            common_locks.notification(fresh_title, f"Local Refresh: {body}.", xbmcgui.NOTIFICATION_INFO, 3000)

        elif dbtype == 'episode':
            xbmc.log(f"nICo Context: [{tag}] Calling {method} | params={params}", xbmc.LOGINFO)
            response = execute_rpc(method, params)
            xbmc.log(f"nICo Context: [{tag}] {method} response={response} ({_ms()-t0}ms)", xbmc.LOGINFO)
            if response.get('result') != "OK":
                raise Exception(f"RPC returned error: {response.get('error')}")
            if saved_lp_dict:
                marker_file = _pick_marker(saved_lp_dict)
                if marker_file:
                    _wait_for_db_change(marker_file, saved_lp_dict[marker_file], timeout_ms=5000, tag=tag, poll_ms=100)
                else:
                    xbmc.sleep(2000)
                xbmc.log(f"nICo Context: [{tag}] Restoring lastplayed for ep{dbid} ({len(saved_lp_dict)} files)", xbmc.LOGINFO)
                _restore_lastplayed(saved_lp_dict, tag=tag)
                _restore_playcount(saved_pc_dict, tag=tag)
            xbmc.executebuiltin('Container.Refresh')
            fresh_title = _fetch_show_title(root_id, show_title)
            common_locks.notification(fresh_title, "Local Refresh: 1 episode.", xbmcgui.NOTIFICATION_INFO, 3000)

        else:
            xbmc.log(f"nICo Context: [{tag}] Calling {method} | params={params}", xbmc.LOGINFO)
            response = execute_rpc(method, params)
            xbmc.log(f"nICo Context: [{tag}] {method} response={response} ({_ms()-t0}ms)", xbmc.LOGINFO)
            if response.get('result') != "OK":
                raise Exception(f"RPC returned error: {response.get('error')}")

    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] EXCEPTION: {str(e)}", xbmc.LOGERROR)
    finally:
        common_locks.release(lock_path, root_id, tag=tag, show_name=show_title)

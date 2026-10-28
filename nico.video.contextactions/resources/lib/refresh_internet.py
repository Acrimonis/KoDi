import xbmc
import xbmcgui
import common_locks
import common_actions

_IDLE_TIMEOUT_MS = 15_000  # time out only if no OnUpdate received for this long
_IDLE_TIMEOUT_START_MS = 30_000  # time out only if no OnUpdate received for this long


class _UpdateMonitor(xbmc.Monitor):
    def __init__(self, expected, tag):
        super().__init__()
        self.expected = expected
        self.count = 0
        self.done = False
        self.tag = tag
        self.last_update_ms = None  # set on first OnUpdate
        self.interval_estimate = 6000  # Default 6s -> 30s timeout (matches START_MS)

    def onNotification(self, sender, method, data):
        if method == "VideoLibrary.OnUpdate":
            now = common_actions._ms()
            if self.last_update_ms is not None:
                self.interval_estimate = now - self.last_update_ms
            
            self.count += 1
            self.last_update_ms = now
            xbmc.log(f"nICo Context: [{self.tag}] OnUpdate {self.count}/{self.expected} (gap={self.interval_estimate if self.count > 1 else 'N/A'}ms)", xbmc.LOGINFO)
            if self.count >= self.expected:
                self.done = True


def _refresh_internet():
    dbid, dbtype = common_actions.get_target_info()
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    tag = f"REFRESH_Internet:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] Triggered | dbid='{dbid}' dbtype='{dbtype}'", xbmc.LOGINFO)

    if not dbid or dbid == "-1":
        xbmc.log(f"nICo Context: [{tag}] Aborted — no valid DBID.", xbmc.LOGWARNING)
        return

    rpc_map = {'movie': 'Movie', 'tvshow': 'TVShow', 'season': 'Season', 'episode': 'Episode'}
    method_suffix = rpc_map.get(dbtype)
    if not method_suffix:
        xbmc.log(f"nICo Context: [{tag}] Aborted — unhandled dbtype '{dbtype}'.", xbmc.LOGWARNING)
        return

    root_id = common_actions._resolve_root_id(dbid, dbtype)
    lock_path, was_queued = common_locks.acquire(root_id, tag=tag, show_name=show_title,
        on_queue=lambda: common_locks.notification(show_title, "Internet Refresh queued\u2026", xbmcgui.NOTIFICATION_INFO, 3000))
    # Mark as 'inet' so queue notification shows "internet fetch" instead of "running"
    common_locks._write_lock_status(lock_path, 'inet')
    if not was_queued:
        common_locks.notification(show_title, "Internet Refresh\u2026", xbmcgui.NOTIFICATION_INFO, 3000)
    try:
        # For tvshow/season: count expected OnUpdate events (1 for show + 1 per episode)
        expected = 1
        ep_count = 0
        saved_pc = {}
        saved_lp = {}
        if dbtype in ('tvshow', 'season'):
            episodes = common_actions.get_episodes(dbid, dbtype)
            ep_count = len(episodes)
            expected = 1 + ep_count
            xbmc.log(f"nICo Context: [{tag}] Expecting {expected} OnUpdate events (1 show + {ep_count} episodes)", xbmc.LOGINFO)
            if episodes:
                ep_to_idfile = common_actions._episodes_to_idfile(episodes, tag=tag)
                saved_lp = common_actions._get_canonical_snapshot([ep['episodeid'] for ep in episodes], root_id, tag=tag)
                saved_pc = common_actions._snapshot_playcount(list(ep_to_idfile.values()), tag=tag)

        params = {f"{dbtype}id": int(dbid), "ignorenfo": True}
        if dbtype in ('tvshow', 'season'):
            params["refreshepisodes"] = True

        monitor = _UpdateMonitor(expected, tag)

        t0 = common_actions._ms()
        xbmc.log(f"nICo Context: [{tag}] Calling VideoLibrary.Refresh{method_suffix} | params={params}", xbmc.LOGINFO)
        if dbtype == 'season':
            # Kodi has no RefreshSeason; iterate episodes manually
            for ep in episodes:
                common_actions.execute_rpc("VideoLibrary.RefreshEpisode", {"episodeid": ep['episodeid'], "ignorenfo": True})
            response = {'result': 'OK'}
        else:
            response = common_actions.execute_rpc(f"VideoLibrary.Refresh{method_suffix}", params)
            if response.get('result') != 'OK':
                raise Exception(f"RPC error: {response.get('error')}")

        # Initialize to current time to ensure a 3s delay before the first status heartbeat
        loop_start_ms = common_actions._ms()
        last_log_ms = loop_start_ms
        last_notif_ms = loop_start_ms
        zeTimeout = _IDLE_TIMEOUT_START_MS
        exit_reason = "timeout"

        while not monitor.done:
            xbmc.sleep(200)
            now = common_actions._ms()

            # Adapt timeout based on observed notification frequency (Interval * 20)
            if monitor.count > 0:
                new_timeout = max(_IDLE_TIMEOUT_MS, monitor.interval_estimate * 20)
                if zeTimeout == _IDLE_TIMEOUT_START_MS and new_timeout != _IDLE_TIMEOUT_START_MS:
                    xbmc.log(f"nICo Context: [{tag}] Activity detected, switching to adaptive timeout", xbmc.LOGINFO)
                zeTimeout = new_timeout

            if now - last_log_ms >= 1000:
                seconds = (now - loop_start_ms) // 1000
                xbmc.log(f"nICo Context: [{tag}] Waiting for OnUpdate events... ({monitor.count}/{expected}) t={seconds}s/{zeTimeout/1000}s", xbmc.LOGINFO)
                last_log_ms = now                

            if now - last_notif_ms >= 850:
                xbmc.log(f"nICo Context: [{tag}] Show queue notification", xbmc.LOGINFO)
                common_locks._show_queue_notification()
                last_notif_ms = now

            # Idle timeout: give up if zeTimeout
            last_seen = monitor.last_update_ms or t0            
            if now - last_seen >= zeTimeout:
                if monitor.last_update_ms is None:
                    xbmc.log(f"nICo Context: [{tag}] timed out -- no ep  -- [{zeTimeout}ms] -> EXITING -> IsScanningVideo: {xbmc.getCondVisibility('Library.IsScanningVideo')}", xbmc.LOGINFO)
                    break
                else:
                    xbmc.log(f"nICo Context: [{tag}] timed out -- w/ eps -- [{zeTimeout}ms] -> EXITING -> IsScanningVideo: {xbmc.getCondVisibility('Library.IsScanningVideo')}", xbmc.LOGINFO)
                    break
                   
        elapsed = common_actions._ms() - t0
        if saved_pc:
            common_actions._restore_playcount(saved_pc, tag=tag)
        if saved_lp:
            common_actions._restore_lastplayed(saved_lp, tag=tag)
        fresh_title = common_actions._fetch_show_title(root_id, show_title) if dbtype in ('tvshow', 'season') else show_title
        
        if monitor.done:
            exit_reason = "done"

        if exit_reason == "done":
            xbmc.log(f"nICo Context: [{tag}] Done — {monitor.count}/{expected} updates in {elapsed}ms", xbmc.LOGINFO)
            body = f"Internet Refresh: {common_actions._plural(ep_count, 'episode')}." if dbtype in ('tvshow', 'season') else "Internet Refresh done."
            common_locks.notification(fresh_title, body, xbmcgui.NOTIFICATION_INFO, 2500)
        else:
            xbmc.log(f"nICo Context: [{tag}] Idle timeout after {elapsed}ms — no OnUpdate for {zeTimeout}ms ({monitor.count}/{expected} received)", xbmc.LOGWARNING)
            common_locks.notification(fresh_title, f"Internet Refresh: Timed out ({monitor.count}/{expected}).", xbmcgui.NOTIFICATION_WARNING, 2500)

    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] EXCEPTION: {e}", xbmc.LOGERROR)
        common_locks.notification(show_title, "Internet Refresh: Error.", xbmcgui.NOTIFICATION_ERROR, 4000)
    finally:
        common_locks.release(lock_path, root_id, tag=tag, show_name=show_title)


if __name__ == '__main__':
    common_locks._log_thread_info("REFRESH_INET")
    common_locks.cleanup_stale_locks()
    _refresh_internet()

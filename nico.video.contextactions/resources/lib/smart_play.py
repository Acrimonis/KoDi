import xbmc
import xbmcgui
import sys
import common_actions
import common_locks
import smart_cmd

_REWIND_SECONDS = 5
# The bound key's original action (Kodi's default keymaps: remote <play> and keyboard <play_pause>
# both map to PlayPause). Override with RunScript(...smart_play.py,<Action>).
_FALLBACK = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else 'PlayPause'


def _default_play(tag, reason):
    xbmc.log(f"nICo Context: [{tag}] Default play ({_FALLBACK}) — {reason}", xbmc.LOGINFO)
    xbmc.executebuiltin(f'Action({_FALLBACK})')


def _episode_order(e):
    """Season then episode, specials (season 0) last."""
    return (e.get('season', 0) == 0, e.get('season', 0), e.get('episode', 0))


def _derive_profile(show_id, tag):
    """Build and write a profile from library state. Returns the written profile, or None."""
    episodes = common_actions.get_episodes(show_id, 'tvshow', extra_props=["playcount", "episode", "lastplayed", "resume"])
    if not episodes:
        return None
    played = [e for e in episodes if e.get('lastplayed')]
    if played:
        # Most recently played; ties (e.g. after Watched to Past...) -> furthest season/episode
        target = max(played, key=lambda e: (e['lastplayed'], e.get('season', 0), e.get('episode', 0)))
        position = (target.get('resume') or {}).get('position', 0)
        # Resume point, or dated but unwatched (e.g. a Move to Top target) -> continue that episode
        strategy = 'in_progress' if position > 0 or not target.get('playcount') else 'completed'
    else:
        unwatched = sorted((e for e in episodes if not e.get('playcount')), key=_episode_order)
        if not unwatched:
            return None
        target, position, strategy = unwatched[0], 0, 'in_progress'

    xbmc.log(f"nICo Context: [{tag}] Derived profile: episode={target['episodeid']} "
             f"S{target.get('season', 0):02d}E{target.get('episode', 0):02d} strategy={strategy} position={position}", xbmc.LOGINFO)
    smart_cmd.persist_show_by_id(target['episodeid'], 'episode', silent=True, automated=True,
                                 position=position if strategy == 'in_progress' else None,
                                 strategy=strategy, source='derived')
    return smart_cmd.load_profile(show_id)


def _next_unwatched(show_id, after_id, season_num, tag):
    """First unwatched episode after `after_id`, else the first unwatched one (Kodi's own pick)."""
    episodes = common_actions.get_episodes(show_id, 'tvshow', extra_props=["playcount", "episode", "resume"])
    if season_num is not None:
        episodes = [e for e in episodes if e.get('season') == season_num]
    episodes.sort(key=_episode_order)
    ids = [e['episodeid'] for e in episodes]
    if after_id in ids:
        later = [e for e in episodes[ids.index(after_id) + 1:] if not e.get('playcount')]
        if later:
            return later[0]
    unwatched = [e for e in episodes if not e.get('playcount')]
    return unwatched[0] if unwatched else None


def _time_obj(seconds):
    s = int(seconds)
    return {"hours": s // 3600, "minutes": s % 3600 // 60, "seconds": s % 60, "milliseconds": int((seconds - s) * 1000)}


def _clock(seconds):
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_VIDEO_PLAYLIST = 1


def _queue_rest_of_show(show_id, episode_id, tag):
    """Append every episode after episode_id to the video playlist, once episode_id is playing.

    Player.Open with a playlist ignores the resume time, so the episode is opened on its own
    (resume honored); Kodi's playlist then holds only that episode. Appending the later episodes
    gives "play next video automatically" something to advance to.
    """
    episodes = common_actions.get_episodes(show_id, 'tvshow', extra_props=["episode"])
    episodes.sort(key=_episode_order)
    ids = [e['episodeid'] for e in episodes]
    if episode_id not in ids:
        return
    later = ids[ids.index(episode_id) + 1:]
    if not later:
        return
    current = common_actions.execute_rpc("Playlist.GetItems", {"playlistid": _VIDEO_PLAYLIST})
    items = current.get('result', {}).get('items', [])
    xbmc.log(f"nICo Context: [{tag}] Playlist before append: {len(items)} item(s) {items}", xbmc.LOGINFO)
    if len(items) != 1:
        xbmc.log(f"nICo Context: [{tag}] Playlist is not just the playing episode — not appending", xbmc.LOGWARNING)
        return
    res = common_actions.execute_rpc("Playlist.Add", {"playlistid": _VIDEO_PLAYLIST,
                                                      "item": [{"episodeid": i} for i in later]})
    xbmc.log(f"nICo Context: [{tag}] Playlist.Add {len(later)} episodes after {episode_id} -> {res}", xbmc.LOGINFO)


def _play_at(show_id, episode_id, start, tag, show_title, detail):
    """Open the episode at `start` seconds. Logs everything so the behavior can be verified in kodi.log."""
    item = {"episodeid": episode_id}
    res = common_actions.execute_rpc("Player.Open", {"item": item, "options": {"resume": _time_obj(start)}})
    xbmc.log(f"nICo Context: [{tag}] Player.Open {item} start={start:.1f}s -> {res}", xbmc.LOGINFO)
    if res.get('result') != 'OK':
        res = common_actions.execute_rpc("Player.Open", {"item": {"episodeid": episode_id}})
        xbmc.log(f"nICo Context: [{tag}] Player.Open without resume (fallback) -> {res}", xbmc.LOGINFO)
        if res.get('result') != 'OK':
            return

    # Verify the actual start position; seek if Kodi ignored the resume time
    player = xbmc.Player()
    monitor = xbmc.Monitor()
    actual = None
    for _ in range(100):  # up to 10s
        try:
            if player.isPlayingVideo() and player.getTime() > 0:
                actual = player.getTime()
                break
        except Exception:
            pass
        if monitor.waitForAbort(0.1):
            return
    if actual is None:
        xbmc.log(f"nICo Context: [{tag}] Playback did not start within 10s", xbmc.LOGWARNING)
        return
    xbmc.log(f"nICo Context: [{tag}] Playback started at {actual:.1f}s (wanted {start:.1f}s)", xbmc.LOGINFO)
    if abs(actual - start) > 10:
        player.seekTime(start)
        xbmc.log(f"nICo Context: [{tag}] Resume time not honored — seekTime({start:.1f}) fallback", xbmc.LOGINFO)
    try:
        _queue_rest_of_show(show_id, episode_id, tag)
    except Exception as e:
        xbmc.log(f"nICo Context: [{tag}] Could not queue the rest of the show: {e}", xbmc.LOGWARNING)
    common_locks.notification(show_title, f"Smart resume{common_locks.DOT_SPC}{detail}",
                              xbmcgui.NOTIFICATION_INFO, 2500)


def smart_play():
    if xbmc.Player().isPlayingVideo():
        # A video is playing (or paused): the key keeps its normal meaning
        return _default_play("SMART_PLAY", "video already playing")
    dbid, dbtype = common_actions.get_target_info()
    if dbtype not in ('tvshow', 'season') or not dbid or dbid == "-1":
        # Not a show/season: regular play, unchanged
        xbmc.executebuiltin(f'Action({_FALLBACK})')
        return

    season_num = None
    if dbtype == 'tvshow':
        show_id = int(dbid)
    else:
        res = common_actions.execute_rpc("VideoLibrary.GetSeasonDetails", {"seasonid": int(dbid), "properties": ["tvshowid", "season"]})
        s_details = res.get('result', {}).get('seasondetails', {})
        show_id, season_num = s_details.get('tvshowid'), s_details.get('season')
    show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Label')
    tag = f"SMART_PLAY:{show_title}"
    xbmc.log(f"nICo Context: [{tag}] RAW dbid='{dbid}' dbtype='{dbtype}' show_id={show_id} season={season_num}", xbmc.LOGINFO)
    if not show_id:
        return _default_play(tag, "show not resolved")

    profile = smart_cmd.load_profile(show_id)
    if profile is None:
        xbmc.log(f"nICo Context: [{tag}] No profile — deriving from library", xbmc.LOGINFO)
        profile = _derive_profile(show_id, tag)

    resume = (profile or {}).get('status', {}).get('resume') or {}
    strategy, episode_id = resume.get('strategy'), resume.get('episode_id')
    if strategy == 'completed':
        nxt = _next_unwatched(show_id, episode_id, season_num, tag)
        if not nxt:
            return _default_play(tag, "completed, nothing unwatched")
        position = (nxt.get('resume') or {}).get('position', 0)
        start = max(0.0, position - _REWIND_SECONDS) if position > 0 else 0.0
        xbmc.log(f"nICo Context: [{tag}] Completed — next unwatched episode={nxt['episodeid']} start={start:.1f}s", xbmc.LOGINFO)
        detail = f"S{nxt.get('season', 0):02d}E{nxt.get('episode', 0):02d} (next)"
        return _play_at(show_id, nxt['episodeid'], start, tag, show_title, detail)
    if strategy not in ('in_progress', 'manual_save') or not episode_id:
        return _default_play(tag, f"strategy={strategy}")

    res = common_actions.execute_rpc("VideoLibrary.GetEpisodeDetails", {"episodeid": int(episode_id), "properties": ["tvshowid", "season", "episode"]})
    ep = res.get('result', {}).get('episodedetails')
    if not ep or ep.get('tvshowid') != show_id:
        return _default_play(tag, f"saved episode {episode_id} not in library")
    if season_num is not None and ep.get('season') != season_num:
        return _default_play(tag, f"saved episode is in season {ep.get('season')}, not {season_num}")

    start = max(0.0, float(resume.get('position', 0)) - _REWIND_SECONDS)
    detail = f"S{ep.get('season', 0):02d}E{ep.get('episode', 0):02d} at {_clock(start)}"
    if profile.get('status', {}).get('source') == 'derived':
        detail += " (from Kodi)"  # profile built from Kodi's watch history, not saved by the addon
    _play_at(show_id, int(episode_id), start, tag, show_title, detail)


if __name__ == '__main__':
    xbmc.log("nICo Context: Triggering Smart Play", xbmc.LOGINFO)
    smart_play()

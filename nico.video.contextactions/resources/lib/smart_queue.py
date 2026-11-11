import threading
import xbmc
import common_actions

_VIDEO_PLAYLIST = 1
_VIDEO_PLAYER = 1
_lock = threading.Lock()  # one queue sync at a time (consecutive episode starts)


def episode_order(e):
    """Season then episode, specials (season 0) last."""
    return (e.get('season', 0) == 0, e.get('season', 0), e.get('episode', 0))


def wanted_tail(show_id, episode_id):
    """Ids of the episodes that should follow episode_id in the queue, in play order.

    After a regular episode: the later unwatched regular episodes (specials, season 0, are never queued).
    After a special: the later unwatched specials, then the unwatched regular episodes.
    Returns None when episode_id is not an episode of the show.
    """
    episodes = common_actions.get_episodes(show_id, 'tvshow', extra_props=["episode", "playcount"])
    episodes.sort(key=episode_order)
    ids = [e['episodeid'] for e in episodes]
    if episode_id not in ids:
        return None
    anchor = episodes[ids.index(episode_id)]
    specials = [e for e in episodes if e.get('season', 0) == 0]
    regular = [e for e in episodes if e.get('season', 0) != 0]
    if anchor.get('season', 0) == 0:
        s_ids = [e['episodeid'] for e in specials]
        candidates = specials[s_ids.index(episode_id) + 1:] + regular
    else:
        r_ids = [e['episodeid'] for e in regular]
        candidates = regular[r_ids.index(episode_id) + 1:]
    # Unwatched episodes only: already watched ones are skipped by autoplay
    return [e['episodeid'] for e in candidates if not e.get('playcount')]


def sync_queue(show_id, episode_id, tag="QUEUE"):
    """Make the video playlist after the playing episode match wanted_tail, so "Play next video automatically"
    moves on the same way whatever started the episode (Smart Play, Enter in the library, ...).

    Left alone when the playlist is shuffled, or holds anything but episodes of this show (a deliberate queue).
    Idempotent: nothing is touched when the playlist already matches; otherwise only the part after the first
    difference is replaced.
    """
    with _lock:
        wanted = wanted_tail(show_id, episode_id)
        if wanted is None:
            return
        res = common_actions.execute_rpc("Player.GetProperties", {"playerid": _VIDEO_PLAYER,
                                                                  "properties": ["position", "shuffled"]})
        props = res.get('result') or {}
        position = props.get('position')
        if position is None or position < 0:
            xbmc.log(f"nICo Service: [{tag}] No playing position ({res}) — queue not synced", xbmc.LOGINFO)
            return
        if props.get('shuffled'):
            xbmc.log(f"nICo Service: [{tag}] Playlist is shuffled — queue not synced", xbmc.LOGINFO)
            return
        res = common_actions.execute_rpc("Playlist.GetItems", {"playlistid": _VIDEO_PLAYLIST,
                                                               "properties": ["tvshowid"]})
        items = res.get('result', {}).get('items', [])
        if position >= len(items) or items[position].get('id') != episode_id:
            xbmc.log(f"nICo Service: [{tag}] Playing episode {episode_id} is not at playlist position {position} "
                     f"— queue not synced", xbmc.LOGINFO)
            return
        if any(i.get('type') != 'episode' or i.get('tvshowid') != show_id for i in items):
            xbmc.log(f"nICo Service: [{tag}] Playlist holds other items {items} — queue not synced", xbmc.LOGINFO)
            return
        tail = [i['id'] for i in items[position + 1:]]
        if tail == wanted:
            xbmc.log(f"nICo Service: [{tag}] Queue after episode {episode_id} already as wanted "
                     f"({len(wanted)} episodes)", xbmc.LOGINFO)
            return
        keep = 0  # length of the common start of both lists
        while keep < len(tail) and keep < len(wanted) and tail[keep] == wanted[keep]:
            keep += 1
        for _ in range(len(tail) - keep):
            res = common_actions.execute_rpc("Playlist.Remove", {"playlistid": _VIDEO_PLAYLIST,
                                                                 "position": position + 1 + keep})
            if res.get('result') != 'OK':
                xbmc.log(f"nICo Service: [{tag}] Playlist.Remove failed -> {res} — queue left as is", xbmc.LOGWARNING)
                return
        if wanted[keep:]:
            res = common_actions.execute_rpc("Playlist.Add", {"playlistid": _VIDEO_PLAYLIST,
                                                              "item": [{"episodeid": i} for i in wanted[keep:]]})
            if res.get('result') != 'OK':
                xbmc.log(f"nICo Service: [{tag}] Playlist.Add failed -> {res}", xbmc.LOGWARNING)
                return
        xbmc.log(f"nICo Service: [{tag}] Queue after episode {episode_id}: kept {keep}, removed {len(tail) - keep}, "
                 f"added {len(wanted) - keep}", xbmc.LOGINFO)

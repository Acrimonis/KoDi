import re
import time
import xbmc
import smart_cmd

# videodb://tvshows/titles/<showid>/            -> season list of a show
# videodb://tvshows/titles/<showid>/<season>/   -> episode list of a season
_PATH_RE = re.compile(r'^videodb://tvshows/titles/(\d+)/(?:(-?\d+)/)?(?:\?.*)?$')
# Standard Kodi view container IDs (Estuary, Amber, ...): the visible one is the active view
_VIEW_IDS = (50, 51, 52, 53, 54, 55, 56, 57, 58, 501, 502, 511, 551, 600)
_LOAD_TIMEOUT = 8  # seconds to wait for the list to load


def _is_back(prev, path):
    """True when `path` is the parent of `prev`: Kodi restores the cursor itself on the way back."""
    if not prev:
        return False
    # Kodi appends a query (?xsp=…, ?tvshowid=…) to the folder path: compare the paths without it
    prev, path = prev.split('?', 1)[0], path.split('?', 1)[0]
    return prev != path and prev.startswith(path)


class FocusNavigator:
    """Moves the cursor to the saved season / episode when a show or season list is entered.

    Called every 0.1s by the service loop. Nothing is played, only the focus moves.
    """

    def __init__(self):
        self._seen = None      # last Container.FolderPath seen in the Videos window
        self._away = False     # Videos window left since the last tick in it
        self._played = False   # a video played while away (Kodi restores the folder itself on return)
        self._pending = None   # (path, show_id, is_episode_list) waiting for its list to load
        self._deadline = 0
        self._why = ''         # last reason the pending list was not ready (logged on timeout)

    def tick(self):
        if not xbmc.getCondVisibility('Window.IsActive(videos)'):
            self._away = True
            self._played = self._played or xbmc.getCondVisibility('Player.HasVideo')
            return
        if self._away:
            if not self._played:
                self._seen = None  # came back from elsewhere (Home, ...): treat as a fresh entry
            self._away = self._played = False
        path = xbmc.getInfoLabel('Container.FolderPath')
        if not path:
            return
        if path != self._seen:
            prev, self._seen = self._seen, path
            self._pending = None
            m = _PATH_RE.match(path)
            if m and not _is_back(prev, path):
                self._pending = (path, int(m.group(1)), m.group(2) is not None)
                self._deadline = time.monotonic() + _LOAD_TIMEOUT
                self._why = 'list not loaded'
                xbmc.log(f"nICo Service: [NAV:{m.group(1)}] entered {'episode' if m.group(2) is not None else 'season'} list "
                         f"{path.split('?', 1)[0]}", xbmc.LOGINFO)
            elif m:
                xbmc.log(f"nICo Service: [NAV:{m.group(1)}] back to {path.split('?', 1)[0]} — left to Kodi", xbmc.LOGINFO)
        if self._pending:
            try:
                self._try_focus()
            except Exception as e:
                xbmc.log(f"nICo Service: [NAV] failed: {e}", xbmc.LOGERROR)
                self._pending = None

    def _try_focus(self):
        path, show_id, is_episode_list = self._pending
        if time.monotonic() > self._deadline:
            self._pending = None
            xbmc.log(f"nICo Service: [NAV:{show_id}] gave up after {_LOAD_TIMEOUT}s: {self._why}", xbmc.LOGINFO)
            return
        if xbmc.getInfoLabel('Container.FolderPath') != path:
            self._why = 'folder changed'
            return
        if xbmc.getCondVisibility('Container.IsUpdating'):
            self._why = 'container still updating'
            return
        view = next((v for v in _VIEW_IDS if xbmc.getCondVisibility(f'Control.IsVisible({v})')), None)
        if view is None:
            self._why = 'no visible view container among the standard IDs'
            return
        count = int(xbmc.getInfoLabel(f'Container({view}).NumItems') or 0)
        if count == 0:
            self._why = f'view {view} has no items'
            return
        self._pending = None
        profile = smart_cmd.load_profile(show_id)
        if profile is None:
            xbmc.log(f"nICo Service: [NAV:{show_id}] no profile — nothing to select", xbmc.LOGINFO)
            return
        index = self._find(view, count, show_id, profile, is_episode_list)
        if index is None:
            resume = (profile.get('status') or {}).get('resume') or {}
            xbmc.log(f"nICo Service: [NAV:{show_id}] nothing to select in {count} items (view {view}); "
                     f"profile strategy={resume.get('strategy')} season={resume.get('season_num')} "
                     f"episode_id={resume.get('episode_id')}", xbmc.LOGINFO)
            return
        xbmc.executebuiltin(f'SetFocus({view},{index},absolute)')
        xbmc.log(f"nICo Service: [NAV:{show_id}] {path} -> item {index} (view {view})", xbmc.LOGINFO)

    def _find(self, view, count, show_id, profile, is_episode_list):
        """Index of the item to select in the list, or None."""
        import smart_play  # lazy: keeps the service alive if it ever fails to import
        resume = profile.get('status', {}).get('resume') or {}
        strategy, episode_id = resume.get('strategy'), resume.get('episode_id')
        tag = f"NAV:{show_id}"

        def label(i, name):
            return xbmc.getInfoLabel(f'Container({view}).ListItemAbsolute({i}).{name}')

        if strategy not in ('in_progress', 'manual_save', 'completed') or not episode_id:
            return None
        if is_episode_list:
            if strategy == 'completed':
                try:
                    list_season = int(label(0, 'Season'))
                except ValueError:
                    return None
                nxt = smart_play.next_unwatched(show_id, episode_id, list_season, tag)
                if not nxt:
                    return None
                episode_id = nxt['episodeid']
            return next((i for i in range(count) if label(i, 'DBID') == str(episode_id)), None)

        season = resume.get('season_num')
        if strategy == 'completed':
            nxt = smart_play.next_unwatched(show_id, episode_id, None, tag)
            season = nxt.get('season') if nxt else None
        if season is None:
            return None
        return next((i for i in range(count) if label(i, 'Season') == str(season)), None)

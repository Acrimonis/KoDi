import xbmc
import xbmcgui
import sys
import os
import time
import threading

# Ensure resources/lib is in the path for imports
sys.path.append(os.path.dirname(__file__))
import common_actions
import common_locks
import smart_cmd
import nav_focus

_LOOP_SECONDS = 0.1  # service loop period (library navigation reacts at this rate)
_PLAYER_TICK_EVERY = 10  # player position sampled every 10 loops = 1s
_AUTOPLAY_WINDOW = 10  # an episode starting within this many seconds of another one's end is an autoplay
_OFFER_MIN_POSITION = 30  # offer to resume only from a saved position of at least this many seconds
_TICK_SECONDS = 30  # periodic profile write while an episode plays
_COMPLETED_RATIO = 0.92  # position >= 92% of duration counts as completed (Kodi's default watched threshold)


class nICoPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._ended_id = None   # episode that last ended, and when (survives _reset)
        self._ended_at = 0
        self._reset()

    def _reset(self):
        self._active_id = None
        self._position = None       # last sampled player position (s), in memory only
        self._duration = None
        self._written_position = None
        self._next_write = 0

    def onPlayBackStarted(self):
        # Previous episode got no Stopped/Ended (playlist advance, Player.Open over it): save it now
        if self._active_id:
            self._persist("Switched", 'in_progress', silent=True)
        # Allow metadata to populate
        xbmc.sleep(500)
        self._reset()
        tag = self.getVideoInfoTag()
        dbid, media_type = tag.getDbId(), tag.getMediaType()
        # Profiles are per show: only library episodes are tracked
        if media_type != 'episode' or not dbid or dbid == -1:
            return
        self._active_id = dbid
        self._next_write = time.time() + _TICK_SECONDS
        xbmc.log(f"nICo Service: Tracking playback for episode (ID: {dbid})", xbmc.LOGINFO)
        autoplay = self._ended_id not in (None, dbid) and time.time() - self._ended_at < _AUTOPLAY_WINDOW
        try:
            # Show has no profile yet: create it now (silent, library resume point) so a crash still leaves one
            smart_cmd.persist_show_by_id(dbid, 'episode', silent=True, automated=True,
                                         create_only=True, strategy='in_progress')
        except Exception as e:
            xbmc.log(f"nICo Service: Start persist failed: {e}", xbmc.LOGERROR)
        if autoplay:
            threading.Thread(target=self._offer_resume, args=(dbid,), daemon=True).start()

    def onPlayBackStopped(self):
        if self._active_id:
            self._persist("Stopped", 'in_progress', silent=False)
        self._reset()

    def onPlayBackEnded(self):
        if self._active_id:
            self._ended_id, self._ended_at = self._active_id, time.time()
            self._persist("Ended", 'completed', silent=False)
        self._reset()

    def tick(self):
        """Called every second by the service loop: sample the position, write every _TICK_SECONDS."""
        if not self._active_id or not self.isPlayingVideo():
            return
        try:
            self._position = self.getTime()
            self._duration = self.getTotalTime()
        except Exception:
            return
        if time.time() < self._next_write:
            return
        self._next_write = time.time() + _TICK_SECONDS
        if xbmc.getCondVisibility('Player.Paused') or self._position == self._written_position:
            return
        self._persist("Tick", 'in_progress', silent=True, durable=False)

    def on_exit(self):
        """Kodi is quitting: Stopped is not delivered, so save the last sample (best-effort)."""
        if self._active_id:
            self._persist("Exit", 'in_progress', silent=True)
        self._reset()

    def _saved_position(self, episode_id):
        """Where the user left this episode: profile (current status, then history), else Kodi's resume point."""
        res = common_actions.execute_rpc("VideoLibrary.GetEpisodeDetails", {
            "episodeid": int(episode_id), "properties": ["tvshowid", "season", "episode", "resume"]})
        ep = res.get('result', {}).get('episodedetails')
        if not ep:
            return 0, None
        library = (ep.get('resume') or {}).get('position', 0)
        saved = None
        profile = smart_cmd.load_profile(ep.get('tvshowid'))
        if profile:
            for status in [profile.get('status') or {}] + (profile.get('history') or []):
                resume = status.get('resume') or {}
                if resume.get('episode_id') == int(episode_id):  # newest entry for this episode wins
                    saved = resume.get('position', 0) if resume.get('strategy') in ('in_progress', 'manual_save') else 0
                    break
        if saved is None:
            saved = library
        elif saved > smart_cmd.min_resume_seconds() and not library:
            saved = 0  # Kodi's resume point was cleared (reset): nothing to offer
        return saved, ep

    def _offer_resume(self, episode_id):
        """Autoplay moved on to an episode that was left part-way: ask whether to resume there."""
        try:
            position, ep = self._saved_position(episode_id)
            if position < _OFFER_MIN_POSITION:
                xbmc.log(f"nICo Service: Autoplay reached episode {episode_id}: saved position {position:.1f}s "
                         f"< {_OFFER_MIN_POSITION}s — no offer", xbmc.LOGINFO)
                return
            if not self._playing_episode(episode_id):
                return
            if not xbmc.getCondVisibility('Player.Paused'):
                self.pause()
            h, m, sec = int(position) // 3600, int(position) % 3600 // 60, int(position) % 60
            clock = f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
            title = common_actions._fetch_show_title(ep.get('tvshowid'), fallback="Resume?")
            xbmc.log(f"nICo Service: Autoplay reached episode {episode_id} with saved position {position:.1f}s — asking", xbmc.LOGINFO)
            # Same shape as Kodi's own resume prompt; the first entry uses Kodi's string (follows the UI language)
            resume_label = xbmc.getLocalizedString(12022)
            resume_label = resume_label.replace('%s', clock) if '%s' in resume_label else f"{resume_label or 'Resume from'} {clock}"
            begin_label = "Restart"
            try:
                percent = f" ({position / self.getTotalTime() * 100:.0f}%)"
            except Exception:
                percent = ""
            # The context menu has no heading: show the episode info as a toast while it is open
            common_locks.notification(title, f"S{ep.get('season', 0):02d}E{ep.get('episode', 0):02d}{common_locks.DOT_SPC}"
                                      f"left at {clock}{percent}", xbmcgui.NOTIFICATION_INFO, 6000)
            choice = xbmcgui.Dialog().contextmenu([resume_label, begin_label])
            resume = choice != 1  # default (first entry) and a cancelled menu both resume
            xbmc.log(f"nICo Service: Autoplay prompt answer: {'resume' if resume else 'beginning'} (choice={choice})", xbmc.LOGINFO)
            if self._playing_episode(episode_id):
                if resume:
                    self.seekTime(position)
                if xbmc.getCondVisibility('Player.Paused'):
                    self.pause()
        except Exception as e:
            xbmc.log(f"nICo Service: Autoplay resume offer failed: {e}", xbmc.LOGERROR)

    def _playing_episode(self, episode_id):
        try:
            return self.isPlayingVideo() and self.getVideoInfoTag().getDbId() == int(episode_id)
        except Exception:
            return False

    def _persist(self, event, strategy, silent, durable=True):
        if (strategy == 'in_progress' and self._position is not None and self._duration
                and self._position >= self._duration * _COMPLETED_RATIO):
            strategy = 'completed'
        # completed: no position, persist_show_by_id uses the full duration
        position = self._position if strategy == 'in_progress' else None
        quiet = event == "Tick"
        xbmc.log(f"nICo Service: Playback {event} — updating profile for episode (ID: {self._active_id}) "
                 f"strategy={strategy} position={position} duration={self._duration}",
                 xbmc.LOGDEBUG if quiet else xbmc.LOGINFO)
        try:
            smart_cmd.persist_show_by_id(self._active_id, 'episode', silent=silent, automated=True,
                                         position=position, duration=self._duration,
                                         strategy=strategy, durable=durable, quiet=quiet)
            self._written_position = position
        except Exception as e:
            xbmc.log(f"nICo Service: Background persist failed for {event}: {e}", xbmc.LOGERROR)


class nICoService(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.player = nICoPlayer()
        self.navigator = nav_focus.FocusNavigator()

if __name__ == '__main__':
    xbmc.log("nICo Service: Background playback monitor started", xbmc.LOGINFO)
    monitor = nICoService()
    loops = 0
    while not monitor.waitForAbort(_LOOP_SECONDS):
        monitor.navigator.tick()
        loops += 1
        if loops % _PLAYER_TICK_EVERY == 0:
            monitor.player.tick()
    monitor.player.on_exit()

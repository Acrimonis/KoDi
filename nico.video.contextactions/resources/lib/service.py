import xbmc
import sys
import os
import time

# Ensure resources/lib is in the path for imports
sys.path.append(os.path.dirname(__file__))
import smart_cmd
import nav_focus

_LOOP_SECONDS = 0.1  # service loop period (library navigation reacts at this rate)
_PLAYER_TICK_EVERY = 10  # player position sampled every 10 loops = 1s
_TICK_SECONDS = 30  # periodic profile write while an episode plays
_COMPLETED_RATIO = 0.92  # position >= 92% of duration counts as completed (Kodi's default watched threshold)


class nICoPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
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
        try:
            # Show has no profile yet: create it now (silent, library resume point) so a crash still leaves one
            smart_cmd.persist_show_by_id(dbid, 'episode', silent=True, automated=True,
                                         create_only=True, strategy='in_progress')
        except Exception as e:
            xbmc.log(f"nICo Service: Start persist failed: {e}", xbmc.LOGERROR)

    def onPlayBackStopped(self):
        if self._active_id:
            self._persist("Stopped", 'in_progress', silent=False)
        self._reset()

    def onPlayBackEnded(self):
        if self._active_id:
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

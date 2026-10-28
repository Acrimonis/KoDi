import xbmc
import sys
import os

# Ensure resources/lib is in the path for imports
sys.path.append(os.path.dirname(__file__))
import smart_cmd

class nICoPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._active_id = None
        self._active_type = None

    def onPlayBackStarted(self):
        # Allow metadata to populate
        xbmc.sleep(500)
        tag = self.getVideoInfoTag()
        self._active_id = tag.getDbId()
        self._active_type = tag.getMediaType()
        
        if self._active_id and self._active_id != -1:
            xbmc.log(f"nICo Service: Tracking playback for {self._active_type} (ID: {self._active_id})", xbmc.LOGDEBUG)

    def onPlayBackStopped(self):
        self._trigger_persist("Stopped")

    def onPlayBackEnded(self):
        self._trigger_persist("Ended")

    def _trigger_persist(self, event):
        if self._active_id and self._active_id != -1 and self._active_type:
            xbmc.log(f"nICo Service: Playback {event} detected. Updating profile for {self._active_type} (ID: {self._active_id})...", xbmc.LOGINFO)
            try:
                # Call with silent=False per request, and automated=True for strategy logic
                smart_cmd.persist_show_by_id(self._active_id, self._active_type, silent=False, automated=True)
            except Exception as e:
                xbmc.log(f"nICo Service: Background persist failed for {event}: {e}", xbmc.LOGERROR)
        
        # Reset state for next playback
        self._active_id = None
        self._active_type = None

class nICoService(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.player = nICoPlayer()

if __name__ == '__main__':
    xbmc.log("nICo Service: Background playback monitor started", xbmc.LOGINFO)
    monitor = nICoService()
    while not monitor.waitForAbort(10):
        pass
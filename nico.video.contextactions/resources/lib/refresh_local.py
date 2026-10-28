import xbmc
import common_locks
import common_actions

if __name__ == '__main__':
    common_locks._log_thread_info("REFRESH")
    common_locks.cleanup_stale_locks()
    xbmc.log("nICo Context: Triggering Local Refresh", xbmc.LOGINFO)
    common_actions.refresh()

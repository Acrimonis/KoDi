"""Per-show file locks for Kodi context menu actions.

Kodi runs each plugin call as a thread (sub-interpreter) within the same process.
Lock files are named {root_id}_{tid}.lock using the OS thread ID.
Liveness is checked via Win32 OpenThread (threads, not processes, are the unit here).

On acquire: stale locks (dead threads) are cleaned up automatically.
On startup: call cleanup_stale_locks() to sweep any leftovers from crashes.
"""
import ctypes, ctypes.util, json, os, random, sys, threading, time, importlib, xbmc, xbmcgui, xbmcvfs


DOT = "\u2022"
DOT_SPC = " \u2022 "

_LOCK_DIR = None
_notif_suppress_until_ms = 0  # suppress queue status notifications until this timestamp

def reload_modules():
    """Force reload all modules belonging to this addon for development."""
    # Determine the base directory of the addon
    # Normalize path and case for reliable comparison on Windows (C: vs c:)
    addon_base_dir = os.path.normcase(os.path.normpath(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))))
    xbmc.log(f"nICo Context: Reloading modules from addon base directory: {addon_base_dir}", xbmc.LOGINFO)

    reloaded_count = 0
    for name, module in list(sys.modules.items()):
        # Skip __main__ as it's the currently executing script and cannot be reloaded this way
        if name == '__main__':
            continue
        # Check if the module has a __file__ attribute and if it's within the addon's base directory
        if hasattr(module, '__file__') and module.__file__:
            module_path = os.path.normcase(os.path.normpath(os.path.abspath(module.__file__)))
            # Check if module resides in the addon folder. We omit the '.py' check to catch .pyc files.
            if module_path.startswith(addon_base_dir):
                try:
                    importlib.reload(module)
                    xbmc.log(f"nICo Context: Reloaded module {name}", xbmc.LOGINFO)
                    reloaded_count += 1
                except Exception as e:
                    xbmc.log(f"nICo Context: Failed to reload module {name} ({module_path}): {e}", xbmc.LOGERROR)
    xbmc.log(f"nICo Context: Total {reloaded_count} modules reloaded.", xbmc.LOGINFO)
    notification("nICo Dev PlugiN", f"{reloaded_count} modules reloaded", xbmcgui.NOTIFICATION_INFO, 1000)


def suppress_queue_notification(duration_ms):
    """Call after showing a completion notification to delay the next status notification."""
    global _notif_suppress_until_ms
    _notif_suppress_until_ms = _ms() + duration_ms


def notification(heading, message, icon=xbmcgui.NOTIFICATION_INFO, time=3000, sound=True):
    """Show a notification and set the global suppression timer to its duration."""
    xbmcgui.Dialog().notification(heading, message, icon, time, sound)
    suppress_queue_notification(time)


def notificationStatus(heading, message, icon="", time=3000, sound=False):
    """Wait for suppression to expire, then show with remaining time (skip if expired).
    Uses [COLOR grey] tags to ensure a subdued look in skins like Amber,
    and defaults sound to False for background status updates."""
    now = _ms()
    if now < _notif_suppress_until_ms:
        wait_ms = _notif_suppress_until_ms - now
        if wait_ms >= time:
            return
        xbmc.sleep(wait_ms)
        time -= wait_ms

    # Force subdued color using Kodi label formatting
    h = f"[COLOR grey]{heading}[/COLOR]"
    m = f"[COLOR grey]{message}[/COLOR]"
    xbmcgui.Dialog().notification(h, m, icon, time, sound)


def _ms():
    return int(time.time() * 1000)


def _lock_dir():
    global _LOCK_DIR
    if _LOCK_DIR is None:
        _LOCK_DIR = xbmcvfs.translatePath('special://temp/nico.locks/')
        if not xbmcvfs.exists(_LOCK_DIR):
            xbmcvfs.mkdirs(_LOCK_DIR)
    return _LOCK_DIR


def _thread_alive(tid):
    """Return True if the OS thread with this ID is still running."""
    if sys.platform == 'win32':
        THREAD_QUERY_LIMITED_INFORMATION = 0x0800
        handle = ctypes.windll.kernel32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, tid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong(0)
        ctypes.windll.kernel32.GetExitCodeThread(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE
    else:
        # On Linux/macOS threading.get_ident() returns a pthread ID.
        # pthread_kill(tid, 0) checks liveness without sending a signal.
        try:
            # ctypes.util is part of ctypes, already imported globally.
            libpthread = ctypes.CDLL(ctypes.util.find_library('pthread'), use_errno=True)
            ret = libpthread.pthread_kill(ctypes.c_ulong(tid), 0)
            return ret == 0  # 0 = alive, ESRCH (3) = no such thread
        except Exception:
            return True  # if detection fails, assume alive (safe fallback)


def _my_tid():
    return threading.get_ident()


def _log_thread_info(tag=""):
    """Log identity info to definitively determine if calls share an interpreter.

    Key diagnostic: if id(sys.modules) is the same across two concurrent calls,
    they share a Python interpreter and global variables — a simple dict flag works.
    If different, they are sub-interpreters with isolated globals — OS calls needed.
    """
    import sys
    xbmc.log(
        f"nICo Context: [{tag}] identity — pid={os.getpid()} tid={_my_tid()} "
        f"id(sys.modules)={id(sys.modules)} id(threading)={id(threading)}",
        xbmc.LOGINFO
    )


def _parse_lock_fname(fname):
    """Parse '{root_id}_{tid}.lock' -> (root_id_str, tid) or None."""
    name = fname[:-5]  # strip .lock
    parts = name.rsplit('_', 1)
    if len(parts) != 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


def _snap_path(root_id):
    """Path to the shared per-show snapshot file (lives alongside lock files)."""
    return os.path.join(_lock_dir(), f"{root_id}.snap.json")


def _write_lock_status(lock_path, status, queue_ts=None):
    """Write status and optional queue timestamp into the lock file."""
    try:
        with open(lock_path, 'w') as f:
            f.write(f"{status}\n{queue_ts}" if queue_ts is not None else status)
    except Exception:
        pass


def _read_lock(lock_path):
    """Return (status, queue_ts) from a lock file. queue_ts is float or None."""
    try:
        with open(lock_path) as f:
            lines = f.read().strip().split('\n', 1)
        status = lines[0]
        queue_ts = float(lines[1]) if len(lines) > 1 else None
        return status, queue_ts
    except Exception:
        return 'held', None


def _show_queue_notification():
    """Scan all lock files and show a notification summarising running and queued actions.

    Lock file content is 'held' (action running), 'queued' (waiting), or 'inet' (internet fetch).
    Groups by show (root_id) to produce:
      "2 running on 2 shows, 1 internet fetch on 1 show, 3 queued on 2 shows"
    """
    # xbmc.log(f"nICo Context: [notif] 0 In...", xbmc.LOGINFO)

    d = _lock_dir()
    held_shows = set()
    queued_shows = set()
    inet_shows = set()
    held_count = 0
    queued_count = 0
    inet_count = 0
    my_tid = _my_tid()
    try:
        for fname in os.listdir(d):
            if not fname.endswith('.lock'):
                continue
            parsed = _parse_lock_fname(fname)
            if parsed is None:
                continue

            # xbmc.log(f"nICo Context: [notif] 1 parsed: {parsed}", xbmc.LOGINFO)

            root_id, tid = parsed
            # Skip liveness check for ourselves; if we are running this code, we are alive.
            if tid != my_tid and not _thread_alive(tid):
                continue
            status, _ = _read_lock(os.path.join(d, fname))

            # xbmc.log(f"nICo Context: [notif] 2 status: {status}", xbmc.LOGINFO)

            if status == 'queued':
                queued_count += 1
                queued_shows.add(root_id)
            elif status == 'inet':
                inet_count += 1
                inet_shows.add(root_id)
            else:
                held_count += 1
                held_shows.add(root_id)

            # xbmc.log(f"nICo Context: [notif] 3 queued_count: {queued_count}, inet_count: {inet_count}, held_count: {held_count}", xbmc.LOGINFO)

    except Exception:
        xbmc.log(f"nICo Context: [notif] X Exception: {sys.exc_info()}", xbmc.LOGINFO)
        return

    if held_count == 0 and queued_count == 0 and inet_count == 0:
        return

    parts = []
    if held_count:
        s = 's' if len(held_shows) > 1 else ''
        parts.append(f"{held_count} running on {len(held_shows)} show{s}")
    if inet_count:
        s = 's' if len(inet_shows) > 1 else ''
        parts.append(f"{inet_count} internet fetch on {len(inet_shows)} show{s}")
    if queued_count:
        s = 's' if len(queued_shows) > 1 else ''
        parts.append(f"{queued_count} queued on {len(queued_shows)} show{s}")


    if (parts):
        xbmc.log(f"nICo Context: [notif] Running {DOT_SPC.join(parts)}", xbmc.LOGINFO)
        notificationStatus("Running",  DOT_SPC.join(parts), "", 1000)
    else:
        xbmc.log(f"nICo Context: [notif] Running **nothing**", xbmc.LOGINFO)      


def merge_and_save_snapshot(root_id, fresh_dict, tag=""):
    """Load the shared snapshot for root_id and merge fresh_dict into it.

    Merge rules — existing entries are NEVER overwritten:
      - No snapshot on disk: create from fresh_dict (first action for this show;
        fresh_dict contains the true pre-action DB state).
      - Snapshot exists: add only idFiles not already recorded (subsequent queued
        actions inherit the truth captured before the very first action ran, even
        if a background scanner has since corrupted the DB between actions).

    Returns the canonical {idFile (int): lastPlayed (str)} dict.
    """
    path = _snap_path(root_id)
    canonical = {}

    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                raw = json.load(f)
            canonical = {int(k): v for k, v in raw.items()}  # JSON keys are always str
            new_keys = [fid for fid in fresh_dict if fid not in canonical]
            if new_keys:
                for fid in new_keys:
                    canonical[fid] = fresh_dict[fid]
                xbmc.log(
                    f"nICo Context: [{tag}] SNAPSHOT merged — root_id={root_id} "
                    f"+{len(new_keys)} new idFiles, total={len(canonical)}",
                    xbmc.LOGINFO
                )
            else:
                xbmc.log(
                    f"nICo Context: [{tag}] SNAPSHOT inherited — root_id={root_id} "
                    f"{len(canonical)} files, no new entries (all already recorded)",
                    xbmc.LOGINFO
                )
        except Exception as ex:
            xbmc.log(
                f"nICo Context: [{tag}] SNAPSHOT read error (root_id={root_id}): {ex} — using fresh snapshot",
                xbmc.LOGWARNING
            )
            canonical = dict(fresh_dict)
    else:
        canonical = dict(fresh_dict)
        xbmc.log(
            f"nICo Context: [{tag}] SNAPSHOT created — root_id={root_id} {len(canonical)} files "
            f"(first action for this show; truth captured)",
            xbmc.LOGINFO
        )

    try:
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump({str(k): v for k, v in canonical.items()}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as ex:
        xbmc.log(f"nICo Context: [{tag}] SNAPSHOT write error (root_id={root_id}): {ex}", xbmc.LOGWARNING)

    return canonical


def _delete_snapshot_if_last(root_id, tag=""):
    """Delete the snapshot file if no lock files remain for root_id.

    Called by release() after removing the lock. The last action in a serialised
    queue (no competing locks left) cleans up the shared snapshot automatically.
    """
    d = _lock_dir()
    try:
        remaining = [
            f for f in os.listdir(d)
            if f.startswith(f"{root_id}_") and f.endswith('.lock')
        ]
        path = _snap_path(root_id)
        if not remaining and os.path.exists(path):
            os.remove(path)
            xbmc.log(
                f"nICo Context: [{tag}] SNAPSHOT deleted — root_id={root_id} (last lock released, queue empty)",
                xbmc.LOGINFO
            )
        elif remaining and os.path.exists(path):
            xbmc.log(
                f"nICo Context: [{tag}] SNAPSHOT kept — root_id={root_id} "
                f"{len(remaining)} lock(s) still active: {remaining}",
                xbmc.LOGINFO
            )
    except Exception as ex:
        xbmc.log(f"nICo Context: [{tag}] SNAPSHOT cleanup error (root_id={root_id}): {ex}", xbmc.LOGWARNING)


def cleanup_stale_locks():
    """Remove lock files whose owner thread is no longer alive, and orphaned snapshots.
    Call on plugin startup to sweep leftovers from crashes or abnormal exits.
    """
    d = _lock_dir()
    try:
        # --- Pass 1: clean up stale lock files ---
        all_files = os.listdir(d)
        for fname in all_files:
            if not fname.endswith('.lock'):
                continue
            parsed = _parse_lock_fname(fname)
            if parsed is None:
                continue
            root_id, tid = parsed
            try:
                if not _thread_alive(tid):
                    os.remove(os.path.join(d, fname))
                    xbmc.log(
                        f"nICo Context: [LOCK] CLEANUP stale lock — show_key={root_id} dead_thread_key={tid} file={fname}",
                        xbmc.LOGWARNING
                    )
            except Exception as ex:
                xbmc.log(f"nICo Context: [LOCK] Could not clean {fname}: {ex}", xbmc.LOGWARNING)

        # --- Pass 2: clean up orphaned snapshot files (no corresponding lock) ---
        # Re-read dir so pass 1 deletions are reflected.
        all_files = os.listdir(d)
        active_root_ids = {
            str(parsed[0])
            for f in all_files
            if f.endswith('.lock') and (parsed := _parse_lock_fname(f)) is not None
        }
        for fname in all_files:
            if not fname.endswith('.snap.json'):
                continue
            root_id_str = fname[:-10]  # strip '.snap.json'
            if root_id_str not in active_root_ids:
                try:
                    os.remove(os.path.join(d, fname))
                    xbmc.log(
                        f"nICo Context: [LOCK] CLEANUP orphaned snapshot — root_id={root_id_str} file={fname}",
                        xbmc.LOGWARNING
                    )
                except Exception as ex:
                    xbmc.log(f"nICo Context: [LOCK] Could not clean snapshot {fname}: {ex}", xbmc.LOGWARNING)

    except Exception as ex:
        xbmc.log(f"nICo Context: [LOCK] cleanup_stale_locks error: {ex}", xbmc.LOGWARNING)


def acquire(root_id, tag="", show_name="", on_queue=None, poll_ms=100):
    """Create {root_id}_{tid}.lock, waiting if another live thread holds one.

    Lock identity:
      show_key  = root_id  — tvshowid (or movie dbid); one mutex per show
      thread_key = tid     — OS thread ID (threading.get_ident()), unique per Kodi plugin call
      lock_file = {root_id}_{tid}.lock

    on_queue: called once when a competing lock is first detected.
    Returns (lock_path, was_queued). If was_queued is True, suppress the start notification.
    """
    d = _lock_dir()
    my_tid = _my_tid()
    my_lock = os.path.join(d, f"{root_id}_{my_tid}.lock")
    name_part = f" ({show_name})" if show_name else ""
    t0 = _ms()
    was_queued = False

    xbmc.log(
        f"nICo Context: [{tag}] LOCK ACQUIRE — show_key={root_id}{name_part} "
        f"thread_key={my_tid} lock_file={os.path.basename(my_lock)}",
        xbmc.LOGINFO
    )

    last_notif_ms = 0  # throttle notifications to once per ~3s

    # Monotonic timestamp for FIFO ordering (written inside the lock file, not relying on mtime).
    my_queue_ts = None

    while True:
        competing = []
        try:
            for fname in os.listdir(d):
                if not fname.startswith(f"{root_id}_") or not fname.endswith('.lock'):
                    continue
                parsed = _parse_lock_fname(fname)
                if parsed is None:
                    continue
                _, tid = parsed
                if tid == my_tid:
                    continue  # that's me
                if not _thread_alive(tid):
                    os.remove(os.path.join(d, fname))
                    xbmc.log(
                        f"nICo Context: [{tag}] Stale lock removed — show_key={root_id} dead_thread_key={tid} file={fname}",
                        xbmc.LOGWARNING
                    )
                    continue
                # Read status to apply FIFO ordering among queued threads.
                # A 'held' lock always blocks.  A 'queued' lock only blocks if it
                # was written BEFORE ours (it has higher queue priority than us).
                status, their_queue_ts = _read_lock(os.path.join(d, fname))
                if status in ('held', 'inet'):
                    competing.append(fname)
                elif status == 'queued':
                    if my_queue_ts is None or (their_queue_ts is not None and their_queue_ts < my_queue_ts):
                        competing.append(fname)  # they queued before us → they have priority
        except Exception as ex:
            xbmc.log(f"nICo Context: [{tag}] Lock dir scan error: {ex}", xbmc.LOGWARNING)

        if not competing:
            # Mark as held in lock file so queue notification counts us correctly.
            _write_lock_status(my_lock, 'held')
            elapsed = _ms() - t0
            xbmc.log(
                f"nICo Context: [{tag}] LOCK HELD — show_key={root_id}{name_part} "
                f"thread_key={my_tid} waited={elapsed}ms",
                xbmc.LOGINFO
            )
            return my_lock, was_queued

        if not was_queued:
            # Write our lock file immediately so _delete_snapshot_if_last sees us as
            # active — if we only wrote it on win, a releasing thread would see an empty
            # dir and delete the snapshot while we're still waiting for it.
            # Mark as queued so the notification helper can distinguish running vs waiting.
            my_queue_ts = time.monotonic()
            _write_lock_status(my_lock, 'queued', queue_ts=my_queue_ts)
            blocked_tids = [_parse_lock_fname(f)[1] for f in competing if _parse_lock_fname(f)]
            xbmc.log(
                f"nICo Context: [{tag}] LOCK QUEUED — show_key={root_id}{name_part} "
                f"thread_key={my_tid} waiting_on_thread_keys={blocked_tids} files={competing}",
                xbmc.LOGWARNING
            )
            if on_queue:
                on_queue()
            was_queued = True

        # Periodic queue-status notification (every ~3s while waiting).
        now = _ms()
        if now - last_notif_ms >= 850:
            _show_queue_notification()
            last_notif_ms = now

        # Jitter prevents multiple queued threads from waking up simultaneously
        # and all passing the "no competing locks" check in the same poll cycle.
        jitter = random.randint(0, poll_ms)
        xbmc.sleep(poll_ms + jitter)


def release(lock_path, root_id, tag="", show_name=""):
    """Delete the lock file, then clean up the shared snapshot if no more actions are queued."""
    name_part = f" ({show_name})" if show_name else ""
    try:
        if lock_path and os.path.exists(lock_path):
            fname = os.path.basename(lock_path)
            tid = _parse_lock_fname(fname)[1] if _parse_lock_fname(fname) else "?"
            os.remove(lock_path)
            xbmc.log(
                f"nICo Context: [{tag}] LOCK RELEASED — show_key={root_id}{name_part} "
                f"thread_key={tid} lock_file={fname}",
                xbmc.LOGINFO
            )
    except Exception as ex:
        xbmc.log(f"nICo Context: [{tag}] Lock release error: {ex}", xbmc.LOGWARNING)
    # Always attempt snapshot cleanup — _delete_snapshot_if_last is a no-op if no snapshot exists.
    _delete_snapshot_if_last(root_id, tag=tag)


if __name__ == '__main__':
    # Ensure local path is available and modules are imported so the loop can find them
    sys.path.append(os.path.dirname(__file__))
    try:
        import common_actions, common_db, smart_cmd, watched_past, toggle_watch
    except ImportError:
        pass

    reload_modules()
    cleanup_stale_locks()

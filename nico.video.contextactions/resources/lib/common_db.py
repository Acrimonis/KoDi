import os, re, sqlite3, xbmc, xbmcvfs, typing
from contextlib import contextmanager
from typing import Generator, Optional

_CACHED_DB_KODI_PATH: Optional[str] = None


def _kodi_db_path() -> str:
    """Locate the latest MyVideos database path and cache it."""
    global _CACHED_DB_KODI_PATH
    if _CACHED_DB_KODI_PATH:
        return _CACHED_DB_KODI_PATH

    db_dir = xbmcvfs.translatePath('special://database/')
    # Highest schema version wins, compared as a number (MyVideos99.db < MyVideos131.db)
    versions = {}
    for f in os.listdir(db_dir):
        m = re.fullmatch(r'MyVideos(\d+)\.db', f)
        if m:
            versions[int(m.group(1))] = f
    if not versions:
        raise FileNotFoundError("nICo Context: Could not find any MyVideos database files in special://database/")

    _CACHED_DB_KODI_PATH = os.path.join(db_dir, versions[max(versions)])
    return _CACHED_DB_KODI_PATH


@contextmanager
def kodi_db_context(readonly: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for Kodi SQLite database connections with transaction management."""
    conn = sqlite3.connect(_kodi_db_path(), timeout=10.0)
    try:
        if readonly:
            conn.execute('BEGIN DEFERRED')
        else:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        xbmc.log(f"nICo Context SQL Error: {str(e)}", xbmc.LOGERROR)
        raise
    finally:
        conn.close()

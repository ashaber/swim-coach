"""Store factory: picks FileStore or DbStore from Settings.

The single place the backend decides which persistence backend to use. Every
route/context that needs a store calls `make_store(settings)` instead of
constructing one directly, so the file->DB cutover is one config flag
(`STORE_BACKEND`), not a code change.

Default is `file` -- the live backend is unchanged until Andrew provisions
Supabase and sets `STORE_BACKEND=db` + `DATABASE_URL`. Rollback is flipping the
flag back to `file`.
"""

from __future__ import annotations

from swim_coach.store import FileStore, StoreInterface

from app.config import ConfigError, Settings


def make_store(settings: Settings) -> StoreInterface:
    """Return the configured store. `file` -> FileStore over the athlete tree;
    `db` -> DbStore over the Supabase DSN (psycopg imported lazily inside
    DbStore -- so importing this factory never requires psycopg)."""
    if settings.store_backend == "file":
        return FileStore(base_dir=settings.athletes_dir)

    if settings.store_backend == "db":
        if not settings.database_url:
            # Belt-and-suspenders: Settings.from_env already fails fast on this,
            # but guard here too so make_store is safe called with any Settings.
            raise ConfigError("STORE_BACKEND=db requires DATABASE_URL")
        # Imported lazily so the psycopg dependency is only pulled in when the
        # db backend is actually selected (engine core stays psycopg-free).
        from swim_coach.store_db import DbStore

        return DbStore(dsn=settings.database_url)

    raise ConfigError(f"unknown STORE_BACKEND: {settings.store_backend!r}")

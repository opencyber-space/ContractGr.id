from __future__ import annotations

import os
import struct
from typing import Optional

from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


class WatcherLMDB:
    """
    Thin wrapper around keripy's LMDB infrastructure.
    Manages watcher-specific state that must be co-located with
    the Kevery for atomic read-validate-write semantics.

    This class is intentionally minimal. The heavy lifting for
    KEL storage is done by keripy's Baser. We only store:
      - first-seen digest per (aid, sn) for fast duplicity pre-check
      - escrow flags for events pending missing prior events
    """

    def __init__(self, path: str, map_size: int) -> None:
        self._path = path
        self._map_size = map_size
        self._env = None
        self._db_fse = None
        self._db_esc = None

    def open(self) -> None:
        try:
            import lmdb
        except ImportError:
            log.warning("lmdb package not installed; LMDB layer disabled")
            return

        os.makedirs(self._path, exist_ok=True)
        self._env = lmdb.open(
            self._path,
            map_size=self._map_size,
            max_dbs=8,
            writemap=True,
            metasync=False,
            sync=True,
            readahead=False,
            meminit=False,
        )
        self._db_fse = self._env.open_db(b"watcher.fse", create=True)
        self._db_esc = self._env.open_db(b"watcher.esc", create=True)
        log.info_kw("LMDB opened", path=self._path)

    def close(self) -> None:
        if self._env:
            self._env.close()
            self._env = None

    def _fse_key(self, aid: str, sn: int) -> bytes:
        sn_bytes = struct.pack(">Q", sn)
        return aid.encode() + b"." + sn_bytes

    def get_first_seen_said(self, aid: str, sn: int) -> Optional[str]:
        if not self._env:
            return None
        with self._env.begin(db=self._db_fse, write=False) as txn:
            val = txn.get(self._fse_key(aid, sn))
            return val.decode() if val else None

    def put_first_seen_said(self, aid: str, sn: int, said: str) -> bool:
        if not self._env:
            return False
        key = self._fse_key(aid, sn)
        with self._env.begin(db=self._db_fse, write=True) as txn:
            existing = txn.get(key)
            if existing:
                return False
            txn.put(key, said.encode())
            return True

    def is_first_seen(self, aid: str, sn: int, said: str) -> bool:
        existing = self.get_first_seen_said(aid, sn)
        return existing is None or existing == said

    def is_duplicate(self, aid: str, sn: int, said: str) -> bool:
        existing = self.get_first_seen_said(aid, sn)
        return existing is not None and existing != said

    def set_escrowed(self, aid: str, sn: int, said: str) -> None:
        if not self._env:
            return
        key = f"{aid}.{sn}.{said}".encode()
        with self._env.begin(db=self._db_esc, write=True) as txn:
            txn.put(key, b"1")

    def clear_escrowed(self, aid: str, sn: int, said: str) -> None:
        if not self._env:
            return
        key = f"{aid}.{sn}.{said}".encode()
        with self._env.begin(db=self._db_esc, write=True) as txn:
            txn.delete(key)

    def is_escrowed(self, aid: str, sn: int, said: str) -> bool:
        if not self._env:
            return False
        key = f"{aid}.{sn}.{said}".encode()
        with self._env.begin(db=self._db_esc, write=False) as txn:
            return txn.get(key) is not None

    def stat(self) -> dict:
        if not self._env:
            return {}
        info = self._env.info()
        stat = self._env.stat()
        return {
            "map_size": info["map_size"],
            "last_pgno": info["last_pgno"],
            "last_txnid": info["last_txnid"],
            "map_addr": info["map_addr"],
            "num_readers": info["num_readers"],
            "psize": stat["psize"],
        }
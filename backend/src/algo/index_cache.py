"""In-memory cache for precomputed spectral-index maps.

Keyed by (raster_path, index_name). Stores float32 arrays at preview
resolution plus the warp metadata (transform, crs) and per-band stats so
/render/index can apply a color ramp without recomputing.
"""

import logging
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class IndexCache:
    def __init__(self) -> None:
        self._arrays: Dict[Tuple[str, str], np.ndarray] = {}
        self._meta: Dict[Tuple[str, str], dict] = {}
        self._progress: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def has(self, path: str, name: str) -> bool:
        with self._lock:
            return (path, name) in self._arrays

    def get(self, path: str, name: str) -> Optional[Tuple[np.ndarray, dict]]:
        with self._lock:
            key = (path, name)
            arr = self._arrays.get(key)
            meta = self._meta.get(key)
            if arr is None or meta is None:
                return None
            return arr, meta

    def put(self, path: str, name: str, arr: np.ndarray, meta: dict) -> None:
        with self._lock:
            key = (path, name)
            self._arrays[key] = arr
            self._meta[key] = meta

    def clear_for(self, path: Optional[str]) -> None:
        if path is None:
            return
        with self._lock:
            for key in list(self._arrays.keys()):
                if key[0] == path:
                    self._arrays.pop(key, None)
                    self._meta.pop(key, None)
            self._progress.pop(path, None)

    def ready_names(self, path: str) -> List[str]:
        with self._lock:
            return sorted(name for (p, name) in self._arrays.keys() if p == path)

    def init_progress(self, path: str, total: int) -> None:
        with self._lock:
            self._progress[path] = {
                "path": path,
                "total": int(total),
                "done": 0,
                "in_progress": True,
                "ready": [],
                "errors": [],
            }

    def mark_done(self, path: str, name: str) -> None:
        with self._lock:
            entry = self._progress.get(path)
            if entry is None:
                return
            entry["done"] = int(entry.get("done", 0)) + 1
            ready = entry.setdefault("ready", [])
            if name not in ready:
                ready.append(name)

    def mark_error(self, path: str, name: str, message: str) -> None:
        with self._lock:
            entry = self._progress.get(path)
            if entry is None:
                return
            entry["done"] = int(entry.get("done", 0)) + 1
            entry.setdefault("errors", []).append({"name": name, "message": message})

    def finish_progress(self, path: str) -> None:
        with self._lock:
            entry = self._progress.get(path)
            if entry is None:
                return
            entry["in_progress"] = False

    def progress(self, path: Optional[str]) -> dict:
        with self._lock:
            if path is None or path not in self._progress:
                return {
                    "path": path,
                    "total": 0,
                    "done": 0,
                    "in_progress": False,
                    "ready": [],
                    "errors": [],
                }
            entry = self._progress[path]
            return {
                "path": entry.get("path"),
                "total": int(entry.get("total", 0)),
                "done": int(entry.get("done", 0)),
                "in_progress": bool(entry.get("in_progress", False)),
                "ready": list(entry.get("ready", [])),
                "errors": list(entry.get("errors", [])),
            }

"""
LRU cache for tile rendering.
Caches rendered tiles to avoid recomputation.
"""

import sys
from collections import OrderedDict
from typing import Optional, Tuple
import numpy as np
import logging

logger = logging.getLogger(__name__)


class TileCache:
    """LRU cache for rendered tiles."""

    def __init__(self, max_size_mb: int = 500):
        """
        Initialize cache.

        Args:
            max_size_mb: Maximum cache size in MB
        """
        self.max_size_bytes = max_size_mb * (1024 ** 2)
        self.cache: OrderedDict[str, Tuple] = OrderedDict()
        self.current_size = 0

    def get(self, key: str):
        """Get tile from cache."""
        if key in self.cache:
            tile, size = self.cache.pop(key)
            self.cache[key] = (tile, size)  # Move to end (recently used)
            logger.debug(f"Cache hit: {key}")
            return tile
        return None

    def put(self, key: str, tile):
        """Put tile in cache, evicting LRU items if needed.

        Accepts numpy arrays or raw bytes (e.g., PNG-encoded tile data).
        """
        if isinstance(tile, (bytes, bytearray)):
            tile_size = len(tile)
        elif hasattr(tile, "nbytes"):
            tile_size = tile.nbytes
        else:
            tile_size = sys.getsizeof(tile)

        # Evict LRU items until we have space
        while self.current_size + tile_size > self.max_size_bytes and self.cache:
            evicted_key, (_, evicted_size) = self.cache.popitem(last=False)
            self.current_size -= evicted_size
            logger.debug(f"Cache evict: {evicted_key}")

        self.cache[key] = (tile, tile_size)
        self.current_size += tile_size
        logger.debug(f"Cache put: {key} ({tile_size / 1024:.1f}KB)")

    def clear(self):
        """Clear cache."""
        self.cache.clear()
        self.current_size = 0

    def stats(self) -> dict:
        """Get cache statistics."""
        return {
            "num_tiles": len(self.cache),
            "size_mb": self.current_size / (1024 ** 2),
            "max_mb": self.max_size_bytes / (1024 ** 2),
        }

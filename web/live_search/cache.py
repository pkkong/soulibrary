import copy
import threading
import time


class TTLMemoryCache:
    def __init__(self, ttl_seconds: int, max_items: int = 256):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_items = max(1, int(max_items))
        self._items = {}
        self._lock = threading.Lock()

    def get(self, key):
        now = time.time()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            return copy.deepcopy(value)

    def set(self, key, value):
        now = time.time()
        with self._lock:
            if len(self._items) >= self.max_items:
                expired = [k for k, (expires_at, _) in self._items.items() if expires_at <= now]
                for k in expired:
                    self._items.pop(k, None)
                while len(self._items) >= self.max_items:
                    oldest_key = min(self._items, key=lambda k: self._items[k][0])
                    self._items.pop(oldest_key, None)
            self._items[key] = (now + self.ttl_seconds, copy.deepcopy(value))

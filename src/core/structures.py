"""
Core Data Structures - Optimized data containers for high-performance trading.
"""

from __future__ import annotations

import threading
from typing import Optional, Tuple

import numpy as np


class RingBuffer:
    """
    Fixed-size circular buffer using pre-allocated NumPy arrays.
    Optimized for O(1) appends and zero-copy sliding windows.
    Thread-safe via an internal lock.
    """

    def __init__(self, capacity: int, dtype: np.dtype = np.float64):
        self.capacity = capacity
        self.size = 0
        self.position = 0
        self._data = np.zeros(capacity, dtype=dtype)
        self._lock = threading.Lock()

    def append(self, value: float) -> None:
        """Append a single value to the buffer, overwriting oldest if full."""
        with self._lock:
            self._data[self.position] = value
            self.position = (self.position + 1) % self.capacity
            if self.size < self.capacity:
                self.size += 1

    def append_many(self, values: np.ndarray) -> None:
        """Append multiple values efficiently."""
        with self._lock:
            n = len(values)
            if n >= self.capacity:
                self._data[:] = values[-self.capacity:]
                self.position = 0
                self.size = self.capacity
                return

            start = self.position
            end = (start + n) % self.capacity

            if start + n <= self.capacity:
                self._data[start:start+n] = values
            else:
                split = self.capacity - start
                self._data[start:] = values[:split]
                self._data[:n-split] = values[split:]

            self.position = end
            if self.size < self.capacity:
                self.size = min(self.size + n, self.capacity)

    def view(self) -> np.ndarray:
        """
        Return a view of the valid data in chronological order.
        Note: This may return a copy if the data wraps around.
        """
        with self._lock:
            if self.size == 0:
                return np.array([], dtype=self._data.dtype)
            if self.size < self.capacity:
                return self._data[:self.size].copy()
            if self.position == 0:
                return self._data.copy()
            return np.concatenate((
                self._data[self.position:],
                self._data[:self.position]
            ))

    def latest(self, n: int = 1) -> np.ndarray:
        """Get the most recent n values."""
        with self._lock:
            if n <= 0 or self.size == 0:
                return np.array([], dtype=self._data.dtype)
            n = min(n, self.size)

            end = self.position
            start = (end - n) % self.capacity

            if start < end:
                return self._data[start:end].copy()
            else:
                return np.concatenate((self._data[start:], self._data[:end]))

    def get_last(self) -> float:
        """Get the very last appended value."""
        with self._lock:
            if self.size == 0:
                return 0.0
            idx = (self.position - 1) % self.capacity
            return float(self._data[idx])

    def clear(self) -> None:
        """Reset the buffer."""
        with self._lock:
            self.size = 0
            self.position = 0
            self._data.fill(0)

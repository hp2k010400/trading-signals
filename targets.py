"""
Tracks active trade targets per symbol.
Each target has a direction, a TP level, and up to MAX_ENTRIES entries.
New entries (DCA) fire when price pulls back ENTRY_SEPARATION points.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import config


@dataclass
class Target:
    symbol:    str
    direction: str          # "bull" | "bear"
    tp:        float
    entries:   list[float] = field(default_factory=list)
    created:   datetime    = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def last_entry(self) -> float | None:
        return self.entries[-1] if self.entries else None

    def is_full(self) -> bool:
        return self.entry_count >= config.MAX_ENTRIES

    def is_expired(self) -> bool:
        age = (datetime.now(timezone.utc) - self.created).total_seconds()
        return age > config.TARGET_EXPIRY_HOURS * 3600

    def needs_dca(self, current_price: float) -> bool:
        """
        True if price has moved FURTHER in our direction since last entry.
        This is pyramiding (adding to winners) not averaging down.
        For buys:  price moved UP   sep points from last entry
        For sells: price moved DOWN sep points from last entry
        """
        if self.is_full() or self.last_entry is None:
            return False
        sep = config.ENTRY_SEPARATION
        if self.direction == "bull":
            return current_price >= self.last_entry + sep
        else:
            return current_price <= self.last_entry - sep

    def tp_hit(self, current_price: float) -> bool:
        if self.direction == "bull":
            return current_price >= self.tp
        else:
            return current_price <= self.tp

    @property
    def sl_level(self) -> float:
        if not self.entries:
            return 0.0
        last = self.entries[-1]
        return (last + config.SL_POINTS) if self.direction == "bear" else (last - config.SL_POINTS)

    def sl_hit(self, current_price: float) -> bool:
        sl = self.sl_level
        if self.direction == "bull":
            return current_price <= sl
        else:
            return current_price >= sl

    def add_entry(self, price: float):
        self.entries.append(price)


# ── Global state ──────────────────────────────────────────────────────────────

_active: dict[str, Target] = {}   # symbol → Target


def get(symbol: str) -> Target | None:
    t = _active.get(symbol)
    if t and t.is_expired():
        del _active[symbol]
        return None
    return t


def set_target(symbol: str, direction: str, tp: float, entry_price: float) -> Target:
    t = Target(symbol=symbol, direction=direction, tp=tp)
    t.add_entry(entry_price)
    _active[symbol] = t
    return t


def clear(symbol: str):
    _active.pop(symbol, None)


def add_dca_entry(symbol: str, entry_price: float):
    if symbol in _active:
        _active[symbol].add_entry(entry_price)

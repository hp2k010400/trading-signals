"""
Tracks active trade targets per symbol.
State is persisted to targets_state.json so it survives bot restarts.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json, os
import config

STATE_FILE = "targets_state.json"


@dataclass
class Target:
    symbol:    str
    direction: str
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

    def to_dict(self) -> dict:
        return {
            "symbol":    self.symbol,
            "direction": self.direction,
            "tp":        self.tp,
            "entries":   self.entries,
            "created":   self.created.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Target":
        t = cls(
            symbol    = d["symbol"],
            direction = d["direction"],
            tp        = d["tp"],
            entries   = d["entries"],
            created   = datetime.fromisoformat(d["created"]),
        )
        return t


# ── Global state ──────────────────────────────────────────────────────────────

_active: dict[str, Target] = {}


def _save():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({sym: t.to_dict() for sym, t in _active.items()}, f)
    except Exception as e:
        print(f"[Targets] Save failed: {e}")


def _load():
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        for sym, d in data.items():
            t = Target.from_dict(d)
            if not t.is_expired():
                _active[sym] = t
                print(f"[Targets] Restored: {sym} {t.direction} TP={t.tp} entries={t.entry_count}")
    except Exception as e:
        print(f"[Targets] Load failed: {e}")


# Load persisted state on import
_load()


def get(symbol: str) -> Target | None:
    t = _active.get(symbol)
    if t and t.is_expired():
        del _active[symbol]
        _save()
        return None
    return t


def set_target(symbol: str, direction: str, tp: float, entry_price: float) -> Target:
    t = Target(symbol=symbol, direction=direction, tp=tp)
    t.add_entry(entry_price)
    _active[symbol] = t
    _save()
    return t


def clear(symbol: str):
    _active.pop(symbol, None)
    _save()


def add_dca_entry(symbol: str, entry_price: float):
    if symbol in _active:
        _active[symbol].add_entry(entry_price)
        _save()

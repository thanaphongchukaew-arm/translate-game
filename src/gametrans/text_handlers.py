"""Per-text-type handling logic that genuinely needs runtime state beyond
what a preset's static config values provide (spec section 8.9). Most
preset types (dialogue/ui/hud/subtitle/tooltip/retro_pixel) are just
different config values applied by the pipeline — only `chat_log` needs a
real stateful algorithm: detecting which lines are actually new as chat
scrolls, so already-translated lines are never re-sent to the translator.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _longest_overlap(prev: list[str], cur: list[str]) -> int:
    """Largest L such that cur[:L] == prev[-L:] — i.e. how many lines at
    the top of the current view are the same lines (in the same order)
    that were at the bottom of the previous view, meaning the log
    scrolled by (len(prev) - L) lines and cur[L:] is genuinely new."""
    max_l = min(len(prev), len(cur))
    for l in range(max_l, 0, -1):
        if cur[:l] == prev[-l:]:
            return l
    return 0


@dataclass
class ChatLogTracker:
    """Tracks a scrolling chat/log region and reports only the lines that
    are new since the last call. Lines are matched by exact text equality
    (position-aware, not just "have we ever seen this string before") so a
    line that happens to repeat later (someone says "lol" twice) is still
    reported as new when it actually is."""

    _prev_lines: list[str] = field(default_factory=list)

    def new_lines(self, current_lines: list[str]) -> list[str]:
        if not self._prev_lines:
            self._prev_lines = list(current_lines)
            return list(current_lines)

        overlap = _longest_overlap(self._prev_lines, current_lines)
        new = current_lines[overlap:]
        self._prev_lines = list(current_lines)
        return new

    def reset(self) -> None:
        self._prev_lines = []

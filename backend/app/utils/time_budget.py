"""
How long a request may wait on the model.

On the public steps every request passes through Cloudflare, which gives up
on an answer after 100 seconds (a 524, and the visitor sees nothing). A
question to the city, the Scribe or the one who had the floor, and anything
else that waits on the model while the request is open, is given a budget
(begin()); the calls it makes inside it are cut to the time left, without
retries, and give up with TimeBudgetSpent when it is gone. The request then
answers with a calm line instead of a 524.

The budget belongs to the request's own thread. Work handed to other
threads (a Chronicle, a film, a run) is never cut by it; a caller that hands
work to a pool passes the time left along itself (see symposium_memory).

Without begin() (the owner's own machine) nothing here changes anything.
"""

import threading
import time
from typing import Optional

# The least time a call is still started with.
MIN_CALL_SECONDS = 3.0

_local = threading.local()


class TimeBudgetSpent(TimeoutError):
    """The request's time for the model is gone."""


def begin(seconds: float) -> None:
    """Give this thread's request `seconds` for the model, from now."""

    _local.end = time.monotonic() + max(0.0, float(seconds))
    _local.spent = False


def clear() -> None:
    """End this thread's budget (the request is over; the thread serves the next one)."""

    _local.end = None
    _local.spent = False


def active() -> bool:
    return getattr(_local, 'end', None) is not None


def remaining() -> Optional[float]:
    """Seconds left, or None when this thread has no budget."""

    end = getattr(_local, 'end', None)
    if end is None:
        return None
    return max(0.0, end - time.monotonic())


def cap(seconds: float) -> float:
    """`seconds`, or the time left when that is less."""

    left = remaining()
    if left is None:
        return seconds
    return min(float(seconds), left)


def mark_spent() -> None:
    if active():
        _local.spent = True


def spent() -> bool:
    """Whether a call in this request gave up because the budget was gone."""

    return bool(getattr(_local, 'spent', False))


def call_seconds(minimum: float = MIN_CALL_SECONDS) -> Optional[float]:
    """The timeout for the next call: None without a budget; raises when too little is left."""

    left = remaining()
    if left is None:
        return None
    if left < minimum:
        mark_spent()
        raise TimeBudgetSpent('the request has no time left for the model')
    return left

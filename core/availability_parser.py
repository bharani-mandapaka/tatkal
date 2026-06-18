"""
Parse raw IRCTC availability badge text into a structured result, then evaluate
it against the user's booking thresholds.

Formats seen on IRCTC search results:
  AVAILABLE-4         → 4 confirmed seats
  CURR_AVBL           → confirmed, exact count unknown
  CURR_AVBL-3         → confirmed, 3 remaining
  RAC 7               → RAC position 7 (can board, side berth)
  GNWL 45/WL 30       → WL from origin; current wl_position=30
  RLWL 5/WL 3         → WL for remote-to-remote leg
  PQWL 12/WL 8        → point-to-point quota WL
  TQWL 3/WL 2         → Tatkal quota WL
  RSWL 1/WL 1         → roadside-station WL
  WL 10               → generic WL (no sub-type)
  REGRET              → no more bookings accepted
  NOT AVAILABLE       → window closed / train not running
  TRAIN CANCELLED     → train cancelled for that date
"""
import re
from dataclasses import dataclass, field

# WL types that will never be in allowed_wl_types by default.
# Order matters for UI display: "premium" odds first.
_ALL_WL_TYPES = ("GNWL", "RLWL", "WL", "PQWL", "TQWL", "RSWL")


@dataclass
class AvailabilityResult:
    raw: str
    status_type: str            # AVAILABLE / CURR_AVBL / RAC / GNWL / RLWL / PQWL / TQWL / RSWL / WL / REGRET / NOT_AVAILABLE / TRAIN_CANCELLED / UNKNOWN
    is_bookable: bool           # False for REGRET / NOT_AVAILABLE / TRAIN_CANCELLED
    confirmed_count: int | None = None   # for AVAILABLE-N / CURR_AVBL-N
    rac_number: int | None = None        # for RAC N
    wl_position: int | None = None       # the "current" WL position (second number after /)
    wl_total: int | None = None          # the initial WL total (first number before /)


def parse_availability(text: str) -> AvailabilityResult:
    t = text.strip().upper()

    if not t or t in ("NOT AVAILABLE", "NOT_AVAILABLE", "NOT AVBL"):
        return AvailabilityResult(raw=text, status_type="NOT_AVAILABLE", is_bookable=False)
    if t in ("REGRET", "REGRET/REGRET"):
        return AvailabilityResult(raw=text, status_type="REGRET", is_bookable=False)
    if "TRAIN CANCEL" in t or "CANCELLED" in t:
        return AvailabilityResult(raw=text, status_type="TRAIN_CANCELLED", is_bookable=False)

    if t.startswith("AVAILABLE"):
        m = re.search(r"(\d+)", t)
        count = int(m.group(1)) if m else None
        return AvailabilityResult(
            raw=text, status_type="AVAILABLE", is_bookable=True, confirmed_count=count
        )

    if t.startswith("CURR_AVBL") or t.startswith("CURR AVBL"):
        m = re.search(r"(\d+)", t)
        count = int(m.group(1)) if m else None
        return AvailabilityResult(
            raw=text, status_type="CURR_AVBL", is_bookable=True, confirmed_count=count
        )

    if t.startswith("RAC"):
        m = re.search(r"(\d+)", t)
        rac = int(m.group(1)) if m else None
        return AvailabilityResult(
            raw=text, status_type="RAC", is_bookable=True, rac_number=rac
        )

    for wl_type in ("GNWL", "RLWL", "PQWL", "TQWL", "RSWL"):
        if t.startswith(wl_type):
            nums = re.findall(r"(\d+)", t)
            wl_total = int(nums[0]) if nums else None
            wl_pos   = int(nums[1]) if len(nums) > 1 else wl_total
            return AvailabilityResult(
                raw=text, status_type=wl_type, is_bookable=True,
                wl_position=wl_pos, wl_total=wl_total
            )

    # Generic "WL N" with no sub-type prefix
    if t.startswith("WL"):
        nums = re.findall(r"(\d+)", t)
        wl_pos = int(nums[0]) if nums else None
        return AvailabilityResult(
            raw=text, status_type="WL", is_bookable=True, wl_position=wl_pos
        )

    return AvailabilityResult(raw=text, status_type="UNKNOWN", is_bookable=False)


def evaluate_threshold(
    result: AvailabilityResult, thresholds, passenger_count: int | None = None
) -> str:
    """
    Returns one of: "book" | "pause" | "skip"

    thresholds is a BookingThresholds instance (imported at call site to avoid
    circular deps, since models imports nothing from this module).

    passenger_count, when provided, guards against booking a class that has
    fewer confirmed seats than passengers (a partial/split booking).
    """
    st = result.status_type

    if st in ("AVAILABLE", "CURR_AVBL"):
        cc = result.confirmed_count
        # Zero confirmed seats. IRCTC briefly shows "AVAILABLE-0" during the
        # rush — the status says AVAILABLE but there is nothing to book.
        if cc is not None and cc <= 0:
            return "skip"
        # Fewer confirmed seats than passengers → booking would split the party
        # (some confirmed, some waitlisted). Surface to the user rather than
        # silently committing to a partial booking.
        if passenger_count and cc is not None and cc < passenger_count:
            return "pause"
        return "book"

    if not result.is_bookable:
        return "skip"

    if st == "RAC":
        if thresholds.max_rac is None:
            return "skip"
        rac = result.rac_number or 0
        if rac > thresholds.max_rac:
            return "skip"
        if thresholds.max_rac - rac < thresholds.borderline_buffer:
            return "pause"
        return "book"

    # WL types
    if st in _ALL_WL_TYPES:
        if st not in thresholds.allowed_wl_types and "WL" not in thresholds.allowed_wl_types:
            return "skip"
        if thresholds.max_wl is None:
            return "skip"
        wl_pos = result.wl_position or 0
        if wl_pos > thresholds.max_wl:
            return "skip"
        if thresholds.max_wl - wl_pos < thresholds.borderline_buffer:
            return "pause"
        return "book"

    return "skip"

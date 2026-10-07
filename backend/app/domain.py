"""熬锅业务门槛。

- 出胶（已出胶）：最近一次煮胶峰值温度须 ≥ 90℃，只看峰值，与清灰单无关。
- 冷锅改熬煮中：该锅必须挂着一张未核销的灶膛清灰单。
"""

from app.models import Kettle

MIN_PEAK = 90.0


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def has_open_ash_ticket(kettle: Kettle) -> bool:
    tickets = getattr(kettle, "ash_tickets", None) or []
    return any(t.redeemed_at is None for t in tickets)


def assert_can_set_status(
    kettle: Kettle, new_status: str, open_ash_ticket: bool | None = None
) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Kettle.STATUS_DRAWN:
        # 出胶只看峰值门槛，清灰单不得掺进出胶判断。
        peak = latest_peak(kettle)
        if peak is None:
            raise RuleError("该锅尚无煮胶峰值，不能出胶")
        if peak < MIN_PEAK:
            raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
        return
    if kettle.status == Kettle.STATUS_COLD and new_status == Kettle.STATUS_BOILING:
        if open_ash_ticket is None:
            open_ash_ticket = has_open_ash_ticket(kettle)
        if not open_ash_ticket:
            raise RuleError("该锅没有未核销的灶膛清灰单，不能改成熬煮中")

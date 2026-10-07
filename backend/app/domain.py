"""熬锅作业门槛。

- 出胶：最近一次煮胶峰值温度须 ≥ 90℃，与清灰单无关。
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


def assert_can_set_status(kettle: Kettle, new_status: str, has_open_ash_ticket: bool = False) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Kettle.STATUS_DRAWN:
        # 已出胶只看峰值门槛，清灰单不掺进此判断。
        peak = latest_peak(kettle)
        if peak is None:
            raise RuleError("该锅尚无煮胶峰值，不能出胶")
        if peak < MIN_PEAK:
            raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
        return
    if new_status == Kettle.STATUS_BOILING and kettle.status == Kettle.STATUS_COLD:
        # 冷锅开熬前必须先清灶膛，且挂着一张未核销清灰单。
        if not has_open_ash_ticket:
            raise RuleError("该锅没有未核销的灶膛清灰单，不能改成熬煮中")

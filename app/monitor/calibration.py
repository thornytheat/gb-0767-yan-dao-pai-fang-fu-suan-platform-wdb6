"""采样仪时钟回拨（校时）的领域规则。

回拨只允许把时钟往过去拨。回拨发生时，仪器显示时刻会重复一段区间：
``[rollback_at - back, rollback_at)``（真实时间），回拨前后两组独立采样
会落在相同的显示分钟上。二者是两次物理采样，必须各自保留，不能互当修订。
"""
from dataclasses import dataclass

from app.errors import InputError
from app.monitor.clock import HOUR, MINUTE, minute

MAX_BACK_MINUTES = 24 * 60
TICKET_LIMIT = 40


@dataclass(frozen=True)
class Adjustment:
    """一次时钟回拨校时事件。

    rollback_at: 真实时间（UTC）下，操作员把时钟回拨的那一刻。
    back_minutes: 回拨时长（正数），显示时刻被往过去拨多少分钟。
    ticket: 提出校时确认的交接凭据（班次/单号）。
    confirmed: 校时是否已经确认；未确认前受影响小时只挂起、不出正式差额。
    """

    rollback_at: object
    back_minutes: int
    ticket: str
    confirmed: bool = False

    @property
    def back(self):
        return MINUTE * self.back_minutes

    @property
    def band_start(self):
        """重叠时段起点（真实时间）：回拨后显示时刻重新走到的最早一刻。"""
        return self.rollback_at - self.back

    @property
    def band_end(self):
        """重叠时段终点（真实时间）：回拨发生的那一刻。"""
        return self.rollback_at

    def is_repeated_reading(self, when_display, received):
        """收件严格晚于回拨时刻、显示时刻落在重叠段内的，才是回拨后那组采样。

        回拨点本身（``received == rollback_at``）送达的仍是回拨前最后一条。
        """
        return received > self.rollback_at and self.band_start <= when_display < self.band_end

    def correct(self, when_display, received):
        """确认后把显示时刻纠正为真实时刻；不属于回拨后重复段的原样返回。"""
        if self.is_repeated_reading(when_display, received):
            return when_display + self.back
        return when_display

    def with_confirmed(self, ticket):
        return Adjustment(self.rollback_at, self.back_minutes, ticket, True)


def parse_clock(raw, window):
    """解析 clock.json 的单个回拨事件；缺省返回 None 表示无校时。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InputError('BAD_CLOCK', '校时原件必须是单个对象')
    try:
        rollback_at = minute(raw['rollback_at'])
        back = raw['back_minutes']
        ticket = raw['ticket']
        if type(back) is not int or not 1 <= back <= MAX_BACK_MINUTES:
            raise ValueError
        if not isinstance(ticket, str) or not ticket.strip() or len(ticket) > TICKET_LIMIT:
            raise ValueError
        if rollback_at.second or rollback_at.microsecond:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise InputError('BAD_CLOCK', '校时事件、回拨分钟或交接凭据无效') from None
    adjustment = Adjustment(rollback_at, back, ticket.strip(), bool(raw.get('confirmed', False)))
    # 回拨重叠段必须与监测窗口有交集，否则没有需要交接的小时。
    if adjustment.band_end <= window.start or adjustment.band_start >= window.end:
        raise InputError('BAD_CLOCK', '校时回拨段与监测窗口无交集')
    return adjustment


def _hours_overlapping(interval_start, interval_end, window):
    if interval_end <= interval_start:
        return []
    start = max(interval_start, window.start)
    end = min(interval_end, window.end)
    if end <= start:
        return []
    first = start.replace(minute=0, second=0, microsecond=0)
    last_hour = (end - MINUTE).replace(minute=0, second=0, microsecond=0)
    hours = []
    cursor = first
    while cursor <= last_hour and cursor < window.end:
        if cursor >= window.start:
            hours.append(cursor.isoformat())
        cursor += HOUR
    return hours


def affected_hours(adjustment, window):
    """采信可能被校时改变的小时桶（ISO），确认前一律挂起。

    含两段：回拨重复段的真实区间（移出方，读数显示分钟所在小时），以及确认后
    纠正读数落入的真实区间 ``[rollback_at, rollback_at+back)``（移入方）。
    """
    if adjustment is None:
        return []
    repeat_hours = _hours_overlapping(adjustment.band_start, adjustment.band_end, window)
    target_hours = _hours_overlapping(adjustment.rollback_at,
                                      adjustment.rollback_at + adjustment.back, window)
    return sorted(set(repeat_hours) | set(target_hours))


def resolve_confirmation(existing, incoming):
    """两班冲突确认的纯函数裁决：同一凭据幂等，冲突只接受先到的一套。

    返回 (accepted_adjustment, reused)。``existing`` 为已接受的确认，
    ``incoming`` 为新提交的确认；凭据不同即冲突，拒绝后来者。
    """
    if existing is not None:
        if existing.ticket == incoming.ticket:
            return existing, True
        raise ClockConflict(existing.ticket)
    return incoming, False


class ClockConflict(InputError):
    def __init__(self, winning_ticket):
        super().__init__('CLOCK_CONFIRM_CONFLICT',
                         f'校时确认冲突，已接受凭据 {winning_ticket}，本套不予采信', 409)
        self.winning_ticket = winning_ticket

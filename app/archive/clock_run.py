import json

from app.archive.manifest import canonical
from app.errors import InputError
from app.monitor.calibration import ClockConflict, resolve_confirmation
from app.monitor.inspection import Inspection


def confirm_clock(store, run_id, ticket):
    """对某监测留档接受一套校时确认并整包重算。

    两班并发提交冲突凭据时，SQLite 唯一约束只放行第一套，后来者收到
    ``CLOCK_CONFIRM_CONFLICT``；同一凭据重复提交幂等返回。确认后的读数按
    真实时刻重新归桶，跨整点移动的读数会同时重算移出与移入小时。
    """
    packet = store.require(run_id)
    if 'clock' not in packet['originals']:
        raise InputError('CLOCK_EVENT_MISSING', '该批次没有待确认的时钟回拨原件', 422)
    if not isinstance(ticket, str) or not ticket.strip() or len(ticket) > 40:
        raise InputError('BAD_TICKET', '交接凭据无效', 422)
    ticket = ticket.strip()

    clock_raw = json.loads(packet['originals']['clock'].removeprefix('﻿'))
    adjustment = Inspection({**packet['originals'],
                             'clock': json.dumps(clock_raw | {'confirmed': True})}).adjustment
    incoming = adjustment.with_confirmed(ticket)

    existing = store.clock_confirmation(run_id)
    if existing is not None:
        _, reused = resolve_confirmation(_to_adjustment(existing['meta']), incoming)
        return existing['packet'], reused

    confirmed_packet = _rebuild(packet, incoming)
    meta = {'ticket': incoming.ticket, 'rollback_at': incoming.rollback_at.isoformat(),
            'back_minutes': incoming.back_minutes}
    winning_ticket, saved_packet = store.save_clock_confirmation(run_id, incoming.ticket, meta, confirmed_packet)
    if winning_ticket != incoming.ticket:
        # 并发下唯一约束先接受了另一套，本套不予采信。
        raise ClockConflict(winning_ticket)
    return saved_packet, False


def _to_adjustment(meta):
    from app.monitor.calibration import Adjustment
    from app.monitor.clock import minute
    return Adjustment(minute(meta['rollback_at']), meta['back_minutes'], meta['ticket'], True)


def _rebuild(packet, adjustment):
    """用已确认的校时原件重算整条管线；未确认原件仍保留在 originals 内可追溯。"""
    clock_raw = json.loads(packet['originals']['clock'].removeprefix('﻿'))
    confirmed_clock = json.dumps(clock_raw | {'confirmed': True, 'ticket': adjustment.ticket},
                                 ensure_ascii=False)
    files = {**packet['originals'], 'clock': confirmed_clock}
    results = Inspection(files).results()
    return {**packet, 'results': results,
            'clock_confirmation': {'ticket': adjustment.ticket,
                                   'rollback_at': adjustment.rollback_at.isoformat(),
                                   'back_minutes': adjustment.back_minutes,
                                   'results_canonical': canonical(results)}}

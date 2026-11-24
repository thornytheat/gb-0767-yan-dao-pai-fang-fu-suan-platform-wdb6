import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import InputError
from app.monitor.calibration import (
    Adjustment, ClockConflict, affected_hours, parse_clock, resolve_confirmation,
)
from app.monitor.clock import minute
from app.monitor.source import sample
from app.monitor.inspection import Inspection


@pytest.fixture(scope='session')
def rollback():
    return Inspection(sample('rollback'))


def test_pending_hours_cover_move_out_and_move_in(rollback):
    # 重复段真实区间 00:50-01:00（移出方），纠正后落点 01:00-01:10（移入方）。
    assert rollback.clock['pending_hours'] == [
        '2026-11-14T00:00:00+00:00', '2026-11-14T01:00:00+00:00']


def test_same_display_minute_kept_twice_not_revisions(rollback):
    # 回拨前后同刻采样各自保留，绝不互当修订（无 SUPERSEDED/DUPLICATE/CONFLICT）。
    repeats = rollback.clock['repeats']
    # 显示分钟 00:50..00:59 共 10 条回拨后采样；其中 00:55 回拨前本就缺测，
    # 故 9 条与回拨前同刻成对，00:55 仅回拨后一条，全部按 CLOCK_REPEAT 保留。
    assert len(repeats) == 10
    assert all(r['code'] == 'CLOCK_REPEAT' and r['clock_side'] == 'post' for r in repeats)
    display_minutes = {r['display_utc'] for r in repeats}
    assert '2026-11-14T00:50:00+00:00' in display_minutes
    isolated_codes = {r['code'] for r in rollback.oxygen['isolated']}
    assert 'CLOCK_REPEAT' in isolated_codes
    repeat_lines = {r['line'] for r in repeats}
    revisionish = {r['code'] for r in rollback.oxygen['isolated']
                   if r['line'] in repeat_lines and r['code'] != 'CLOCK_REPEAT'}
    assert revisionish == set()


def test_unconfirmed_hours_withhold_official_difference(rollback):
    rows = rollback.reports['rows']
    assert [r['code'] for r in rows] == ['CLOCK_PENDING', 'CLOCK_PENDING']
    # 复算与报送仍照常展示，仅正式差额暂不出。
    assert all(r['difference_mg_nm3'] is None for r in rows)
    assert [r['reported_mg_nm3'] for r in rows] == ['30.00', '36.58']
    assert all(r['mg_nm3'] is not None for r in rows)


def test_minute_conservation_while_pending(rollback):
    totals = rollback.hours['totals']
    assert totals['scheduled'] == totals['valid'] + totals['exempt'] + totals['missing'] == 120


def test_other_hours_still_reconcile_when_only_some_pending():
    # 构造一个回拨段只压在单个小时内的窗口，其余小时须照常裁决。
    files = sample('rollback')
    window = json.loads(files['window'])
    window['start'] = '2026-11-14T08:00+08:00'
    clock = json.loads(files['clock'])
    clock['rollback_at'] = '2026-11-14T00:20Z'
    clock['back_minutes'] = 5
    audit = Inspection(files | {'window': json.dumps(window), 'clock': json.dumps(clock)})
    codes = [r['code'] for r in audit.reports['rows']]
    assert codes[0] == 'CLOCK_PENDING'
    assert codes[1] != 'CLOCK_PENDING'


def test_confirmed_recalculates_both_hours_and_restores_difference(rollback):
    files = sample('rollback')
    clock = json.loads(files['clock'])
    confirmed = Inspection({**files, 'clock': json.dumps(clock | {'confirmed': True})})
    assert confirmed.clock['confirmed'] is True
    assert confirmed.clock['pending_hours'] == []
    assert confirmed.clock['repeats'] == []
    rows = confirmed.reports['rows']
    assert [r['code'] for r in rows] == ['MATCH', 'MATCH']
    assert [r['difference_mg_nm3'] for r in rows] == ['0.31', '0.00']
    # 移入小时的有效分钟由 50 升至 60，证明跨整点读数已重算；移出小时维持 59。
    assert [h['valid'] for h in confirmed.hours['rows']] == [59, 60]
    assert confirmed.hours['totals']['missing'] == 1


def test_cross_hour_readings_move_to_true_minutes(rollback):
    files = sample('rollback')
    clock = json.loads(files['clock'])
    confirmed = Inspection({**files, 'clock': json.dumps(clock | {'confirmed': True})})
    selected, _, _, _ = confirmed.corrected
    moved_in = sorted(k.strftime('%H:%M') for k in selected if k.hour == 1 and k.minute < 10)
    # 回拨后 10 条全部纠正到真实分钟 01:00..01:09（含原显示 00:55 的一条）。
    assert moved_in == [f'01:0{i}' for i in range(10)]
    # 回拨前读数仍保留在原显示分钟，未被覆盖。
    retained = sorted(k.strftime('%H:%M') for k in selected if k.hour == 0 and k.minute >= 50)
    assert retained == ['00:50', '00:51', '00:52', '00:53', '00:54',
                        '00:56', '00:57', '00:58', '00:59']


def test_modes_and_cutoff_rules_unchanged(rollback):
    # 校时不改变收件截止：晚于 cutoff 的仍按 AFTER_CUTOFF 隔离。
    files = sample('rollback')
    late = dict(files)
    late['minutes'] = files['minutes'] + (
        'K-04,2026-11-14T01:30Z,99,mg/Nm3,dry,-,10,OK,1,2026-11-14T05:30Z\r\n')
    audit = Inspection(late)
    assert any(r['code'] == 'AFTER_CUTOFF' for r in audit.oxygen['isolated'])


def test_parse_clock_rejects_forward_and_bad_values(rollback):
    window = rollback.window
    with pytest.raises(InputError) as bad:
        parse_clock({'rollback_at': '2026-11-14T01:00Z', 'back_minutes': 0, 'ticket': 'x'}, window)
    assert bad.value.code == 'BAD_CLOCK'
    with pytest.raises(InputError) as bad:
        parse_clock({'rollback_at': '2026-11-14T01:00Z', 'back_minutes': '10', 'ticket': 'x'}, window)
    assert bad.value.code == 'BAD_CLOCK'
    with pytest.raises(InputError) as bad:
        parse_clock({'rollback_at': '2030-01-01T00:00Z', 'back_minutes': 10, 'ticket': 'x'}, window)
    assert bad.value.code == 'BAD_CLOCK'


def test_resolve_confirmation_idempotent_and_conflict():
    first = Adjustment(minute('2026-11-14T01:00Z'), 10, '甲班', True)
    accepted, reused = resolve_confirmation(None, first)
    assert (accepted.ticket, reused) == ('甲班', False)
    same, reused = resolve_confirmation(first, first)
    assert (same.ticket, reused) == ('甲班', True)
    other = Adjustment(minute('2026-11-14T01:00Z'), 10, '乙班', True)
    with pytest.raises(ClockConflict) as failure:
        resolve_confirmation(first, other)
    assert failure.value.winning_ticket == '甲班'


def test_affected_hours_empty_without_adjustment(rollback):
    assert affected_hours(None, rollback.window) == []


def test_pending_keeps_move_out_hour_when_target_crosses_window_end(rollback):
    # 回拨点贴近窗口末端：纠正落点越出 end，移出小时仍须挂起，且不臆造窗外小时。
    files = sample('rollback')
    clock = json.loads(files['clock'])
    clock['rollback_at'] = '2026-11-14T01:55Z'   # 窗口 end = 02:00
    clock['back_minutes'] = 10                   # 落点 01:55-02:05，部分越窗
    audit = Inspection({**files, 'clock': json.dumps(clock)})
    pending = audit.clock['pending_hours']
    assert '2026-11-14T01:00:00+00:00' in pending          # 移出/重叠小时挂起
    assert all(h < rollback.window.end.isoformat() for h in pending)  # 不臆造窗外小时
    assert all(r['code'] == 'CLOCK_PENDING' for r in audit.reports['rows']
               if r['hour'] in pending)

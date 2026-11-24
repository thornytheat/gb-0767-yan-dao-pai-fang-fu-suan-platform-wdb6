from collections import defaultdict
from datetime import timedelta

from app.monitor.clock import instant, minute

MEASURES = ('value', 'unit', 'basis', 'moisture', 'oxygen', 'status')


def choose(rows, window, adjustment=None):
    """按业务分钟采信修订。

    传入未确认的时钟回拨事件时，回拨后落在重复段内的采样与回拨前同刻采样
    是两次独立物理采样：各自保留为 ``CLOCK_REPEAT``，绝不互当修订（不会出现
    SUPERSEDED/DUPLICATE/CONFLICT）。确认后则把回拨后采样纠正到真实分钟，
    与回拨前采样落在不同时间槽，再走统一修订裁决。
    """
    by_minute = defaultdict(list)
    isolated = []
    clock_repeats = []
    for row in rows:
        fields = row['fields']
        try:
            when_display, received = minute(fields['timestamp']), instant(fields['received'])
            if fields['stack'] != window.stack:
                raise ValueError('WRONG_STACK')
            if not window.start <= when_display < window.end:
                raise ValueError('OUTSIDE_WINDOW')
            if received > window.cutoff:
                raise ValueError('AFTER_CUTOFF')
            revision = fields['revision']
            if not revision.isascii() or not revision.isdecimal() or len(revision) > 6 or received < when_display:
                raise ValueError('BAD_REVISION')
        except ValueError as error:
            isolated.append(row | {'code': str(error)})
            continue

        when = when_display
        if adjustment is not None and adjustment.is_repeated_reading(when_display, received):
            if adjustment.confirmed:
                when = adjustment.correct(when_display, received)
                if not window.start <= when < window.end:
                    isolated.append(row | {'code': 'OUTSIDE_WINDOW'})
                    continue
            else:
                evidence = row | {'code': 'CLOCK_REPEAT', 'clock_side': 'post',
                                  'display_utc': when_display.isoformat(),
                                  'true_utc': (when_display + adjustment.back).isoformat()}
                clock_repeats.append(evidence)
                isolated.append(evidence)
                continue
        by_minute[when].append((int(revision), received, row))

    selected = {}
    conflicts = {}
    for when, candidates in sorted(by_minute.items()):
        top = max(item[0] for item in candidates)
        active = sorted((item for item in candidates if item[0] == top), key=lambda x: (x[1], x[2]['line']))
        older = [row | {'code': 'SUPERSEDED'} for rev, _, row in candidates if rev < top]
        isolated.extend(older)
        signatures = {tuple(item[2]['fields'][key] for key in MEASURES) for item in active}
        if len(signatures) > 1:
            conflicts[when] = [row | {'code': 'CONFLICT'} for _, _, row in active]
            isolated.extend(conflicts[when])
            continue
        _, received, row = active[0]
        selected[when] = row | {'late': received - when > timedelta(minutes=5), 'revision': top}
        isolated.extend(row | {'code': 'DUPLICATE'} for _, _, row in active[1:])
    return selected, conflicts, sorted(isolated, key=lambda row: row['line']), clock_repeats

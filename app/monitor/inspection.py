from functools import cached_property

from app.monitor.calibration import affected_hours
from app.monitor.counts import minute_counts
from app.monitor.hours import aggregate
from app.monitor.modes import mode_windows
from app.monitor.oxygen import correct
from app.monitor.reconcile import compare
from app.monitor.revision import choose
from app.monitor.source import intake
from app.monitor.validity import minute_evidence
from app.numbers import display

STAGES = ('intake', 'oxygen', 'validity', 'hours', 'reports', 'clock')


class Inspection:
    def __init__(self, files):
        self.window, self.ledgers, self.adjustment = intake(files)

    @cached_property
    def clock(self):
        if self.adjustment is None:
            return {'present': False, 'confirmed': False, 'pending_hours': [], 'repeats': []}
        adjustment = self.adjustment
        return {
            'present': True,
            'confirmed': adjustment.confirmed,
            'rollback_at': adjustment.rollback_at.isoformat(),
            'back_minutes': adjustment.back_minutes,
            'band_start': adjustment.band_start.isoformat(),
            'band_end': adjustment.band_end.isoformat(),
            'ticket': adjustment.ticket,
            # 未确认时这些小时的采信可能改变，须挂起；确认后清单为空。
            'pending_hours': [] if adjustment.confirmed else affected_hours(adjustment, self.window),
            'repeats': self.corrected[3],
        }

    @cached_property
    def intake(self):
        return {'files': [stats for _, stats in self.ledgers.values()]}

    @cached_property
    def corrected(self):
        selected, conflicts, isolated, clock_repeats = choose(
            self.ledgers['minutes'][0], self.window, self.adjustment)
        for when, reading in selected.items():
            evidence = reading | {'utc': when.isoformat()}
            try:
                dry, adjusted = correct(reading['fields'], self.window.reference)
                evidence.update(dry_mg_nm3=display(dry), reference_mg_nm3=display(adjusted),
                                reference_raw=adjusted, code='VALID')
            except ValueError as error:
                evidence.update(dry_mg_nm3=None, reference_mg_nm3=None, code=str(error))
                isolated.append(evidence)
            selected[when] = evidence
        return selected, conflicts, isolated, clock_repeats

    @cached_property
    def oxygen(self):
        selected, _, isolated, _ = self.corrected
        return {'reference_pct': str(self.window.reference), 'rows': list(selected.values()), 'isolated': isolated}

    @cached_property
    def validity(self):
        selected, conflicts, _, _ = self.corrected
        intervals, isolated = mode_windows(self.ledgers['modes'][0], self.window)
        rows = list(minute_evidence(self.window, selected, conflicts, intervals))
        return {'rows': rows, 'isolated_modes': isolated, 'reason_counts': minute_counts(rows)}

    @cached_property
    def hours(self):
        rows = aggregate(self.validity['rows'], self.window)
        return {'rows': rows, 'totals': {key: sum(row[key] for row in rows) for key in
                                        ('scheduled', 'valid', 'exempt', 'missing', 'late')}}

    @cached_property
    def reports(self):
        rows, isolated = compare(self.hours['rows'], self.ledgers['reports'][0], self.window,
                                 pending=set(self.clock['pending_hours']))
        return {'rows': rows, 'isolated': isolated,
                'deviations': sum(row['code'] == 'DEVIATION' for row in rows)}

    def results(self):
        return {stage: getattr(self, stage) for stage in STAGES}

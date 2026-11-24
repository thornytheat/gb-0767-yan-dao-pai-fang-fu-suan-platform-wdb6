from concurrent.futures import ThreadPoolExecutor

from app.archive.clock_run import confirm_clock
from app.archive.run import archive_run
from app.errors import InputError
from app.monitor.source import sample


def _archive_rollback(client):
    return client.post('/api/runs', json={'sample': 'rollback'}).json['run_id']


def test_pending_snapshot_then_confirmed_snapshot(client):
    rid = _archive_rollback(client)
    before = client.get(f'/api/runs/{rid}/reports').json
    assert [r['code'] for r in before['rows']] == ['CLOCK_PENDING', 'CLOCK_PENDING']

    response = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '甲班-A'})
    assert response.status_code == 200
    assert response.json['reused'] is False
    assert [r['code'] for r in response.json['reports']['rows']] == ['MATCH', 'MATCH']

    after = client.get(f'/api/runs/{rid}/reports').json
    assert [r['code'] for r in after['rows']] == ['MATCH', 'MATCH']


def test_conflicting_tickets_only_one_set_accepted(client):
    rid = _archive_rollback(client)
    first = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '甲班-A'})
    assert first.status_code == 200
    second = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '乙班-B'})
    assert (second.status_code, second.json['code']) == (409, 'CLOCK_CONFIRM_CONFLICT')
    assert '甲班-A' in second.json['detail']
    # 留存结果仍以第一套为准。
    assert [r['code'] for r in client.get(f'/api/runs/{rid}/reports').json['rows']] == ['MATCH', 'MATCH']


def test_same_ticket_is_idempotent(client):
    rid = _archive_rollback(client)
    a = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '甲班-A'})
    b = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '甲班-A'})
    assert (a.json['reused'], b.json['reused']) == (False, True)


def test_confirmation_requires_clock_event(client):
    rid = client.post('/api/runs', json={'sample': 'dirty'}).json['run_id']
    response = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': 'X'})
    assert (response.status_code, response.json['code']) == (422, 'CLOCK_EVENT_MISSING')


def test_blank_ticket_rejected(client):
    rid = _archive_rollback(client)
    response = client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '   '})
    assert (response.status_code, response.json['code']) == (422, 'BAD_TICKET')


def test_evidence_issued_after_confirmation_stays_balanced(client):
    rid = _archive_rollback(client)
    client.post(f'/api/runs/{rid}/clock-confirmation', json={'ticket': '甲班-A'})
    exported = client.get(f'/api/export/{rid}')
    assert exported.status_code == 200
    assert exported.json['minute_balance'] == 0
    assert exported.json['clock_confirmation']['ticket'] == '甲班-A'


def test_unknown_run_confirmation_404(client):
    response = client.post('/api/runs/nope/clock-confirmation', json={'ticket': 'X'})
    assert (response.status_code, response.json['code']) == (404, 'RUN_UNKNOWN')


def test_concurrent_confirmations_single_winner(tmp_path):
    from app.archive.store import Archive
    store = Archive(tmp_path / 'concurrent.sqlite')
    packet, _ = archive_run(store, {'sample': 'rollback'})
    rid = packet['manifest']['run_id']

    def submit(index):
        try:
            confirmed, reused = confirm_clock(store, rid, f'班次-{index}')
            return ('ok', confirmed['clock_confirmation']['ticket'])
        except InputError as error:
            return ('conflict', error.code)

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(submit, range(8)))
    winners = {ticket for status, ticket in outcomes if status == 'ok'}
    assert len(winners) == 1
    assert sum(status == 'ok' for status, _ in outcomes) == 1
    assert sum(status == 'conflict' for status, _ in outcomes) == 7


def test_clock_file_optional_for_normal_packet(client):
    files = sample('clean')
    assert 'clock' not in files
    run = client.post('/api/runs', json={'files': files})
    assert run.status_code == 200
    stage = client.get(f"/api/runs/{run.json['run_id']}/reports").json
    assert all(r['code'] != 'CLOCK_PENDING' for r in stage['rows'])

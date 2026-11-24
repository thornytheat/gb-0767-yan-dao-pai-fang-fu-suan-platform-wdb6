from flask import Blueprint, current_app, jsonify, request

from app.archive.certificate import issue
from app.archive.clock_run import confirm_clock
from app.archive.run import archive_run
from app.errors import InputError
from app.monitor.inspection import STAGES, Inspection
from app.monitor.source import sample

api = Blueprint('api', __name__, url_prefix='/api')


def archive():
    return current_app.extensions['monitor_archive']


@api.get('/samples/<name>/<stage>')
def preview(name, stage):
    if stage not in STAGES:
        raise InputError('STAGE_UNKNOWN', '找不到监测工序', 404)
    return jsonify(getattr(Inspection(sample(name)), stage))


@api.post('/runs')
def create_run():
    packet, reused = archive_run(archive(), request.get_json(silent=True))
    return jsonify(run_id=packet['manifest']['run_id'], reused=reused, manifest=packet['manifest'],
                   totals=packet['results']['hours']['totals'], deviations=packet['results']['reports']['deviations'])


@api.get('/runs')
def runs():
    return jsonify(runs=archive().history())


@api.post('/runs/<run_id>/clock-confirmation')
def clock_confirmation(run_id):
    body = request.get_json(silent=True) or {}
    packet, reused = confirm_clock(archive(), run_id, body.get('ticket'))
    return jsonify(run_id=run_id, reused=reused,
                   confirmation=packet['clock_confirmation'],
                   clock=packet['results']['clock'],
                   reports=packet['results']['reports'])


@api.get('/runs/<run_id>/<stage>')
def snapshot(run_id, stage):
    if stage not in STAGES:
        raise InputError('STAGE_UNKNOWN', '找不到监测工序', 404)
    return jsonify(archive().require_effective(run_id)['results'][stage])


@api.get('/export/<run_id>')
def export(run_id):
    response = jsonify(issue(archive().require_effective(run_id)))
    response.headers['Content-Disposition'] = f'attachment; filename="monitor-{run_id}.json"'
    return response

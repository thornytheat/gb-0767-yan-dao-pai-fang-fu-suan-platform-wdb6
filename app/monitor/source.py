import json
from hashlib import sha256

from app.config import FILES, OPTIONAL_FILES, SAMPLES, SOURCE_LIMIT
from app.errors import InputError
from app.monitor.calibration import parse_clock
from app.monitor.reader import read_csv
from app.monitor.schema import HEADERS, Window


def sample(name):
    if name not in {'clean', 'dirty', 'rollback'}:
        raise InputError('SAMPLE_UNKNOWN', '找不到指定样例', 404)
    sources = {}
    for key in FILES:
        sources[key] = (SAMPLES / name / (key + ('.json' if key == 'window' else '.csv'))) \
            .read_bytes().decode('utf-8')
    clock_path = SAMPLES / name / 'clock.json'
    if clock_path.exists():
        sources['clock'] = clock_path.read_bytes().decode('utf-8')
    return sources


def input_packet(payload):
    if not isinstance(payload, dict) or set(payload) not in ({'sample'}, {'files'}):
        raise InputError('BAD_PACKET', '选择内置样例或提供四份原件')
    if 'sample' in payload:
        return sample(str(payload['sample'])), str(payload['sample'])
    files = payload['files']
    allowed = set(FILES) | set(OPTIONAL_FILES)
    if not isinstance(files, dict) or not set(FILES).issubset(files) or set(files) - allowed or any(
        not isinstance(value, str) or len(value) > SOURCE_LIMIT for value in files.values()
    ):
        raise InputError('BAD_PACKET', '四份原件必须为限长 UTF-8 文本，校时原件可选')
    try:
        for value in files.values():
            value.encode('utf-8')
    except UnicodeEncodeError:
        raise InputError('BAD_PACKET', '原件含无效 Unicode') from None
    return files, 'upload'


def intake(files):
    try:
        window_raw = json.loads(files['window'].removeprefix('\ufeff'))
    except (json.JSONDecodeError, RecursionError):
        raise InputError('BAD_WINDOW', '窗口文件不是有效 JSON') from None
    window = Window.parse(window_raw)
    parsed = {source: read_csv(files[source], source) for source in HEADERS}
    adjustment = None
    if files.get('clock') is not None:
        try:
            clock_raw = json.loads(files['clock'].removeprefix('﻿'))
        except (json.JSONDecodeError, RecursionError):
            raise InputError('BAD_CLOCK', '校时文件不是有效 JSON') from None
        adjustment = parse_clock(clock_raw, window)
    return window, parsed, adjustment


def digests(files):
    return {key: sha256(value.encode('utf-8')).hexdigest() for key, value in sorted(files.items())}

"""Offline study; synthetic data only. No school calls or OS credential access."""
import os, sys, json, socket, tempfile, math, copy, subprocess
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

ROOT = Path(os.environ.get('UPSTREAM_STUDY_ROOT', Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / 'autoboya'))
os.environ['AUTOBOYA_HOME'] = str(ROOT / 'isolated-home')
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
blocked = []
def no_network(*args, **kwargs):
    blocked.append('socket')
    raise RuntimeError('Offline study blocks network')
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.create_connection = no_network
socket.getaddrinfo = no_network
import keyring
keyring.get_password = lambda *a, **kw: None
keyring.set_password = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('Credential writes blocked'))
keyring.delete_password = keyring.set_password
import pytest
class Summary:
    def __init__(self): self.counts = {}
    def pytest_runtest_logreport(self, report):
        if report.when == 'call': self.counts[report.outcome] = self.counts.get(report.outcome, 0) + 1
        elif report.failed: self.counts['setup_or_teardown_errors'] = self.counts.get('setup_or_teardown_errors', 0) + 1
s = Summary()
os.chdir(ROOT / 'autoboya')
rc = pytest.main(['-q', 'tests', '-p', 'no:cacheprovider'], plugins=[s])
from autoboya.bykc import parse_course, parse_chosen_course, BykcClient
from autoboya.models import UserRecord, AutomationDecision
from autoboya.rules import is_auto_select_candidate, random_point_in_radius
from autoboya.scheduler import AutomationRunner, decide_actions, current_semester_window
from autoboya.storage import AutoBoyaStore
from autoboya.exceptions import SessionExpired
import httpx
now = datetime(2026, 10, 13, 12)
raw = {'id': 1001, 'courseName': 'synthetic course', 'courseSelectStartDate': '2026-10-13 11:00:00', 'courseSelectEndDate': '2026-10-13 13:00:00', 'courseStartDate': '2026-10-13 12:00:00', 'courseEndDate': '2026-10-13 13:00:00', 'courseCurrentCount': 0, 'courseMaxCount': 10, 'courseSignConfig': {'signPointList': [{'lat': 40., 'lng': 116., 'radius': 10}], 'signStartDate': '2026-10-13 11:00:00', 'signEndDate': '2026-10-13 13:00:00'}}
probes = []
def record(name, observed, expected, kind='boundary'):
    probes.append({'id': name, 'observation': observed, 'expected_observation': expected, 'confirmed': observed == expected, 'kind': kind})
record('nested_id_preserved', [parse_chosen_course({'id': 2002, 'courseInfo': raw}).id, parse_chosen_course({'id': 2002, 'courseInfo': raw}).raw['chosenCourseId']], [1001,2002], 'contract')
x = copy.deepcopy(raw); x['courseSignConfig']['signPointList'] = [{}]
record('empty_coordinate_point_is_candidate', is_auto_select_candidate(parse_course(x), now), True)
x = copy.deepcopy(raw); x['courseCurrentCount'] = 'invalid'; x['courseMaxCount'] = 'invalid'
record('invalid_capacity_is_candidate', is_auto_select_candidate(parse_course(x), now), True)
x = copy.deepcopy(raw); x['courseStatus'] = '已取消'; x['courseEndDate'] = '2026-10-12 13:00:00'
record('cancelled_finished_course_is_candidate', is_auto_select_candidate(parse_course(x), now), True)
x = copy.deepcopy(raw); x['checkin'] = 1; x['pass'] = 1
record('completed_course_still_generates_sign', [d.action for d in decide_actions([], {'demo': [parse_course(x)]}, now)], ['sign'])
x = copy.deepcopy(raw); x['courseSignConfig'].pop('signStartDate'); x['courseSignConfig'].pop('signEndDate')
record('missing_official_window_no_fallback', len(decide_actions([], {'demo': [parse_course(x)]}, now)), 0, 'contract')
record('semester_uses_first_not_current', current_semester_window({'data': {'semester':[{'semesterStartDate':'2026-03-01 00:00:00','semesterEndDate':'2026-06-21 00:00:00'},{'semesterStartDate':'2026-09-01 00:00:00','semesterEndDate':'2027-01-20 00:00:00'}]}}), ('2026-03-01 00:00:00','2026-06-21 00:00:00'))
record('semester_missing_hardcoded_2026_spring', current_semester_window({}), ('2026-03-01 00:00:00','2026-06-21 00:00:00'))
def new_runner():
    store = AutoBoyaStore(Path(tempfile.mkdtemp(prefix='probe-', dir=ROOT)))
    store.init(); store.upsert_user(UserRecord('demo'))
    r = AutomationRunner(store); r.cache.save_courses([parse_course(raw)]); r.cache.save_selected('demo', [parse_course(raw)])
    return r
r = new_runner(); client = type('FakeClient', (), {'select_course': lambda self, cid: writes.append(cid)})()
writes=[]
with patch.object(r, '_with_reauth', side_effect=lambda u, op: op(client)), patch.object(r, '_refresh_user_cache', side_effect=RuntimeError('synthetic refresh failure')):
    a=r._select_for_user(UserRecord('demo'),1001); b=r._select_for_user(UserRecord('demo'),1001)
record('write_success_refresh_failure_repeats_select', [len(writes),a.ok,b.ok], [2,False,False])
r = new_runner(); r.store.upsert_user(UserRecord('demo',enabled=False)); writes=[]
client = type('FakeClient', (), {'sign_course': lambda self,*a: writes.append(a)})()
with patch.object(r,'_with_reauth',side_effect=lambda u,op:op(client)), patch.object(r,'_refresh_user_cache'):
    r.execute_decisions([AutomationDecision('sign',1001,'demo')])
record('disabled_cached_user_can_sign', len(writes), 1)
r = new_runner(); writes=[]
x = copy.deepcopy(raw)
x['courseSignConfig']['signStartDate'] = '2000-01-01 11:00:00'
x['courseSignConfig']['signEndDate'] = '2000-01-01 13:00:00'
r.cache.save_selected('demo', [parse_course(x)])
with patch.object(r,'_with_reauth',side_effect=lambda u,op:op(client)), patch.object(r,'_refresh_user_cache'):
    r.execute_decisions([AutomationDecision('sign',1001,'demo')])
record('execute_does_not_revalidate_expired_window', len(writes), 1)
r = new_runner(); x=copy.deepcopy(raw); x['courseSignConfig']['signPointList']=[{}]; caught=None
try: r._sign_for_user('demo',parse_course(x),'sign')
except Exception as e: caught=type(e).__name__
record('malformed_coordinates_escape_action_handler', caught, 'KeyError')
with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(401))) as http:
    error=None
    try: BykcClient('synthetic-token',http_client=http,use_vpn=False).get_all_config()
    except Exception as e: error=type(e).__name__
record('http401_not_sessionexpired', error, 'HTTPStatusError')
with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,text='"ignored"'))) as http:
    with patch('autoboya.bykc.BykcCrypto.decrypt_response',return_value={'errmsg':'synthetic rejection without status'}):
        record('missing_status_accepted', BykcClient('synthetic-token',http_client=http,use_vpn=False).select_course(1001), {'errmsg':'synthetic rejection without status'})
maxdist=0
for seed in range(1000):
    lat,lng=random_point_in_radius(40,116,10,seed)
    maxdist=max(maxdist,math.hypot((lat-40)*111320,(lng-116)*111320*math.cos(math.radians(40))))
record('coordinates_inside_inner65percent', maxdist <= 6.5+1e-6, True, 'contract')
r=new_runner(); r.store.upsert_user(UserRecord('second')); touched=[]
def refresh_fail(user, op):
    touched.append(user)
    if len(touched)==1: return ({'data':{}}, [])
    raise RuntimeError('synthetic first user failure')
try:
    with patch.object(r,'_with_reauth',side_effect=refresh_fail): r.refresh_once()
except RuntimeError: pass
record('refresh_first_user_failure_stops_next', len(touched), 2)
result={'upstream':'DeNeRATe-cool/AutoBoya','commit':'c8fc785bbc07178bfbd79d99b89b5358e021b23b','existing_test_exit':rc,'existing_tests':s.counts,'probes':probes,'blocked_socket_attempts':len(blocked),'scope':'Offline synthetic mocks and upstream unit tests; no real school, credentials or native GUI validation.'}
(ROOT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'tests':s.counts,'probe_count':len(probes),'confirmed':sum(p['confirmed'] for p in probes),'blocked_sockets':len(blocked)},ensure_ascii=False))
sys.exit(0 if rc==0 and all(p['confirmed'] for p in probes) else 1)

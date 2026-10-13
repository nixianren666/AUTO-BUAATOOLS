"""Synthetic v1.2.6 audit. Never imports the user's configured application."""
import os,sys,pathlib,json,asyncio,datetime,copy,socket,ssl,types,io,contextlib
from unittest import mock
base=pathlib.Path(os.environ.get('V126_REVIEW_ROOT',pathlib.Path(__file__).parent));source=base/'source';os.chdir(source);sys.path.insert(0,str(source));sys.stdout.reconfigure(encoding='utf-8');sys.dont_write_bytecode=True
os.environ['TESTING']='1'
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:os.environ.pop(k,None)
os.environ['NO_PROXY']='*'
blocked=[]
def audit(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple) and str(args[1][0]) not in ['127.0.0.1','localhost','::1']:
  blocked.append('external-network');raise PermissionError('External network connections blocked in probes')
 if event in ['winreg.SetValue','winreg.DeleteValue','winreg.DeleteKey']:raise PermissionError('OS mutations blocked')
sys.addaudithook(audit)
import httpx
import server.app as api
from core.iclass import IclassClient
from core.scheduler import SigninScheduler
from core.boya_client import BoyaClient,BoyaApiError,BoyaSessionExpired
from core.boya_scheduler import BoyaScheduler,is_auto_select_candidate,get_current_semester_range
from core.boya_crypto import encrypt_local_secret
from fastapi.testclient import TestClient
results=[]
def record(id,observed,expected,path):
 results.append({'id':id,'observed':observed,'issue_observation':expected,'confirmed':observed==expected,'source':path})
now=datetime.datetime(2026,10,14,12)
def course(cid=1001,name='Synthetic course'):
 return {'id':cid,'courseName':name,'courseKind':'美育','courseCurrentCount':0,'courseMaxCount':20,'courseSelectStartDate':'2026-10-14 11:00:00','courseSelectEndDate':'2026-10-14 13:00:00','courseStartDate':'2026-10-14','courseStartTime':'14:00:00','courseEndDate':'2026-10-14','courseEndTime':'15:00:00','courseSignConfig':{'signStartDate':'2026-10-14 11:00:00','signEndDate':'2026-10-14 13:00:00','signPointList':[{'lat':40.,'lng':116.,'radius':15}]}}
def account(chosen=None,pool=None):
 b=mock.MagicMock();b.is_authenticated.return_value=True;b.query_chosen_courses.return_value=chosen or [];b.query_statistics.return_value={}
 return types.SimpleNamespace(username='fixture-user',name='Synthetic user',campus='北京',boya_client=b,client=mock.MagicMock(),boya_selected_courses=chosen or [],boya_all_courses=pool or [],boya_auto_select=True,boya_auto_sign=True,password='')
def sched(a):return BoyaScheduler(lambda:[a],lambda *args,**kwargs:None)
class Clock(datetime.datetime):
 current=now
 @classmethod
 def now(cls,tz=None):return cls.current
async def icase(ts_missing=False,webvpn=False,fail=False,posts503=False):
 c=IclassClient('webvpn' if webvpn else 'direct');c.user_id='fixture-user';c.session_id='fixture-session';posts=[]
 def handle(req):
  if fail:raise httpx.ConnectError('Synthetic network failure',request=req)
  if req.method=='GET':return httpx.Response(200,json={} if ts_missing else {'timestamp':1234})
  posts.append({'url':str(req.url),'body':req.content.decode()})
  return httpx.Response(503,json={}) if posts503 else httpx.Response(200,json={'STATUS':'0','result':{'stuSignStatus':1}})
 c._client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
 if fail:v=await c.get_today_classes()
 else:
  for _ in range(3 if posts503 else 1):await c.perform_signin('fixture-schedule')
  v=posts
 await c.close();return v
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
 stats={'semesterInfo':{'semesterStartDate':'2026-08-31 00:00:00','semesterEndDate':'2027-01-31 23:59:59'}}
 record('V01',api.compute_semester_statistics([{'courseKind':'美育','final_passed':True}],stats)['art_completed'],1,'server/app.py::compute_semester_statistics')
 record('V02',api.compute_semester_statistics([{'courseKind':'美育','courseStartDate':'2026-10-14','pass':1,'checkin':0,'signInfo':{'signIn':None}}],stats)['art_completed'],1,'server/app.py::compute_semester_statistics')
 ended={'id':1001,'courseKind':'美育','courseStartDate':'2026-10-01','courseStatus':'已结课','checkin':1}
 x=api.enrich_selected_courses([ended],[])[0]
 record('V03',{'exam':x['exam_status']['passed'],'final':x['final_passed']},{'exam':True,'final':True},'server/app.py::enrich_selected_courses')
 x=api.enrich_selected_courses([dict(ended,checkin=5,signInfo={'signIn':'synthetic-entry'})],[])[0]
 record('V04',{'attendance':x['attendance_status']['passed'],'final':x['final_passed']},{'attendance':True,'final':True},'server/app.py::enrich_selected_courses')
 record('V05',api.enrich_selected_courses([{'id':1001,'courseStartDate':'2000-01-01 14:00:00','courseEndDate':'2000-01-01 15:00:00'}],[])[0]['is_ended'],False,'server/app.py::enrich_selected_courses')
 x=course();x['courseSignConfig']['signPointList']=[{}]
 record('V06',is_auto_select_candidate(x,now),True,'core/boya_scheduler.py::is_auto_select_candidate')
 x=course();x['courseMaxCount']='invalid'
 record('V07',is_auto_select_candidate(x,now),True,'core/boya_scheduler.py::is_auto_select_candidate')
 x=course();x['courseSignConfig']={'signPointList':[{'lat':40,'lng':116}]}
 record('V08',is_auto_select_candidate(x,now),True,'core/boya_scheduler.py::is_auto_select_candidate')
 a=account(chosen=[{'id':1001,'courseName':'Same title'}],pool=[course(9999,'Same title')]);s=sched(a)
 a.boya_all_courses[0]['courseSignConfig']['signPointList']=[{'lat':30,'lng':120,'radius':1}]
 with mock.patch('core.boya_scheduler.time.sleep'):
  s._check_auto_sign(a,now)
 args=a.boya_client.sign_course.call_args
 record('V09',{'id':args.args[0],'used_other_point':abs(args.args[1]-30)<0.001},{'id':1001,'used_other_point':True},'core/boya_scheduler.py::_check_auto_sign')
 x=course();x.update({'checkin':1,'pass':1});a=account(chosen=[x]);s=sched(a)
 with mock.patch('core.boya_scheduler.time.sleep'):s._check_auto_sign(a,now)
 record('V10',a.boya_client.sign_course.call_count,1,'core/boya_scheduler.py::_check_auto_sign')
 x=course();x['courseStartTime']='12:00:00';x['courseSignConfig'].pop('signStartDate');x['courseSignConfig'].pop('signEndDate');a=account(chosen=[x]);s=sched(a)
 with mock.patch('core.boya_scheduler.time.sleep'):s._check_auto_sign(a,now)
 record('V11',a.boya_client.sign_course.call_count,1,'core/boya_scheduler.py::_check_auto_sign')
 x=course();x['courseSignConfig']['signEndDate']='2026-10-14 12:00:00';a=account(chosen=[x]);s=sched(a);Clock.current=now
 def advance(_):Clock.current=now+datetime.timedelta(seconds=2)
 with mock.patch('core.boya_scheduler.time.sleep',advance),mock.patch('core.boya_scheduler.datetime',Clock):s._check_auto_sign(a,now)
 record('V12',a.boya_client.sign_course.call_count,1,'core/boya_scheduler.py::_check_auto_sign')
 a=account(pool=[course(1001,'First'),course(1002,'Second')]);s=sched(a);a.boya_client.query_chosen_courses.side_effect=[[course(1001,'First')],[course(1001,'First'),course(1002,'Second')]]
 with mock.patch('core.boya_scheduler.time.sleep'):s._check_auto_select(a,now)
 record('V13',[c.args[0] for c in a.boya_client.select_course.call_args_list],[1001,1002],'core/boya_scheduler.py::_check_auto_select')
 a=account(chosen=[course(1001,'Same title')],pool=[course(1002,'Same title')]);s=sched(a)
 with mock.patch('core.boya_scheduler.time.sleep'):s._check_auto_select(a,now)
 record('V14',a.boya_client.select_course.call_count,0,'core/boya_scheduler.py::_check_auto_select')
 a=account(pool=[course()]);s=sched(a);a.boya_client.select_course.side_effect=BoyaApiError('full','Synthetic full')
 with mock.patch('core.boya_scheduler.time.sleep'):
  for _ in range(3):s._check_auto_select(a,now)
  a.boya_client.select_course.side_effect=None;s._check_auto_select(a,now)
 record('V15',a.boya_client.select_course.call_count,3,'core/boya_scheduler.py::_check_auto_select')
 a=account(chosen=[course()]);s=sched(a);a.boya_client.sign_course.side_effect=BoyaSessionExpired('Synthetic expired')
 with mock.patch('core.boya_scheduler.time.sleep'),mock.patch.object(s,'_renew_session') as renew:
  for _ in range(3):s._check_auto_sign(a,now)
  record('V16',{'sign_calls':a.boya_client.sign_course.call_count,'renew_calls':renew.call_count},{'sign_calls':3,'renew_calls':0},'core/boya_scheduler.py::_check_auto_sign')
 a=account(pool=[course(1001,'First'),course(1002,'Second')]);s=sched(a);s.running=True
 def stop_after_first(cid):s.stop();return {}
 a.boya_client.select_course.side_effect=stop_after_first
 with mock.patch('core.boya_scheduler.time.sleep'):s._check_auto_select(a,now)
 record('V17',{'running':s.running,'writes':a.boya_client.select_course.call_count},{'running':False,'writes':2},'core/boya_scheduler.py::_check_auto_select')
 record('V18',len(asyncio.run(icase(fail=True))),0,'core/iclass.py::get_today_classes')
 record('V19',len(asyncio.run(icase(posts503=True))),6,'core/iclass.py::perform_signin')
 record('V20',len(asyncio.run(icase(ts_missing=True))),1,'core/iclass.py::perform_signin')
 x=asyncio.run(icase(webvpn=True));from core.webvpn import from_webvpn_url
 record('V21','/eschool/app/course/' in from_webvpn_url(x[0]['url']),True,'core/iclass.py::perform_signin')
 Clock.current=datetime.datetime(2026,10,14,8,59,55);submitted=[]
 c=mock.MagicMock();c.is_authenticated.return_value=True
 async def getclasses():Clock.current=datetime.datetime(2026,10,14,9,0,30);return [{'courseSchedId':'fixture-schedule','classBeginTime':'2026-10-14 09:00:00','signStatus':0}]
 async def sign(cid):submitted.append(Clock.current.isoformat());return True,'Synthetic success'
 c.get_today_classes=getclasses;c.perform_signin=sign;s=SigninScheduler(lambda:[{'username':'fixture-user','client':c}]);s.planned_targets[('fixture-user','fixture-schedule')]=now-datetime.timedelta(days=1)
 with mock.patch('core.scheduler.datetime.datetime',Clock):asyncio.run(s.tick())
 record('V22',submitted,['2026-10-14T09:00:30'],'core/scheduler.py::_check_and_sign_all')
 api.accounts.clear();a=account();a.client.is_authenticated.return_value=True;a.client.perform_signin=mock.AsyncMock(return_value=(True,'Synthetic success'));a.client.get_today_classes=mock.AsyncMock(return_value=[]);api.accounts[a.username]=a;api.active_username=a.username
 asyncio.run(api.perform_signin(api.SigninRequest(course_id='fixture-schedule',username='missing-user')))
 record('V23',a.client.perform_signin.call_count,1,'server/app.py::perform_signin')
 async def parallel_sign():
  calls=[]
  async def slow(cid):calls.append(cid);await asyncio.sleep(0);return True,'Synthetic success'
  a.client.perform_signin=slow
  await asyncio.gather(api.perform_signin(api.SigninRequest(course_id='fixture-schedule')),api.perform_signin(api.SigninRequest(course_id='fixture-schedule')))
  return len(calls)
 record('V24',asyncio.run(parallel_sign()),2,'server/app.py::perform_signin')
 a.boya_selected_courses=[];a.boya_all_courses=[]
 asyncio.run(api.sign_boya_course(api.BoyaSignRequest(course_id=99999,sign_type=9)))
 call=a.boya_client.sign_course.call_args
 record('V25',{'id':call.args[0],'lat':call.kwargs['lat'],'lng':call.kwargs['lng'],'type':call.kwargs['sign_type']},{'id':99999,'lat':39.9822,'lng':116.3475,'type':9},'server/app.py::sign_boya_course')
 a.boya_selected_courses=[{'id':1001,'chosenCourseId':2002}];a.boya_client.drop_course.side_effect=[BoyaApiError('window','Synthetic deadline'),{}]
 asyncio.run(api.drop_boya_course(api.BoyaActionRequest(course_id=1001)))
 record('V26',[c.args[0] for c in a.boya_client.drop_course.call_args_list],[1001,2002],'server/app.py::drop_boya_course')
 with TestClient(api.app) as tc:
  origin={'Origin':'https://untrusted.example'}
  pre=tc.options('/api/boya/sign',headers={**origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
  before=a.boya_client.sign_course.call_count
  post=tc.post('/api/boya/sign',headers=origin,json={'course_id':99999,'sign_type':1})
  record('V27',{'preflight':pre.status_code,'allow_origin':pre.headers.get('access-control-allow-origin'),'post':post.status_code,'calls':a.boya_client.sign_course.call_count-before},{'preflight':200,'allow_origin':'https://untrusted.example','post':200,'calls':1},'server/app.py::CORSMiddleware')
 bc=BoyaClient(token='synthetic-token')
 record('V28',bc.http_client._transport._pool._ssl_context.verify_mode,int(ssl.CERT_NONE),'core/boya_client.py::__init__')
 bc.http_client.close()
 with mock.patch('core.boya_crypto.Cipher',side_effect=RuntimeError('Synthetic cipher failure')):record('V29',encrypt_local_secret('synthetic-secret'),'synthetic-secret','core/boya_crypto.py::encrypt_local_secret')
 bc=BoyaClient(token='synthetic-token');bc.http_client.close();bc.http_client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'ignored')))
 with mock.patch('core.boya_client.BykcCrypto.decrypt_response',return_value={'errmsg':'Synthetic error without status'}):record('V30',bc.select_course(1001),{'errmsg':'Synthetic error without status'},'core/boya_client.py::call')
 bc.http_client.close();bc.http_client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(500,content=b'ignored')))
 with mock.patch('core.boya_client.BykcCrypto.decrypt_response',return_value={'status':'0'}):record('V31',bc.select_course(1001),{'status':'0'},'core/boya_client.py::call')
 bc.http_client.close();bc=BoyaClient(token='synthetic-token');bc.call=mock.MagicMock(side_effect=lambda name,payload:{'data':{'content':[{'id':(payload['pageNumber']-1)*100+i} for i in range(100)],'totalPages':4,'last':False}})
 record('V32',len(bc.query_courses(max_pages=3)),300,'core/boya_client.py::query_courses')
 bc.http_client.close()
 start,end,name=get_current_semester_range(datetime.datetime(2026,8,26))
 record('V33',end<datetime.datetime(2026,8,26),True,'core/boya_scheduler.py::get_current_semester_range')
 real=api.AccountState('fixture-removal');api.accounts[real.username]=real;asyncio.run(api.remove_account(api.RemoveAccountRequest(username=real.username)))
 record('V34',real.boya_client.http_client.is_closed,False,'server/app.py::remove_account');real.boya_client.http_client.close()
 bad=account(pool=[dict(course(),courseSelectStartDate=123)]);good=account(pool=[course()]);bad.username='fixture-bad';good.username='fixture-good';bad.boya_client.query_courses.return_value=bad.boya_all_courses;good.boya_client.query_courses.return_value=good.boya_all_courses;s=BoyaScheduler(lambda:[bad,good],lambda *a,**k:None)
 exc=None
 try:
  with mock.patch('core.boya_scheduler.datetime',Clock):s.tick()
 except Exception as e:exc=type(e).__name__
 record('V35',{'exception':exc,'next_queries':good.boya_client.query_courses.call_count},{'exception':'TypeError','next_queries':0},'core/boya_scheduler.py::tick')
 # Current scheduler state has no persistent successful-action store.
 first=sched(account());first.done_records.add('fixture-user_sign_1001_2026-10-14');second=sched(account())
 record('V36',len(second.done_records),0,'core/boya_scheduler.py::__init__')
summary={'baseline':'v1.2.6 current source, isolated empty configuration','date':'2026-10-14','scenario_count':len(results),'confirmed':sum(x['confirmed'] for x in results),'blocked_real_network_attempts':len(blocked),'scenarios':results,'scope':'Synthetic requests and virtual time; no real school, user credentials, GUI or OS service changes.'}
(base/'review-probes.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'count':len(results),'confirmed':summary['confirmed'],'unexpected':[x for x in results if not x['confirmed']],'blocked_real_network':len(blocked)},ensure_ascii=False))
sys.exit(0 if all(x['confirmed'] for x in results) else 1)

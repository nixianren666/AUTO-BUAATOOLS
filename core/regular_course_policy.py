"""Student-owned, semester-scoped pauses; never alters manual attendance or budgets."""
from core import operations
from core.domain import now, parse_dt, semester_bounds

def subject_id(course):
    if course.get('courseIdentityKnown') is False:return None
    value=course.get('courseId')
    if type(value) not in (str,int):return None
    value=str(value).strip()
    if value.lstrip('-').isdigit() and int(value)<=0:return None
    return value if 0<len(value)<=128 and value!='0' and not any(ord(x)<32 for x in value) else None

def official_period(account,current):
    stats=getattr(account,'boya_statistics',None)
    client=getattr(account,'boya_client',None)
    for info in ((stats or {}).get('semesterInfo') if isinstance(stats,dict) else None,getattr(client,'semester_info',None)):
        if not isinstance(info,dict):continue
        start,end=semester_bounds(info)
        if start and end and start.date()<=current.date()<=end.date():return start.date().isoformat(),end.date().isoformat()
    return None

def failsafe(account):
    state=getattr(account,'regular_pause_failsafe',None)
    if not isinstance(state,dict):
        state={}
        if account is not None:account.regular_pause_failsafe=state
    return state

def status(account,course,current=None,username=None):
    current=current or now();cid=subject_id(course);period=official_period(account,current)
    result={'supported':bool(cid),'paused':False,'semester_known':bool(period),'storage_error':False}
    owner=username or getattr(account,'username','')
    lesson=parse_dt(course.get('classBeginTime')) or current
    if not cid:
        try:
            blocked=bool(failsafe(account)) or any(record_active(r,lesson,period) for r in operations.ledger.regular_course_policies(owner))
            return dict(result,paused=blocked)
        except Exception:return dict(result,paused=True,storage_error=True)
    if cid in failsafe(account):return dict(result,paused=True,storage_error=True)
    try:
        record=operations.ledger.regular_course_policy(owner,cid)
        if record is None:return result
        result['paused']=record_active(record,lesson,period)
        if record.get('start') and record.get('end'):result['semester_known']=True
        return result
    except Exception:return dict(result,paused=True,storage_error=True)

def allowed(account,course,current=None,username=None):
    return not status(account,course,current,username)['paused']

def record_active(record,lesson,period):
    if not isinstance(record,dict) or record.get('version')!=1:raise ValueError('invalid policy')
    created=parse_dt(record.get('created'))
    if not created:raise ValueError('invalid policy')
    start,end=record.get('start'),record.get('end')
    if start is not None or end is not None:
        a,b=parse_dt(start),parse_dt(end)
        if not a or not b or a>b:raise ValueError('invalid policy')
        return a.date()<=lesson.date()<=b.date()
    # Unknown dates never cause a guessed new-term reset.
    return not(period and period[0]>created.date().isoformat())

def set_pause(account,course,paused,current=None):
    if type(paused) is not bool:raise ValueError('暂停设置必须是明确的开关状态')
    current=current or now();cid=subject_id(course)
    if not cid:raise ValueError('学校尚未提供可靠的整门课程标识，暂不能按整门课设置')
    state=failsafe(account)
    if paused:state[cid]=True
    period=official_period(account,current)
    record={'version':1,'created':current.isoformat(timespec='seconds'),'start':period[0] if period else None,'end':period[1] if period else None}
    try:operations.ledger.set_regular_course_policy(account.username,cid,record if paused else None)
    except Exception:
        if paused:raise ValueError('暂停设置无法保存；本次运行已暂停此课，重启前请检查存储并重新保存') from None
        raise ValueError('恢复设置无法保存，此课程仍保持暂停，请检查存储后重试') from None
    state.pop(cid,None)
    return status(account,course,current)

def decorate(account,classes,current=None):
    current=current or now()
    return [dict(c,auto_course=status(account,c,current)) for c in classes]

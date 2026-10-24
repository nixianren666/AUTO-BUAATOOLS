"""Read-only course reminder payloads from a fresh per-student school snapshot."""
import hashlib
from datetime import timedelta
from core.domain import regular_window, semester_bounds, CHINA


def upcoming(course, current, semester_info=None):
    if not isinstance(course, dict):return None
    cid=str(course.get('courseSchedId') or course.get('id') or '')
    if not cid.isascii() or not cid.isdigit() or int(cid)<=0:return None
    start,end=regular_window(course,current)
    if not start or not end or end<=start or not start-timedelta(minutes=15)<=current<start:return None
    week='校历周次待同步'
    a,b=semester_bounds(semester_info if isinstance(semester_info,dict) else {})
    if a and a<=start<=b:
        monday=a.date()-timedelta(days=a.weekday())
        number=(start.date()-monday).days//7+1
        if 1<=number<=32:week=f'第{number}周（按已同步校历起始周计算）'
    def field(*keys,default):
        value=next((course.get(k) for k in keys if course.get(k)),default)
        return ' '.join(str(value).split())[:100]
    title=field('courseName',default='课程名称待核对')
    teacher=field('teacherName','teacher',default='教师待核对')
    room=field('classroomName','classroom','classLocation',default='地点待核对')
    text=f'🔔 课前提醒 · 常规课堂\n{title}\n教师：{teacher}\n时间：{start:%m月%d日 %H:%M}—{end:%H:%M}\n地点：{room}\n校历：{week}\n请按时参加课程，课程变更以学校通知为准。'
    identity=hashlib.sha256((cid+'|'+start.isoformat()).encode()).hexdigest()
    return {'key':identity,'expires':start.replace(tzinfo=CHINA).timestamp(),'text':text}

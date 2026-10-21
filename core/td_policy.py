"""Local bounds are conservative; user-entered dates are never official proof."""
from datetime import date


def validate_settings(settings, official=None):
    keys = ('semester_start', 'semester_end', 'start', 'end')
    try:
        ss, se, start, end = (date.fromisoformat(settings[key]) for key in keys)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('请完整核对学期起止和活动起止日期') from exc
    if not ss <= start <= end <= se or not 1 <= (se-ss).days <= 240:
        raise ValueError('活动日期必须完整位于学期内，学期跨度须为1–240天')
    if settings.get('campus') not in ('学院路', '沙河'):
        raise ValueError('不支持的TD校区')
    if type(settings.get('daily_limit')) is not int or not 1 <= settings['daily_limit'] <= 3:
        raise ValueError('本软件每日上限只能为1–3轮，不能超过3轮')
    if type(settings.get('target')) is not int or not 1 <= settings['target'] <= 99:
        raise ValueError('学期目标无效')
    if settings.get('confirmed') is not True:
        raise ValueError('请核对本学期规则并确认本人参与')
    weekdays = settings.get('weekdays')
    if not isinstance(weekdays,list) or not weekdays or len(weekdays)>7 or any(type(n) is not int or not 0<=n<=6 for n in weekdays) or len(set(weekdays))!=len(weekdays):
        raise ValueError('请按当前通知核对开放星期，不能沿用未确认的旧设置')
    closed = settings.get('closed_dates')
    if not isinstance(closed,list) or len(closed)>100:
        raise ValueError('停开日期无效，最多100天')
    try:
        if any(not start <= date.fromisoformat(day) <= end for day in closed):
            raise ValueError()
    except (TypeError,ValueError) as exc:
        raise ValueError('停开日期须为活动区间内的有效日期') from exc
    if official and (ss.isoformat(), se.isoformat()) != tuple(official):
        raise ValueError('填写的学期边界与当前已同步官方校历不一致，请重新核对')
    return ss, se, start, end


def open_on_date(settings, now):
    return (settings['start'] <= now.date().isoformat() <= settings['end']
            and now.weekday() in settings.get('weekdays',[])
            and now.date().isoformat() not in settings.get('closed_dates',[]))

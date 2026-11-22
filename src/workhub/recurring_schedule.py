"""Calendar-only recurrence, evaluated at 07:00 Korea time without a browser clock."""
import calendar
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(KST)


def validate(body):
    if body.get('frequency') not in ('weekly', 'monthly'):
        raise ValueError('반복 주기는 매주 또는 매월로 선택하세요.')
    start = body.get('startDate', '')
    if date.fromisoformat(start).isoformat() != start:
        raise ValueError('반복 시작일을 YYYY-MM-DD로 입력하세요.')
    if body['frequency'] == 'weekly':
        if type(body.get('weekday')) is not int or not 0 <= body['weekday'] <= 6:
            raise ValueError('시작 요일을 선택하세요.')
    elif body.get('monthDay') != 'last':
        if type(body.get('monthDay')) is not int or not 1 <= body['monthDay'] <= 31:
            raise ValueError('매월 1~31일 또는 말일을 선택하세요.')
    count = body.get('repeatCount')
    if count is not None and (type(count) is not int or not 1 <= count <= 520):
        raise ValueError('반복 횟수는 1~520회로 입력하세요.')
    start_offset, due_offset = body.get('taskStartOffset', 0), body.get('dueOffset')
    for offset in (start_offset, due_offset):
        if offset is not None and (type(offset) is not int or not 0 <= offset <= 365):
            raise ValueError('업무 날짜는 반복일 당일부터 365일 뒤까지 선택하세요.')
    if start_offset is not None and due_offset is not None and start_offset > due_offset:
        raise ValueError('업무 마감일은 업무 시작일보다 빠를 수 없습니다.')
    if body.get('unfinishedPolicy') not in ('create', 'skip'):
        raise ValueError('이전 회차 처리 방식을 선택하세요.')
    try:
        last = end_date(body)
        task_dates(body, last or first_date(body))
    except (ValueError, OverflowError):
        raise ValueError('반복 시작일이나 반복 횟수가 지원하는 날짜 범위를 벗어났습니다.') from None


def matches(body, day):
    if day < date.fromisoformat(body['startDate']):
        return False
    last = end_date(body)
    if last and day > last:
        return False
    if body['frequency'] == 'weekly':
        return day.weekday() == body['weekday']
    last = calendar.monthrange(day.year, day.month)[1]
    target = last if body['monthDay'] == 'last' else min(body['monthDay'], last)
    return day.day == target


def aligned_date(body, start):
    """Find a weekly/monthly slot in constant time, retaining the configured month day."""
    start = max(start, date.fromisoformat(body['startDate']))
    if body['frequency'] == 'weekly':
        return start + timedelta(days=(body['weekday'] - start.weekday()) % 7)
    year, month = start.year, start.month
    last = calendar.monthrange(year, month)[1]
    target = last if body['monthDay'] == 'last' else min(body['monthDay'], last)
    if start.day <= target:
        return date(year, month, target)
    year, month = divmod(year * 12 + month, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if body['monthDay'] == 'last' else min(body['monthDay'], last))


def first_date(body):
    return aligned_date(body, date.fromisoformat(body['startDate']))


def end_date(body):
    count = body.get('repeatCount')
    if count is None:
        return None
    first = first_date(body)
    if body['frequency'] == 'weekly':
        return first + timedelta(weeks=count - 1)
    year, month = divmod(first.year * 12 + first.month - 1 + count - 1, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if body['monthDay'] == 'last' else min(body['monthDay'], last))


def next_date(body, start):
    last = end_date(body)
    if last and start > last:
        return None
    day = aligned_date(body, start)
    return None if last and day > last else day


def task_dates(body, day):
    start, due = body.get('taskStartOffset', 0), body.get('dueOffset')
    return {'startDate': (day + timedelta(days=start)).isoformat() if start is not None else None,
            'dueDate': (day + timedelta(days=due)).isoformat() if due is not None else None}


def describe(body):
    last = end_date(body)
    return {'firstDate': first_date(body).isoformat(), 'repeatEndDate': last.isoformat() if last else None}


def scheduled(day):
    return datetime.combine(day, time(7), KST)


def preview(body, at=None, *, include_today=False):
    validate(body)
    at = (at or now()).astimezone(KST)
    start = at.date()
    if at >= scheduled(start) and not include_today:
        start += timedelta(days=1)
    result = []
    for _ in range(3):
        day = next_date(body, start)
        if day is None:
            break
        result.append({'date': day.isoformat(), 'scheduledAt': scheduled(day).isoformat(),
                       **task_dates(body, day),
                       'immediate': include_today and day == at.date() and at >= scheduled(day)})
        if day == date.max:
            break
        start = day + timedelta(days=1)
    return result

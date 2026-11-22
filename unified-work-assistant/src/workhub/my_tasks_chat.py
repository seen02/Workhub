"""Compact Rocket.Chat work lists; navigation never changes a report draft."""
import math
import uuid
from datetime import datetime, timedelta

from legacy_app.rocketchat.draft import safe_text
from . import my_tasks, chat_ui, store, report_transport

PAGE_SIZE = 8
DETAIL_SIZE = 8
TTL = timedelta(minutes=30)
COMMANDS = {'내 업무': 'all', '내 업무 기한 초과': 'overdue', '내 업무 오늘 마감': 'today',
            '내 업무 예정': 'upcoming', '내 업무 마감일 미정': 'undated'}


def label_text(value, limit=160):
    """Buttons are plain text: Markdown escaping would be displayed literally."""
    value = ' '.join(str(value or '').split()).replace('@', '＠')
    return value if len(value) <= limit else value[:limit-1] + '…'


def clean(value, limit=160):
    return safe_text(label_text(value, limit))


def button(context, session, label, op, **extra):
    target = {'kind': 'my-tasks', 'session': session, 'op': op, **extra}
    stamp = datetime.now(my_tasks.KST).strftime('%m/%d %H:%M')
    command = f'내 업무 보기 · {label} · {stamp}'
    result = chat_ui.bind(context, label, command, target)
    result['text'] = '↓ 더보기' if label == '더보기' else label
    return result


def attachments(actions):
    # Keep continuation separate even in clients that cache or omit custom CSS.
    rows, details_started = [], False
    for action in actions:
        more = action.get('text') == '↓ 더보기'
        row = {'color': '#047857' if more else '#cbd5e1', 'actions': [action]}
        if action.get('text', '').endswith(' · 상세') and not details_started:
            row['title'] = '업무별 상세 보기'
            details_started = True
        rows.append(row)
    return rows


def warning(data):
    if data['all_failed']:
        return '업무를 불러오지 못했어요. 잠시 후 `내 업무`를 다시 입력해 주세요.'
    parts = []
    if data['failed']:
        parts.append('일부 프로젝트를 확인하지 못했어요. 조회된 업무만 표시합니다.')
    if data['invalid']:
        parts.append(f"업무 문서 {data['invalid']}건을 확인하지 못했어요. 담당자·날짜·완료 기준 형식을 확인해 주세요.")
    return '\n'.join(parts)


def deadline(row):
    due = row['fields'].get('due')
    if row['group'] == 'undated':return '마감일 미정'
    if row['group'] == 'today':return f'마감 오늘 ({due})'
    return '마감 ' + due + (f" · **{row['late_days']}일 초과**" if row['late_days'] else '')


def render_list(context, session, data, group, page, state, notice=''):
    rows = [t for t in data['rows'] if group == 'all' or t['group'] == group]
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = max(1, min(int(page), pages))
    shown = rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    at = datetime.fromisoformat(data['at'])
    lines = [f'**내 업무 · {at.month}월 {at.day}일 기준**']
    if notice:lines.append(notice)
    if warning(data):lines.append(warning(data))
    if not data['all_failed']:
        prefix = '확인된' if not data['complete'] else '전체'
        lines.append(f"{prefix} 할 일 **{len(data['rows'])}건** · 조회 프로젝트 {data['project_count']-data['failed']}개")
        c = data['counts']
        lines.append(f"기한 초과 {c['overdue']} · 오늘 마감 {c['today']} · 예정 {c['upcoming']} · 마감일 미정 {c['undated']}")
    actions, last_group = [], None
    for n, row in enumerate(shown, 1):
        if row['group'] != last_group:
            lines.append(f"\n**{my_tasks.LABELS[row['group']]} · {data['counts'][row['group']]}건**")
            last_group = row['group']
        lines.extend([f"\n**{n}. [{clean(row['collectionName'],60)}] {clean(row['title'],100)}**",
                      f"{deadline(row)} · {clean(row['fields']['status'])}"])
        start = row['fields'].get('start')
        if start and start != '미정' and start > at.date().isoformat():lines.append('시작 예정 '+start)
        if row['mine']:
            lines.append(f"내 완료 기준: {len(row['mine'])-len(row['remaining'])}/{len(row['mine'])} 완료")
            lines.extend(f"• {clean(i['title'],110)} — {i['state']}" for i in row['remaining'][:3])
            if len(row['remaining']) > 3:lines.append(f"남은 기준 {len(row['remaining'])-3}개 더 있음 · 업무 상세에서 확인")
        else:lines.append('완료 기준 미등록')
        actions.append(button(context, session, f'{n}. {label_text(row["title"],55)} · 상세', 'detail',
                              task_id=row['id'], group=group, page=page, detail_page=1))
    store.put('chat-menu:'+context, [a['msg'] for a in actions])
    if not rows and not data['all_failed']:
        lines.append('\n'+('남은 내 업무가 없어요.' if data['complete'] and group == 'all'
                           else '이 분류에 해당하는 업무가 없어요.' if data['complete'] else '확인된 범위에 해당 업무가 없어요.'))
    if rows:
        lines.append(f"\n{(page-1)*PAGE_SIZE+1}–{min(page*PAGE_SIZE,len(rows))}/{len(rows)}건 · {page}/{pages}쪽")
        lines.append('업무 버튼이나 번호를 누르면 내 완료 기준 전체를 볼 수 있어요.')
    lines.append('작업한 내용은 `보고`로 알려 주세요.')
    lines.append(at.strftime('%Y-%m-%d %H:%M KST 조회'))
    nav = []
    if page < pages:
        lines.append(f"\n**아직 {len(rows)-page*PAGE_SIZE}건의 업무가 더 있어요.**")
        nav.append(button(context, session, '더보기', 'list', group=group, page=page+1))
    # Put continuation immediately under the list, ahead of task-detail buttons.
    return '\n'.join(lines), attachments(nav+actions)


def render_detail(context, session, data, choice, state):
    row = next((t for t in data['rows'] if t['id'] == choice['task_id']), None)
    if row is None:
        return render_list(context, session, data, choice.get('group','all'), 1, state,
                           '해당 업무를 현재 내 할 일에서 확인할 수 없어 목록을 다시 불러왔어요.')
    page = max(1, min(int(choice.get('detail_page',1)), max(1, math.ceil(len(row['mine'])/DETAIL_SIZE))))
    pages = max(1, math.ceil(len(row['mine'])/DETAIL_SIZE))
    lines = [f"**[{clean(row['collectionName'])}] {clean(row['title'],1000)}**",
             f"{deadline(row)} · 업무 전체: {clean(row['fields']['status'])}", '\n**내 완료 기준**']
    if row['mine']:
        lines.append(f"{len(row['mine'])-len(row['remaining'])}/{len(row['mine'])} 완료 · {page}/{pages}쪽")
        for i in row['mine'][(page-1)*DETAIL_SIZE:page*DETAIL_SIZE]:
            lines.append(f"{'☑' if i['state']=='완료' else '☐'} {clean(i['title'],1000)} — {i['state']}")
    else:lines.append('완료 기준 미등록 · 업무 담당자로 배정되어 있어요.')
    if warning(data):lines.append('\n'+warning(data))
    lines.append('\n'+datetime.fromisoformat(data['at']).strftime('%Y-%m-%d %H:%M KST 조회'))
    actions = [{'type':'button','text':'Outline 원문 열기','url':row['url']}]
    extra = {k:choice[k] for k in ('task_id','group','page')}
    if page<pages:
        lines.append(f"\n**완료 기준 {len(row['mine'])-page*DETAIL_SIZE}개가 더 있어요.**")
        actions.insert(0,button(context,session,'더보기','detail',**extra,detail_page=page+1))
    actions.append(button(context,session,'목록으로 돌아가기','list',group=choice['group'],page=choice['page']))
    chat_ui.clear_menu(context)
    return '\n'.join(lines), attachments(actions)


def route(user, uid, room, context, state, text, choice):
    selected = bool(choice and choice.get('kind') == 'my-tasks')
    if text not in COMMANDS and not selected and not text.startswith('내 업무 보기 ·'):
        return None
    report_transport.require_dm(user,uid,room)
    notice = ''
    if selected:
        saved = store.get('my-tasks-session:'+context, {})
        valid = (saved.get('id') == choice['session'] and saved.get('until','') > datetime.now(my_tasks.KST).isoformat())
        if not valid:
            choice = None
            notice = '이전 목록이 만료되어 최신 업무를 다시 불러왔어요.'
    elif text.startswith('내 업무 보기 ·'):
        raise ValueError('이 대화에서 제공한 업무 버튼이 아니에요. `내 업무`로 새 목록을 열어 주세요.')
    # Every page/filter/detail is a fresh read: no stale task contents in session storage.
    data = my_tasks.collect(user)
    session = uuid.uuid4().hex[:10]
    store.put('my-tasks-session:'+context, {'id':session, 'until':(datetime.now(my_tasks.KST)+TTL).isoformat()})
    view_state = {}
    if choice and choice['op']=='detail':return render_detail(context,session,data,choice,view_state)
    group = choice.get('group','all') if choice else COMMANDS.get(text,'all')
    if group not in ('all',*my_tasks.GROUPS):group='all'
    return render_list(context,session,data,group,choice.get('page',1) if choice else 1,view_state,notice)

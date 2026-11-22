"""Apply only this feature to the existing local image; preserve pending SSO changes."""
import hashlib
from pathlib import Path

root = Path('/app/workhub')
expected = {
    'bot.py': 'c217adcef8f54e5fdf2760ba210eb5c5c97ab29bf29ee91b4b639ac8d6ce47fa',
    'main.py': '356ba1625b82ffedc4ac639a12705c7c52c28791fa44da8ca3c73f3e3711de07',
    'store.py': 'ed268da556d0bf4f36e5a6bd21afbaca34bf95fe17e0688cf7c18938c5917def',
}
patches = {
    'bot.py': [
        ('from . import report_chat, execution, http_pool, my_tasks_chat, job_control, knowledge_chat',
         'from . import report_chat, execution, http_pool, my_tasks_chat, job_control, knowledge_chat\nfrom . import deadline_alerts'),
        ('        routed=my_tasks_chat.route(user,uid,room,context_key,context,text,choice)',
         '        routed=deadline_alerts.route(user,uid,room,text)\n        if routed is None:routed=my_tasks_chat.route(user,uid,room,context_key,context,text,choice)'),
    ],
    'main.py': [
        ('from . import lifecycle, outline_bridge, project_service, knowledge, analytics_service',
         'from . import lifecycle, outline_bridge, project_service, knowledge, analytics_service\nfrom . import deadline_alerts'),
        ('    threading.Thread(target=lifecycle.run,args=(stop,),daemon=True).start()',
         '    threading.Thread(target=lifecycle.run,args=(stop,),daemon=True).start()\n    threading.Thread(target=deadline_alerts.run,args=(stop,),daemon=True).start()'),
    ],
    'store.py': [
        ('    project_service.init()',
         '    project_service.init()\n    from . import deadline_alerts\n    deadline_alerts.init()'),
    ],
}
for name, changes in patches.items():
    path = root / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected[name], name + ' baseline changed'
    text = path.read_text()
    for before, after in changes:
        assert text.count(before) == 1, name + ' patch anchor changed'
        text = text.replace(before, after)
    path.write_text(text)
print('Applied deadline-alert changes only to bot.py, main.py and store.py')

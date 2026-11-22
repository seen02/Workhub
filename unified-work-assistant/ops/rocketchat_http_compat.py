"""Generate a same-origin, early UUID compatibility script for local HTTP only."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def configure(text):
    if '# WORKHUB_LOCAL_UUID_COMPAT' in text:return text
    marker='    server_name rocketchat.workhub.test;'
    assert text.count(marker)==1, 'Expected the dedicated local chat virtual host'
    source=(ROOT/'config/nginx-local/rocketchat-http-compat.js').read_text(encoding='utf-8')
    # An Nginx literal response avoids another volume mount. Keep JS source separate.
    escaped=source.replace('\\','\\\\').replace("'","\\'").replace('$','\\$')
    route='''
    # WORKHUB_LOCAL_UUID_COMPAT: remove when this environment moves to HTTPS.
    location = /__workhub_local/crypto-compat.js {
        default_type application/javascript;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options nosniff always;
        return 200 '%s';
    }
''' % escaped
    start=text.index(marker)+len(marker)
    text=text[:start]+route+text[start:]
    loc=text.index('    location / {',start)
    insert=loc+len('    location / {')
    config='''
        proxy_set_header Accept-Encoding "";
        sub_filter_once on;
        sub_filter '<head>' '<head><script src="/__workhub_local/crypto-compat.js"></script>';
'''
    return text[:insert]+config+text[insert:]

if __name__=='__main__':
    p=ROOT/'config/nginx-local/default.conf';old=p.read_text(encoding='utf-8')
    backup=ROOT/'.local/rocketchat-history-fix/default.conf.before'
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():backup.write_text(old,encoding='utf-8')
    p.write_text(configure(old),encoding='utf-8')
    print('Local chat HTTP compatibility configured; other hosts unchanged.')

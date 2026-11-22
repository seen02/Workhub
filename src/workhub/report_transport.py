"""DM identity and destination ACLs. Stable message IDs reconcile lost responses."""
import os
from urllib.parse import quote
from fastapi import HTTPException

def client():
    from . import bot
    if bot.mongo is None:raise ValueError('채팅 연결을 준비 중입니다.')
    return bot

def require_dm(user,uid,rid):
    b=client()
    if b.identity(uid)['sub']!=user['sub']:raise HTTPException(403,'보고 작성자 인증이 다릅니다.')
    room=b.mongo.rocketchat.rocketchat_room.find_one({'_id':rid})
    if not room or room.get('t')!='d' or set(room.get('uids',[]))!={uid,b.bot_id}:
        raise HTTPException(403,'통합 업무 비서와의 개인 대화방에서 진행하세요.')

def permitted(b,uid,room):
    db=b.mongo.rocketchat
    u=db.users.find_one({'_id':uid},{'active':1,'roles':1,'username':1})
    sub=db.rocketchat_subscription.find_one({'rid':room['_id'],'u._id':uid})
    if not u or not u.get('active',True) or not sub:return False
    if room.get('t') not in ('c','p') or room.get('archived') or room.get('encrypted') or room.get('prid') and room.get('t')=='d':return False
    identifiers={uid,u.get('username')}-{None}
    if identifiers.intersection(room.get('muted',[])) or identifiers.intersection(room.get('blocked',[])):return False
    roles=set(u.get('roles',[]))|set(sub.get('roles',[]))
    def has(name):
        p=db.rocketchat_permissions.find_one({'_id':name})
        return bool(p and roles.intersection(p.get('roles',[])))
    # Installed Rocket.Chat has no generic send-message permission: ordinary
    # members may post unless muted/readonly. Honor it if a deployment adds it.
    send_permission=db.rocketchat_permissions.find_one({'_id':'send-message'})
    if send_permission and not roles.intersection(send_permission.get('roles',[])):return False
    if (room.get('ro') or room.get('broadcast')) and not has('post-readonly'):return False
    return True

def destination(user,uid,rid):
    b=client()
    if b.identity(uid)['sub']!=user['sub']:raise HTTPException(403,'채팅 작성자 인증이 다릅니다.')
    room=b.mongo.rocketchat.rocketchat_room.find_one({'_id':rid})
    if not room or not permitted(b,uid,room) or not permitted(b,b.bot_id,room):
        raise HTTPException(403,'본인과 업무 비서가 모두 참여하고 전송할 수 있는 채널·토론방을 선택하세요.')
    return {'id':rid,'name':room.get('fname') or room.get('name',rid),'kind':'토론방' if room.get('prid') else ('채널' if room['t']=='c' else '비공개 채널')}

def destinations(user,uid,query=''):
    b=client();result=[]
    for s in b.mongo.rocketchat.rocketchat_subscription.find({'u._id':uid,'t':{'$in':['c','p']}}):
        try:r=destination(user,uid,s['rid'])
        except HTTPException:continue
        if query.casefold() in r['name'].casefold():result.append(r)
    return sorted(result,key=lambda r:r['name'])

def lookup(mid):
    return client().mongo.rocketchat.rocketchat_message.find_one({'_id':mid})

def send(rid,text,mid,author=None):
    # chat.sendMessage supports a caller supplied _id. Never use random IDs on retry.
    return client().api('chat.sendMessage',{'message':{'_id':mid,'rid':rid,'msg':text,
        **({'alias':author+' · 업무 보고'} if author else {})}})

def link(rid,mid):
    base=os.getenv('ROCKETCHAT_PUBLIC_URL','http://rocketchat.workhub.test').rstrip('/')
    room=client().mongo.rocketchat.rocketchat_room.find_one({'_id':rid}) or {}
    return base+('/channel/' if room.get('t')=='c' else '/group/')+quote(room.get('name',rid),safe='')+'?msg='+quote(mid,safe='')

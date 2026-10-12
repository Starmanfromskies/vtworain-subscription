"""Executed inside an existing local PasarGuard runtime; never exports an auth token.

REQUEST is supplied on stdin by panel.py. Only subscription.url_prefix may change.
"""
import asyncio
import copy
import hashlib
import http.client
import inspect
import json
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit


async def result(value):
    return await value if inspect.isawaitable(value) else value


class Database:
    async def __aenter__(self):
        from app.db import GetDB
        self.manager=GetDB()
        return await self.manager.__aenter__() if hasattr(self.manager,'__aenter__') else self.manager.__enter__()
    async def __aexit__(self,*args):
        if hasattr(self.manager,'__aexit__'):return await self.manager.__aexit__(*args)
        return self.manager.__exit__(*args)


def endpoint():
    import config
    settings=getattr(config,'server_settings',None)
    port=int(getattr(settings,'port',getattr(config,'UVICORN_PORT',8000)))
    if getattr(settings,'uds',None):raise ValueError('Unix-socket panel requires an explicit HTTP backend')
    cert=getattr(settings,'ssl_certfile',getattr(config,'UVICORN_SSL_CERTFILE',None))
    if not cert:return {'port':port,'scheme':'http','tls_name':'','certificate':''}
    text=Path(cert).read_text()
    decoded=ssl._ssl._test_decode_cert(str(cert))
    names=[value for kind,value in decoded.get('subjectAltName',[]) if kind=='DNS']
    name=next((n for n in names if not n.startswith('*.')),None)
    if not name and names:name='panel.'+names[0][2:]
    if not name:raise ValueError('The panel TLS certificate needs a DNS subjectAltName')
    return {'port':port,'scheme':'https','tls_name':name,'certificate':text}


class LocalTLS(http.client.HTTPSConnection):
    def __init__(self,details):
        context=ssl.create_default_context();context.load_verify_locations(cadata=details['certificate'])
        if hasattr(ssl,'VERIFY_X509_PARTIAL_CHAIN'):context.verify_flags|=ssl.VERIFY_X509_PARTIAL_CHAIN
        super().__init__('127.0.0.1',details['port'],context=context,timeout=15)
        self.tls_name=details['tls_name']
    def connect(self):
        http.client.HTTPConnection.connect(self)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self.tls_name)


def api(details,token,method='GET',body=None):
    connection=LocalTLS(details) if details['scheme']=='https' else http.client.HTTPConnection('127.0.0.1',details['port'],timeout=15)
    try:
        headers={'Authorization':'Bearer '+token,'Accept':'application/json','Content-Type':'application/json'}
        connection.request(method,'/api/settings',body=json.dumps(body) if body is not None else None,headers=headers)
        response=connection.getresponse();data=response.read(8*1024*1024)
        if response.status!=200:raise ValueError('The existing owner cannot access the panel settings API')
        value=json.loads(data)
        if not isinstance(value.get('subscription'),dict):raise ValueError('Unsupported panel settings API')
        return value
    finally:connection.close()


async def identity():
    import config
    import jwt
    from sqlalchemy import select
    from app.db import models
    from app.models.settings import SettingsSchema
    # PUT {} must be an empty patch, otherwise cache refresh would change defaults.
    schema=SettingsSchema()
    dump=schema.model_dump(exclude_none=True) if hasattr(schema,'model_dump') else schema.dict(exclude_none=True)
    if dump!={}:raise ValueError('Unsupported panel patch semantics')
    async with Database() as db:
        secret=(await result(db.execute(select(models.JWT.secret_key)))).scalar_one_or_none()
        if not secret:raise ValueError('The initialized panel JWT key is missing')
        admin=None
        if hasattr(models.Admin,'is_sudo'):
            query=select(models.Admin).where(models.Admin.is_sudo.is_(True))
        elif hasattr(models,'AdminRole') and hasattr(models.AdminRole,'is_owner'):
            query=select(models.Admin).join(models.AdminRole,models.Admin.role_id==models.AdminRole.id).where(models.AdminRole.is_owner.is_(True))
        else:query=None
        if query is not None:
            if hasattr(models.Admin,'is_disabled'):query=query.where(models.Admin.is_disabled.is_(False))
            if hasattr(models.Admin,'status'):query=query.where(models.Admin.status=='active')
            admin=(await result(db.execute(query.order_by(models.Admin.id)))).scalars().first()
        if admin:
            username=admin.username;aid=admin.id
        else:
            debug=getattr(getattr(config,'runtime_settings',None),'debug',getattr(config,'DEBUG',False))
            if not debug:raise ValueError('An existing active database owner is required by a production panel')
            sudoers=getattr(getattr(config,'auth_settings',None),'sudoers',{})
            username=next(iter(sudoers),None) or getattr(config,'SUDO_USERNAME',None)
            if not username:raise ValueError('An active existing panel owner is required')
            existing=(await result(db.execute(select(models.Admin).where(models.Admin.username==username)))).scalar_one_or_none()
            if existing:raise ValueError('The configured environment owner is shadowed by a DB account')
            aid=None
        payload={'sub':username,'access':'admin','iat':int(time.time()),'exp':int(time.time())+120}
        if aid is not None:payload['aid']=int(aid)
        token=jwt.encode(payload,secret,algorithm='HS256')
        row=(await result(db.execute(select(models.Settings)))).scalar_one()
        return {'token':token,'fingerprint':hashlib.sha256(secret.encode()).hexdigest(),'row_id':row.id,
                'subscription':copy.deepcopy(row.subscription)}


async def atomic_prefix(row_id,expected,new,remove=False):
    from sqlalchemy import select,update,func,cast,JSON,literal,Text
    from app.db import models
    async with Database() as db:
        dialect=db.bind.dialect.name
        column=models.Settings.subscription
        if dialect=='postgresql':
            from sqlalchemy.dialects.postgresql import JSONB,ARRAY
            value=(cast(column,JSONB).op('-')('url_prefix') if remove else
                   func.jsonb_set(cast(column,JSONB),literal(['url_prefix'],ARRAY(Text)),func.to_jsonb(literal(new,Text)),True))
            value=cast(value,JSON)
        elif dialect in ('sqlite','mysql','mariadb'):
            value=func.json_remove(column,'$.url_prefix') if remove else func.json_set(column,'$.url_prefix',new)
        else:raise ValueError('Unsupported database for a field-only subscription update')
        condition=func.coalesce(column['url_prefix'].as_string(),'')==expected
        changed=await result(db.execute(update(models.Settings).where(models.Settings.id==row_id,condition).values(subscription=value).execution_options(synchronize_session=False)))
        if changed.rowcount!=1:
            await result(db.rollback());raise ValueError('Subscription URL changed concurrently; update withheld')
        await result(db.commit())


async def execute(request):
    details=endpoint();current=await identity()
    fingerprint=current['fingerprint']
    if request.get('fingerprint') and request['fingerprint']!=fingerprint:raise ValueError('Panel identity changed; update withheld')
    settings=api(details,current['token'])
    if 'url_prefix' not in settings['subscription']:raise ValueError('Unsupported subscription settings')
    describe=dict(details,fingerprint=fingerprint,old_url=current['subscription'].get('url_prefix',''),
                  old_key_present='url_prefix' in current['subscription'])
    command=request.get('command','describe')
    if command=='describe':return describe
    if command=='snapshot':return dict(describe,subscription=current['subscription'])
    if command!='update':raise ValueError('Unsupported integration command')
    new=request['url'];parsed=urlsplit(new)
    if not request.get('restore') and new and (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.path):
        raise ValueError('Use a subscription origin URL without a private path or credentials')
    old=current['subscription'].get('url_prefix','');expected=request['expected_url']
    if old==new:
        api(details,current['token'],'PUT',{})
        return {'updated':False,'url':new,'fingerprint':fingerprint}
    if old!=expected:raise ValueError('Subscription URL changed concurrently; update withheld')
    before=copy.deepcopy(settings['subscription']);before.pop('url_prefix',None)
    await atomic_prefix(current['row_id'],old,new,request.get('remove_key',False))
    try:
        after=api(details,current['token'],'PUT',{})
        effective=after['subscription'].get('url_prefix','')
        if effective!=new:raise ValueError('Panel did not confirm the subscription URL')
        other=copy.deepcopy(after['subscription']);other.pop('url_prefix',None)
        # A concurrent edit of another field is retained by the atomic JSON update.
        return {'updated':True,'url':effective,'fingerprint':fingerprint,'other_subscription_fields_preserved':other==before}
    except Exception:
        await atomic_prefix(current['row_id'],new,old,'url_prefix' not in current['subscription'])
        try:api(details,current['token'],'PUT',{})
        except Exception:pass
        raise


if __name__=='__main__' and 'REQUEST' in globals():
    try:
        output=asyncio.run(execute(REQUEST))
        print('VTWSUB_RESULT='+json.dumps(output))
    except Exception as error:
        # Database exceptions can contain connection details; only our explicit errors are public.
        message=str(error) if type(error) is ValueError else 'Native panel integration failed; no credentials were exported'
        print('VTWSUB_RESULT='+json.dumps({'error':message}))
        raise SystemExit(1)

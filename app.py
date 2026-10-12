"""Subscription-only WSGI gateway. The configured upstream remains authoritative."""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import ssl
import http.client
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler, HTTPSHandler

VERSION = '1.1.0'
ROOT = Path(__file__).resolve().parent
ASSET_BASE = '/tg3xbot-assets/redesign-20260915-server-qr-v1/'
IDENTIFIER = r'(?:[A-Za-z0-9_-]{6,80}|[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43})'
SUB_PATH = re.compile(r'^/(?:(?:sub|tg3xbot-raw-sub)/)?(' + IDENTIFIER + r')(?:/(links|links_base64|clash|clash-meta|sing-box|xray|outline))?/?$')
QR_PATH = re.compile(r'^/tg3xbot-sub-qr/(' + IDENTIFIER + r')\.png$')
LATENCY_PATH = re.compile(r'^/tg3xbot-latency/(' + IDENTIFIER + r')/?$')
MAX_BODY = 8 * 1024 * 1024
FORWARD_HEADERS = {'subscription-userinfo', 'x-subscription-userinfo', 'profile-title',
                   'profile-update-interval', 'support-url', 'announce', 'announce-url',
                   'x-tg3xbot-client-title', 'content-disposition', 'content-type',
                   'subscription-url', 'profile-web-page-url'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
        parsed.username or parsed.password or parsed.query or parsed.fragment or
        any(c in value for c in '\r\n\x00\\') or len(value) > 2048):
        raise ValueError('Upstream must be an HTTP(S) base URL without credentials, query or fragment')
    _ = parsed.port
    return value.rstrip('/')


def validate_config(config):
    config = dict(config)
    config['upstream'] = validate_origin(config['upstream'])
    config['public_url'] = validate_origin(config['public_url'])
    if urlsplit(config['public_url']).path:
        raise ValueError('Public URL must use a domain root')
    if config.get('mode', 'passthrough') not in ('passthrough', 'pasarguard'):
        raise ValueError('Unknown upstream mode')
    public=urlsplit(config['public_url']);origin=urlsplit(config['upstream'])
    port=lambda u:u.port or (443 if u.scheme=='https' else 80)
    if (public.hostname,port(public)) == (origin.hostname,port(origin)):
        raise ValueError('Upstream must not point back to this public subscription endpoint')
    config['mode'] = config.get('mode', 'passthrough')
    if config.get('latency_upstream'):
        config['latency_upstream'] = validate_origin(config['latency_upstream'])
    if config.get('upstream_tls_name'):
        if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',config['upstream_tls_name']):raise ValueError('Invalid upstream TLS name')
        file=config.get('upstream_ca_file','')
        if not file.startswith('/') or '..' in Path(file).parts:raise ValueError('Use an absolute upstream CA certificate path')
    return config


class NamedTLSConnection(http.client.HTTPSConnection):
    def __init__(self,host,tls_name,context,**kwargs):
        super().__init__(host,context=context,**kwargs);self.tls_name=tls_name
    def connect(self):
        http.client.HTTPConnection.connect(self)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self.tls_name)


class NamedTLSHandler(HTTPSHandler):
    def __init__(self,name,context):
        super().__init__(context=context);self.name=name
    def https_open(self,request):
        return self.do_open(lambda host,**kw:NamedTLSConnection(host,self.name,self._context,**kw),request)


def fetch(config, path, environ, origin=None):
    # Never inherit system HTTP proxies or follow a private subscription to another host.
    context=ssl.create_default_context();handler=HTTPSHandler(context=context)
    if config.get('upstream_tls_name') and not origin:
        context.load_verify_locations(cafile=config['upstream_ca_file'])
        if hasattr(ssl,'VERIFY_X509_PARTIAL_CHAIN'):context.verify_flags|=ssl.VERIFY_X509_PARTIAL_CHAIN
        handler=NamedTLSHandler(config['upstream_tls_name'],context)
    opener = build_opener(ProxyHandler({}), NoRedirect(), handler)
    url = (origin or config['upstream']) + path
    headers = {'Accept-Encoding': 'identity', 'User-Agent': environ.get('HTTP_USER_AGENT', 'Subscription-Gateway')[:1024],
               'Accept': environ.get('HTTP_ACCEPT', '*/*')[:1024]}
    request = Request(url, headers=headers, method='GET')
    try:
        response = opener.open(request, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError('Upstream response exceeds the size limit')
        return response.code, dict(response.headers.items()), body


def upstream_path(config, path, query, identifier, export=''):
    raw = 'raw' in parse_qs(query) or path.startswith('/tg3xbot-raw-sub/')
    if config['mode'] == 'pasarguard' and raw and not export:
        return '/sub/' + identifier + '/links_base64'
    if path.startswith('/tg3xbot-raw-sub/'):
        return '/sub/' + identifier + '/?' + urlencode({'raw': '1'})
    return path + ('?' + query if query else '')


def browser_request(environ, query, export):
    ua = environ.get('HTTP_USER_AGENT', '').lower()
    return (not export and 'raw' not in parse_qs(query) and 'text/html' in environ.get('HTTP_ACCEPT', '').lower()
            and not any(name in ua for name in ('v2box', 'v2ray', 'streisand', 'clash', 'sing-box', 'hiddify', 'shadowrocket')))


def safe_headers(source):
    return [(key, value) for key, value in source.items() if key.lower() in FORWARD_HEADERS
            and not any(c in value for c in '\r\n\x00')]


def create_app(config, root=ROOT, transport=fetch):
    config = validate_config(config)
    root = Path(root)
    frontend = root / 'web'

    def app(environ, start_response):
        method = environ.get('REQUEST_METHOD', 'GET')
        path = environ.get('PATH_INFO', '')
        query = environ.get('QUERY_STRING', '')

        def respond(status, body=b'', headers=None, content_type='text/plain; charset=utf-8'):
            labels = {200:'OK', 301:'Moved Permanently', 302:'Found', 303:'See Other', 307:'Temporary Redirect',
                      308:'Permanent Redirect', 400:'Bad Request', 404:'Not Found', 405:'Method Not Allowed',
                      429:'Too Many Requests', 500:'Internal Server Error', 502:'Bad Gateway', 503:'Service Unavailable'}
            output = [(key,value) for key,value in (headers or []) if key.lower() not in
                      ('content-length','cache-control','referrer-policy','x-content-type-options')]
            if not any(key.lower() == 'content-type' for key,_ in output):output.append(('Content-Type', content_type))
            output.extend([('Content-Length', str(len(body))), ('Cache-Control', 'private, no-store'),
                           ('Referrer-Policy','no-referrer'), ('X-Content-Type-Options','nosniff')])
            if content_type.startswith('text/html'):
                output.extend([('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'none'"),
                               ('X-Frame-Options','DENY')])
            start_response(str(status)+' '+labels.get(status,'Upstream response'), output)
            return [b'' if method=='HEAD' else body]

        if method not in ('GET','HEAD'):
            return respond(405,b'Only GET and HEAD are supported', [('Allow','GET, HEAD')])
        if len(path)>2048 or len(query)>4096 or any(c in path+query for c in '\x00\r\n'):
            return respond(400,b'Invalid request')
        if path=='/healthz':
            return respond(200,json.dumps({'status':'ok','version':VERSION}).encode(),content_type='application/json')
        if path.startswith(ASSET_BASE):
            relative=path[len(ASSET_BASE):]
            target=(frontend/relative).resolve()
            if not target.is_relative_to(frontend.resolve()) or not target.is_file():return respond(404,b'Not found')
            return respond(200,target.read_bytes(),content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        latency=LATENCY_PATH.fullmatch(path)
        if latency:
            if len(latency[1])>512:return respond(404,b'Not found')
            if not config.get('latency_upstream'):
                return respond(200,b'{"metric":"tcp_connect","profiles":[]}',content_type='application/json')
            try:
                status,headers,body=transport(config,path,environ,origin=config['latency_upstream'])
                return respond(status,body,safe_headers(headers),content_type='application/json')
            except (OSError,URLError,ValueError):return respond(502,b'Latency source unavailable')
        qr=QR_PATH.fullmatch(path)
        subscription=SUB_PATH.fullmatch(path)
        if not qr and not subscription:return respond(404,b'Use a valid private subscription link')
        identifier=(qr or subscription)[1]
        if len(identifier)>512:return respond(404,b'Not found')
        export=subscription[2] if subscription else ''
        target=upstream_path(config,path,query,identifier,export)
        if qr:target=upstream_path(config,'/sub/'+identifier+'/', 'raw=1',identifier)
        try:
            status,headers,body=transport(config,target,environ)
            if status in (301,302,303,307,308):
                location=next((v for k,v in headers.items() if k.lower()=='location'),'')
                origin=urlsplit(config['upstream']);redirect=urlsplit(location)
                if location.startswith('/') and not location.startswith('//'):
                    location=config['public_url']+location
                elif (redirect.scheme,redirect.netloc)==(origin.scheme,origin.netloc):
                    suffix=redirect.path
                    if origin.path and suffix.startswith(origin.path+'/'):suffix=suffix[len(origin.path):]
                    location=config['public_url']+suffix+('?' + redirect.query if redirect.query else '')
                else:return respond(502,b'Unexpected upstream redirect')
                return respond(status,b'', [('Location',location)])
            if status!=200:
                # Keep the upstream's authorization/status decision; never expose its debug HTML.
                return respond(status,b'Subscription unavailable')
            if qr:
                import qrcode
                image=qrcode.make(config['public_url']+'/'+identifier)
                stream=io.BytesIO();image.save(stream,format='PNG')
                return respond(200,stream.getvalue(),content_type='image/png')
            if browser_request(environ,query,export) and not path.startswith('/tg3xbot-raw-sub/'):
                content_type=next((v for k,v in headers.items() if k.lower()=='content-type'),'')
                if 'text/html' in content_type.lower():
                    return respond(200,(frontend/'index.html').read_bytes(),content_type='text/html; charset=utf-8')
                # Some panels intentionally have their own browser template disabled.
                if not body.lstrip().startswith((b'<',b'{')):
                    return respond(200,(frontend/'index.html').read_bytes(),content_type='text/html; charset=utf-8')
                return respond(502,b'Upstream did not return a subscription')
            return respond(200,body,safe_headers(headers))
        except (OSError,URLError,ValueError,ImportError):
            return respond(502,b'Subscription upstream is unavailable')
    return app


_app = None
def application(environ,start_response):
    global _app
    if _app is None:
        config_path=Path(os.environ.get('SUBSCRIPTION_CONFIG','/etc/vtworain-subscription/config.json'))
        _app=create_app(json.loads(config_path.read_text(encoding='utf-8')))
    return _app(environ,start_response)


if __name__=='__main__':
    import argparse
    from wsgiref.simple_server import make_server, WSGIRequestHandler
    parser=argparse.ArgumentParser(description='Local development server. Production uses Gunicorn behind nginx.')
    parser.add_argument('--config',required=True);parser.add_argument('--port',type=int,default=8789)
    args=parser.parse_args()
    class QuietHandler(WSGIRequestHandler):
        def log_message(self,*args):pass
    app=create_app(json.loads(Path(args.config).read_text()))
    with make_server('127.0.0.1',args.port,app,handler_class=QuietHandler) as server:
        print('Local subscription server: http://127.0.0.1:'+str(server.server_port),flush=True)
        server.serve_forever()

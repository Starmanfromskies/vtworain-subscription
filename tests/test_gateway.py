import io
import json
import sys
import threading
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import deploy

CONFIG={'upstream':'http://127.0.0.1:18080','public_url':'https://subscription.example.com','mode':'passthrough'}
TOKEN='synthetic.'+'A'*43

class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.requests=[];self.reply=(200,{'Content-Type':'text/html'},b'<html>panel</html>')
        self.gateway=app.create_app(CONFIG,transport=self.transport)
    def transport(self,config,path,environ,origin=None):
        self.requests.append((path,origin));return self.reply
    def call(self,path='/sub/'+TOKEN+'/',query='',method='GET',accept='text/html',ua='Mozilla/5.0',gateway=None):
        output={}
        def start(status,headers):output.update(status=int(status.split()[0]),headers=dict(headers))
        output['body']=b''.join((gateway or self.gateway)({'PATH_INFO':path,'QUERY_STRING':query,'REQUEST_METHOD':method,'HTTP_ACCEPT':accept,'HTTP_USER_AGENT':ua},start))
        return output
    def test_authenticated_html_uses_exact_frontend(self):
        result=self.call();self.assertEqual(result['body'],(app.ROOT/'web/index.html').read_bytes());self.assertEqual(result['status'],200)
    def test_invalid_token_stays_rejected(self):
        self.reply=(404,{},b'private debug');self.assertEqual(self.call()['status'],404);self.assertNotIn(b'private debug',self.call()['body'])
    def test_browser_html_is_never_cached(self):
        self.assertEqual(self.call()['headers']['Cache-Control'],'private, no-store')
    def test_client_raw_bytes_and_quota_preserved(self):
        self.reply=(200,{'Content-Type':'text/plain','Subscription-Userinfo':'upload=1; download=2; total=3','Profile-Title':'Demo'},b'SYNTHETIC-RAW')
        result=self.call(accept='*/*',ua='V2Box');self.assertEqual(result['body'],b'SYNTHETIC-RAW');self.assertEqual(result['headers']['Subscription-Userinfo'],'upload=1; download=2; total=3')
    def test_client_with_browser_accept_is_not_overlaid(self):
        self.assertEqual(self.call(ua='Streisand')['body'],b'<html>panel</html>')
    def test_raw_query_bypasses_overlay(self):
        self.assertEqual(self.call(query='raw=1')['body'],b'<html>panel</html>')
    def test_native_raw_translated(self):
        gateway=app.create_app(dict(CONFIG,mode='pasarguard'),transport=self.transport)
        self.call(query='raw=1',gateway=gateway);self.assertEqual(self.requests[0][0],'/sub/'+TOKEN+'/links_base64')
    def test_export_not_overlaid(self):
        self.assertEqual(self.call(path='/sub/'+TOKEN+'/xray')['body'],b'<html>panel</html>')
    def test_legacy_import_translated(self):
        self.call('/tg3xbot-raw-sub/synthetic123/');self.assertEqual(self.requests[0][0],'/sub/synthetic123/?raw=1')
    def test_head_has_original_length_no_body(self):
        result=self.call(method='HEAD');self.assertEqual(result['body'],b'');self.assertEqual(int(result['headers']['Content-Length']),(app.ROOT/'web/index.html').stat().st_size)
    def test_post_not_forwarded(self):
        self.assertEqual(self.call(method='POST')['status'],405);self.assertEqual(self.requests,[])
    def test_admin_route_not_forwarded(self):
        self.assertEqual(self.call('/api/admin')['status'],404);self.assertEqual(self.requests,[])
    def test_static_traversal_rejected(self):
        self.assertEqual(self.call(app.ASSET_BASE+'../../app.py')['status'],404);self.assertEqual(self.requests,[])
    def test_static_asset_no_upstream_request(self):
        result=self.call(app.ASSET_BASE+'assets/qrcode.js');self.assertEqual(result['status'],200);self.assertEqual(self.requests,[])
    def test_health_is_local(self):
        self.assertEqual(json.loads(self.call('/healthz')['body']),{'status':'ok','version':'1.0.0'});self.assertEqual(self.requests,[])
    def test_disabled_latency_not_fabricated(self):
        self.assertEqual(json.loads(self.call('/tg3xbot-latency/synthetic123')['body'])['profiles'],[]);self.assertEqual(self.requests,[])
    def test_foreign_redirect_rejected(self):
        self.reply=(302,{'Location':'https://foreign.example/sub/'+TOKEN},b'');self.assertEqual(self.call()['status'],502)
    def test_same_origin_redirect_rewritten(self):
        self.reply=(302,{'Location':CONFIG['upstream']+'/sub/'+TOKEN},b'');self.assertEqual(self.call()['headers']['Location'],CONFIG['public_url']+'/sub/'+TOKEN)
    def test_error_does_not_leak_upstream_address(self):
        def bad(*a,**k):raise OSError('sensitive diagnostic')
        gateway=app.create_app(CONFIG,transport=bad);result=self.call(gateway=gateway)
        self.assertEqual(result['status'],502);self.assertNotIn(b'sensitive',result['body'])
    def test_private_paths_over_limit_rejected(self):
        result=self.call('/sub/'+'a'*500+'.'+'A'*43);self.assertEqual(result['status'],404);self.assertEqual(self.requests,[])
    def test_credentialed_origin_rejected(self):
        with self.assertRaises(ValueError):app.create_app(dict(CONFIG,upstream='https://user:password@example.com'))
    def test_self_proxy_loop_rejected(self):
        with self.assertRaises(ValueError):app.create_app(dict(CONFIG,upstream=CONFIG['public_url']+'/panel'))
    def test_bad_config_rejected(self):
        for value in ('ftp://example.com','http://example.com/?token=abc','http://example.com/#fragment'):
            with self.assertRaises(ValueError):app.create_app(dict(CONFIG,upstream=value))
    def test_real_http_transport_drops_cookie_and_authorization(self):
        seen={}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.update(dict(self.headers));self.send_response(200);self.send_header('Content-Type','text/plain');self.end_headers();self.wfile.write(b'synthetic')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            config=dict(CONFIG,upstream='http://127.0.0.1:'+str(server.server_port))
            result=app.fetch(config,'/sub/'+TOKEN,{'HTTP_COOKIE':'private','HTTP_AUTHORIZATION':'private'})
            self.assertEqual(result[2],b'synthetic');self.assertNotIn('Cookie',seen);self.assertNotIn('Authorization',seen)
        finally:server.shutdown();server.server_close();thread.join()

class DeployTest(unittest.TestCase):
    def test_safe_http_config(self):
        files=deploy.render('subscription.example.com','http://127.0.0.1:18080','pasarguard',8080,19839,'off')
        self.assertIn('listen 8080;',files['nginx.conf']);self.assertIn('access_log off;',files['nginx.conf']);self.assertNotIn('ssl_certificate',files['nginx.conf'])
        self.assertIn('--bind 127.0.0.1:19839',files['vtworain-subscription.service'])
    def test_tls_paths_and_acme(self):
        files=deploy.render('subscription.example.com',CONFIG['upstream'],'pasarguard',443,19839,'existing','/etc/ssl/fullchain.pem','/etc/ssl/private/key.pem')
        self.assertIn('listen 443 ssl;',files['nginx.conf']);self.assertIn('acme-challenge',files['nginx.conf'])
    def test_injection_inputs_rejected(self):
        for domain in ('example.com;include /secret','example.com\nserver','*.example.com'):
            with self.assertRaises(ValueError):deploy.render(domain,CONFIG['upstream'],'passthrough',443,19839,'off')
    def test_conflicting_ports_rejected(self):
        with self.assertRaises(ValueError):deploy.render('example.com',CONFIG['upstream'],'passthrough',443,443,'off')
    def test_certificate_path_injection_rejected(self):
        with self.assertRaises(ValueError):deploy.render('example.com',CONFIG['upstream'],'passthrough',443,19839,'existing','/tmp/cert;bad','/tmp/key')

if __name__=='__main__':unittest.main(verbosity=2)

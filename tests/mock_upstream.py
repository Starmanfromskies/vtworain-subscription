"""Synthetic upstream for local preview and CI. Never use it as a customer panel."""
import base64
import sys
import time
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import quote,urlencode,urlsplit

TOKEN='synthetic.'+'A'*43
key=base64.b64encode(bytes(range(32))).decode()
public=base64.b64encode(bytes(range(32,64))).decode()
PROFILES=[
 'vless://11111111-1111-4111-8111-111111111111@192.0.2.10:443?security=tls&type=xhttp#Germany%20Demo',
 'ss://'+base64.b64encode(b'aes-128-gcm:SYNTHETIC-ONLY').decode().rstrip('=')+'@198.51.100.10:443#Finland%20Demo',
 'hysteria2://SYNTHETIC-ONLY@203.0.113.10:443#Hysteria%20Demo',
 'wireguard://'+quote(key,safe='')+'@192.0.2.20:51820?'+urlencode({'publickey':public,'address':'10.77.0.2/32','mtu':'1280'})+'#WireGuard%20Demo',
]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):
        path=urlsplit(self.path)
        if path.path.rstrip('/') not in ('/sub/'+TOKEN,'/sub/'+TOKEN+'/links_base64','/sub/synthetic123','/synthetic123'):
            self.send_response(404);self.end_headers();return
        raw='raw=1' in path.query or path.path.endswith('links_base64') or 'text/html' not in self.headers.get('Accept','')
        body=base64.b64encode('\n'.join(PROFILES).encode()) if raw else b'<html>Synthetic panel template</html>'
        self.send_response(200);self.send_header('Content-Type','text/plain' if raw else 'text/html')
        self.send_header('Subscription-Userinfo','upload=1073741824; download=2147483648; total=53687091200; expire='+str(int(time.time())+2592000))
        self.send_header('Profile-Title','Redesign Demo');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
if __name__=='__main__':
    port=int(sys.argv[1]) if len(sys.argv)>1 else 18080
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()

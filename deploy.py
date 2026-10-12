"""Validate installer inputs and render dedicated nginx/systemd configuration."""
import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from app import validate_config

MARKER='# Managed by vtworain-subscription installer'

def render(domain, upstream, mode, port, app_port, tls, certificate='', key='', latency=''):
    if not re.fullmatch(r'(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[A-Za-z]{2,63}',domain):
        raise ValueError('Use a fully qualified domain, without scheme, port or path')
    if any(not 1<=int(p)<=65535 for p in (port,app_port)) or int(port)==int(app_port):
        raise ValueError('Public and application ports must be distinct valid ports')
    if tls not in ('letsencrypt','existing','off'):raise ValueError('Unknown TLS mode')
    public=('http' if tls=='off' else 'https')+'://'+domain+((':'+str(port)) if port!=(80 if tls=='off' else 443) else '')
    config=validate_config({'upstream':upstream,'public_url':public,'mode':mode,'latency_upstream':latency})
    if tls!='off':
        for path in (certificate,key):
            if not re.fullmatch(r'/[A-Za-z0-9_./-]+',path) or '..' in Path(path).parts:
                raise ValueError('Certificate paths must be absolute and contain only safe path characters')
    tls_lines='' if tls=='off' else f'''    ssl_certificate {certificate};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:vtwsub_ssl:10m;
'''
    listen=f'    listen {port}'+(' ssl' if tls!='off' else '')+';'
    nginx=f'''{MARKER}
server {{
{listen}
    server_name {domain};
{tls_lines}    # Private subscription URLs must never appear in access logs or caches.
    access_log off;
    error_log /var/log/nginx/vtworain-subscription-error.log crit;
    client_max_body_size 1k;
    add_header Referrer-Policy no-referrer always;
    location / {{
        limit_req zone=vtwsub_requests burst=20 nodelay;
        proxy_pass http://127.0.0.1:{app_port};
        proxy_http_version 1.1;
        proxy_set_header Host {domain};
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 35s;
        proxy_connect_timeout 5s;
        proxy_buffering off;
        proxy_cache off;
    }}
}}
'''
    if tls!='off':
        nginx+=f'''server {{
    listen 80;
    server_name {domain};
    access_log off;
    location ^~ /.well-known/acme-challenge/ {{ root /var/lib/vtworain-subscription/acme; }}
    location / {{ return 301 https://{domain}{(':'+str(port)) if port!=443 else ''}$request_uri; }}
}}
'''
    acme=f'''{MARKER}
server {{
    listen 80;
    server_name {domain};
    access_log off;
    location ^~ /.well-known/acme-challenge/ {{ root /var/lib/vtworain-subscription/acme; }}
    location / {{ return 503; }}
}}
'''
    unit=f'''{MARKER}
[Unit]
Description=VTWorain custom subscription gateway
After=network-online.target
Wants=network-online.target

[Service]
User=vtwsub
Group=vtwsub
WorkingDirectory=/opt/vtworain-subscription
Environment=SUBSCRIPTION_CONFIG=/etc/vtworain-subscription/config.json
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/gunicorn --bind 127.0.0.1:{app_port} --workers 2 --worker-class gthread --threads 4 --timeout 45 --error-logfile /dev/null --access-logfile /dev/null app:application
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    return {'config.json':json.dumps(config,indent=2)+'\n','nginx.conf':nginx,'acme.conf':acme,
            'rate-limit.conf':MARKER+'\nlimit_req_zone $binary_remote_addr zone=vtwsub_requests:10m rate=10r/s;\n',
            'vtworain-subscription.service':unit}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('domain','upstream','mode','tls','out'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--port',type=int,required=True);parser.add_argument('--app-port',type=int,required=True)
    parser.add_argument('--certificate',default='');parser.add_argument('--key',default='');parser.add_argument('--latency',default='')
    a=parser.parse_args();files=render(a.domain,a.upstream,a.mode,a.port,a.app_port,a.tls,a.certificate,a.key,a.latency)
    output=Path(a.out);output.mkdir(parents=True,exist_ok=True)
    for name,content in files.items():(output/name).write_text(content,encoding='utf-8')

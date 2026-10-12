"""Backup/restore only this installer's owned files. Never restore a customer DB."""
import argparse
import json
import os
import shutil
import subprocess
import re
import time
from urllib.request import build_opener,ProxyHandler
from pathlib import Path

RUNTIME=Path('/opt/vtworain-subscription')
BASE=Path('/var/backups/vtworain-subscription')
FILES=[Path('/etc/vtworain-subscription/config.json'),
       Path('/etc/nginx/conf.d/vtworain-subscription.conf'),
       Path('/etc/nginx/conf.d/vtworain-subscription-rate.conf'),
       Path('/etc/systemd/system/vtworain-subscription.service'),
       Path('/etc/letsencrypt/renewal-hooks/deploy/vtworain-subscription.sh')]

def quiet(*args):
    return subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0

def checked_directory(value):
    directory=Path(value).resolve()
    if directory.parent!=BASE or directory==BASE:raise ValueError('Use a direct child of '+str(BASE))
    return directory

def wait_ready(port,timeout=20):
    opener=build_opener(ProxyHandler({}));deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            with opener.open('http://127.0.0.1:'+str(port)+'/healthz',timeout=2) as response:
                if json.loads(response.read())['status']=='ok':return
        except (OSError,ValueError,KeyError):pass
        time.sleep(.25)
    raise RuntimeError('Restored files are in place, but the previous subscription service is not healthy')

def capture(directory):
    directory.mkdir(parents=True,mode=0o700,exist_ok=False)
    state={'runtime_exists':RUNTIME.exists(),'files':[],
           'active':quiet('systemctl','is-active','--quiet','vtworain-subscription'),
           'enabled':quiet('systemctl','is-enabled','--quiet','vtworain-subscription'),
           'nginx_active':quiet('systemctl','is-active','--quiet','nginx')}
    if RUNTIME.is_symlink():raise ValueError('Runtime directory must not be a symlink')
    if RUNTIME.exists():
        if not (RUNTIME/'.managed-by-installer').exists():raise ValueError('Unowned runtime directory')
        shutil.copytree(RUNTIME,directory/'runtime',symlinks=True)
    for index,path in enumerate(FILES):
        if path.is_symlink():raise ValueError('Managed file must not be a symlink: '+str(path))
        exists=path.exists()
        if exists:shutil.copy2(path,directory/('file-'+str(index)))
        state['files'].append({'path':str(path),'exists':exists})
    (directory/'state.json').write_text(json.dumps(state,indent=2))
    shutil.copy2(__file__,directory/'rollback.py')

def restore(directory):
    state=json.loads((directory/'state.json').read_text())
    assert [item['path'] for item in state['files']]==[str(p) for p in FILES]
    quiet('systemctl','stop','vtworain-subscription')
    if RUNTIME.exists():
        if RUNTIME.is_symlink() or not (RUNTIME/'.managed-by-installer').exists():raise ValueError('Refusing to remove an unowned runtime directory')
        shutil.rmtree(RUNTIME)
    if state['runtime_exists']:shutil.copytree(directory/'runtime',RUNTIME,symlinks=True)
    for index,item in enumerate(state['files']):
        path=FILES[index]
        if item['exists']:
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(directory/('file-'+str(index)),path)
        elif path.exists():path.unlink()
    quiet('systemctl','daemon-reload')
    if state['enabled']:quiet('systemctl','enable','vtworain-subscription')
    else:quiet('systemctl','disable','vtworain-subscription')
    if state['active']:
        subprocess.run(['systemctl','start','vtworain-subscription'],check=True)
        unit=Path('/etc/systemd/system/vtworain-subscription.service').read_text()
        port=re.search(r'--bind 127\.0\.0\.1:(\d+)',unit)
        if port:wait_ready(port[1])
    if state['nginx_active']:
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx'],check=True)
    else:quiet('systemctl','stop','nginx')
    print('Previous subscription files and service state restored.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['capture','restore']);parser.add_argument('directory')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run as root')
    (capture if args.mode=='capture' else restore)(checked_directory(args.directory))

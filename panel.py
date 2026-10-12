"""Root-only discovery and URL integration for an existing local PasarGuard panel."""
import argparse
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent

def run_bridge(locator,command,payload=None):
    request=dict(payload or {},command=command)
    source='REQUEST='+repr(request)+'\n'+(ROOT/'panel_bridge.py').read_text()
    if locator['kind']=='docker':
        if not re.fullmatch(r'[a-f0-9]{12,64}',locator['id']):raise ValueError('Invalid local container ID')
        args=['docker','exec','-i',locator['id'],locator.get('python','python'),'-']
        options={}
    elif locator['kind']=='process':
        pid=int(locator['pid']);base=Path('/proc')/str(pid)
        environment={}
        for field in (base/'environ').read_bytes().split(b'\0'):
            if b'=' in field:
                key,value=field.split(b'=',1);environment[key.decode()]=value.decode()
        environment['PYTHONDONTWRITEBYTECODE']='1'
        options={'cwd':str((base/'cwd').resolve()),'env':environment}
        executable=str((base/'exe').resolve())
        virtual=Path(environment.get('VIRTUAL_ENV','/nonexistent'))/'bin/python'
        argv=(base/'cmdline').read_bytes().split(b'\0')[0].decode()
        if virtual.is_file():executable=str(virtual)
        elif argv.startswith('/') and Path(argv).is_file() and 'python' in Path(argv).name:executable=argv
        args=[executable,'-']
    else:raise ValueError('Unsupported panel locator')
    response=subprocess.run(args,input=source.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45,**options)
    lines=[line for line in response.stdout.decode(errors='replace').splitlines() if line.startswith('VTWSUB_RESULT=')]
    if not lines:raise ValueError('The selected panel runtime does not support automatic integration')
    value=json.loads(lines[-1].split('=',1)[1])
    if response.returncode or value.get('error'):raise ValueError(value.get('error','Panel integration failed'))
    return value


def candidates():
    found=[]
    try:
        ids=subprocess.check_output(['docker','ps','--format','{{.ID}}'],stderr=subprocess.DEVNULL,text=True).splitlines()
        for cid in ids:
            data=json.loads(subprocess.check_output(['docker','inspect',cid],stderr=subprocess.DEVNULL,text=True))[0]
            label=' '.join([data['Name'],data['Config'].get('Image',''),(data['Config'].get('Labels') or {}).get('com.docker.compose.service','')]).lower()
            if 'pasarguard' not in label or 'node' in data['Config'].get('Image','').lower():continue
            locator={'kind':'docker','id':data['Id'],'name':data['Name'].lstrip('/'),'python':'python'}
            try:info=run_bridge(locator,'describe')
            except (ValueError,OSError,subprocess.SubprocessError):continue
            port=str(info['port']);network=data['HostConfig'].get('NetworkMode')
            origins=[]
            if network=='host':origins=['127.0.0.1:'+port]
            else:
                for binding in data['NetworkSettings'].get('Ports',{}).get(port+'/tcp') or []:
                    host=binding['HostIp']
                    if host in ('','0.0.0.0','::'):host='127.0.0.1'
                    if host=='::1':host='[::1]'
                    origins.append(host+':'+binding['HostPort'])
                for net in data['NetworkSettings'].get('Networks',{}).values():
                    address=net.get('IPAddress','')
                    if address and ipaddress.ip_address(address).is_private:origins.append(address+':'+port)
            found.append({'locator':locator,'details':info,'origins':origins})
    except (OSError,subprocess.SubprocessError):pass
    seen=set()
    for process in Path('/proc').glob('[0-9]*'):
        try:
            cwd=(process/'cwd').resolve();exe=(process/'exe').resolve()
            if 'python' not in exe.name or not (cwd/'app/models/settings.py').is_file() or not (cwd/'app/utils/jwt.py').is_file():continue
            if (str(cwd),str(exe)) in seen:continue
            seen.add((str(cwd),str(exe)))
            locator={'kind':'process','pid':int(process.name),'name':str(cwd)}
            info=run_bridge(locator,'describe')
            found.append({'locator':locator,'details':info,'origins':['127.0.0.1:'+str(info['port'])]})
        except (OSError,ValueError,subprocess.SubprocessError):continue
    return found


def choose(found,selector=''):
    if selector:
        found=[item for item in found if item['locator'].get('name')==selector or item['locator'].get('id','').startswith(selector)]
    if not found:raise ValueError('No supported local PasarGuard owner/API was found. Install on the panel server, or use explicit --upstream/--mode with --no-panel-update')
    if len(found)>1:raise ValueError('Multiple local panels found. Use --panel-container NAME to select one: '+', '.join(item['locator']['name'] for item in found))
    return found[0]


def discover(output,selector=''):
    selected=choose(candidates(),selector)
    details=selected['details'];origin=None
    # Confirm connectivity from the host, not only from inside the panel container.
    for address in selected['origins']:
        value=details['scheme']+'://'+address
        try:
            parsed=urlsplit(value)
            with socket.create_connection((parsed.hostname,parsed.port),timeout=3) as sock:
                if details['scheme']=='https':
                    context=ssl.create_default_context();context.load_verify_locations(cadata=details['certificate'])
                    if hasattr(ssl,'VERIFY_X509_PARTIAL_CHAIN'):context.verify_flags|=ssl.VERIFY_X509_PARTIAL_CHAIN
                    with context.wrap_socket(sock,server_hostname=details['tls_name']):pass
            origin=value;break
        except (OSError,ValueError):continue
    if not origin:raise ValueError('The local panel API is not reachable from the host')
    integration={'locator':selected['locator'],'fingerprint':details['fingerprint'],'upstream':origin,'mode':'pasarguard'}
    path=Path(output)
    if path.is_symlink():raise ValueError('Integration output must not be a symlink')
    path.mkdir(parents=True,mode=0o700,exist_ok=True);path.chmod(0o700)
    (path/'panel.json').write_text(json.dumps(integration,indent=2))
    config={'upstream':origin,'mode':'pasarguard'}
    if details['scheme']=='https':
        (path/'panel-ca.pem').write_text(details['certificate'])
        config.update(upstream_tls_name=details['tls_name'],upstream_ca_file='/etc/vtworain-subscription/panel-ca.pem')
    (path/'discovered.json').write_text(json.dumps(config))
    return {'panel':selected['locator']['name'],'upstream':origin,'mode':'pasarguard'}


def snapshot(integration,backup):
    value=run_bridge(integration['locator'],'snapshot',{'fingerprint':integration['fingerprint']})
    (Path(backup)/'panel-before.json').write_text(json.dumps(value,indent=2))
    (Path(backup)/'panel-locator.json').write_text(json.dumps(integration,indent=2))
    for name in ('panel.py','panel_bridge.py'):(Path(backup)/name).write_bytes((ROOT/name).read_bytes())


def update(integration,backup,public_url):
    previous=json.loads((Path(backup)/'panel-before.json').read_text())
    journal={'new_url':public_url,'old_url':previous['old_url'],'old_key_present':previous['old_key_present']}
    (Path(backup)/'panel-update.json').write_text(json.dumps(journal))
    result=run_bridge(integration['locator'],'update',{'fingerprint':integration['fingerprint'],'expected_url':previous['old_url'],'url':public_url})
    (Path(backup)/'panel-update-result.json').write_text(json.dumps(result))
    return {'panel_subscription_url_updated':True,'url':result['url']}


def restore(backup):
    path=Path(backup)
    if not (path/'panel-update.json').exists():return
    integration=json.loads((path/'panel-locator.json').read_text());journal=json.loads((path/'panel-update.json').read_text())
    current=run_bridge(integration['locator'],'describe',{'fingerprint':integration['fingerprint']})
    if current['old_url']==journal['old_url']:return
    if current['old_url']!=journal['new_url']:raise ValueError('Panel URL changed independently; automatic panel rollback withheld')
    run_bridge(integration['locator'],'update',{'fingerprint':integration['fingerprint'],'expected_url':journal['new_url'],
        'url':journal['old_url'],'remove_key':not journal['old_key_present'],'restore':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['discover','snapshot','update','restore'])
    parser.add_argument('--out');parser.add_argument('--selector',default='');parser.add_argument('--integration');parser.add_argument('--backup');parser.add_argument('--url')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Panel discovery/update requires root on the local panel server')
    try:
        if args.command=='discover':value=discover(args.out,args.selector)
        elif args.command=='restore':restore(args.backup);value={'panel_subscription_url_restored':True}
        else:
            integration=json.loads(Path(args.integration).read_text())
            if args.command=='snapshot':snapshot(integration,args.backup);value={'panel_settings_backed_up':True}
            else:value=update(integration,args.backup,args.url)
        print(json.dumps(value))
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        parser.exit(1,'Panel integration: '+str(error)+'\n')

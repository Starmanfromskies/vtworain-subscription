const $=s=>document.querySelector(s);
const parts=location.pathname.split('/').filter(Boolean);
const subId=parts[0]==='sub'?parts[1]:parts[0];
const signedId=/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/.test(subId||'')&&(subId||'').length<=512;
const validId=signedId||/^[A-Za-z0-9_-]{6,80}$/.test(subId||'');
const subscription=location.origin+(signedId?'/sub/':'/')+encodeURIComponent(subId||'');
const rawImport=signedId?subscription:location.origin+'/tg3xbot-raw-sub/'+encodeURIComponent(subId||'')+'/';
const SUBSCRIPTION_SCHEME=/^(vless|vmess|trojan|ss|shadowsocks|hysteria|hysteria2|hy2|wireguard):\/\//i;
let configs=[],clientName='',timer,subscriptionQrUrl='';
const digits=new Intl.NumberFormat('fa-IR',{maximumFractionDigits:1});
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(timer);timer=setTimeout(()=>$('#toast').classList.remove('show'),3500)}
async function copy(value){try{await navigator.clipboard.writeText(value);toast('کپی شد')}catch{const input=document.createElement('textarea');input.value=value;input.style.position='fixed';input.style.opacity='0';document.body.append(input);input.select();const ok=document.execCommand('copy');input.remove();toast(ok?'کپی شد':'مرورگر اجازه کپی نداد.')}}
function decode64(text){return new TextDecoder().decode(Uint8Array.from(atob(text.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0)))}
function titleHeader(text){try{return text?.startsWith('base64:')?decode64(text.slice(7)):text||''}catch{return ''}}
function parseLine(raw){try{let name;if(raw.startsWith('vmess://'))name=JSON.parse(decode64(raw.slice(8))).ps;else name=decodeURIComponent(raw.split('#').slice(1).join('#'));return {raw,name:name||'Server'}}catch{return {raw,name:'Server'}}}
function bytes(n){return digits.format(n/1073741824)+' گیگ'}
const COUNTRY_FLAGS=[
 [/netherlands|holland|\bNL\b/i,'🇳🇱'],[/germany|deutschland|\bDE\b/i,'🇩🇪'],
 [/finland|\bFI\b/i,'🇫🇮'],[/turkey|türkiye|\bTR\b/i,'🇹🇷'],
 [/united states|america|\bUSA?\b/i,'🇺🇸'],[/united kingdom|britain|england|\bUK\b|\bGB\b/i,'🇬🇧'],
 [/france|\bFR\b/i,'🇫🇷'],[/singapore|\bSG\b/i,'🇸🇬'],[/canada|\bCA\b/i,'🇨🇦'],
 [/sweden|\bSE\b/i,'🇸🇪'],[/switzerland|\bCH\b/i,'🇨🇭'],[/japan|\bJP\b/i,'🇯🇵'],
 [/united arab emirates|\bUAE\b/i,'🇦🇪']
];
const LEADING_EMOJI=/^(?:(?:[\u{1F1E6}-\u{1F1FF}]{2})|[\u{1F300}-\u{1FAFF}]|[\u{2600}-\u{27BF}]|\uFE0F|\u200D|\s)+/u;
function serverFlag(name,warning=false){if(warning)return '⚠️';const value=String(name||'');const embedded=value.match(/[\u{1F1E6}-\u{1F1FF}]{2}/u);if(embedded)return embedded[0];return COUNTRY_FLAGS.find(([pattern])=>pattern.test(value))?.[1]||'🌐'}
function serverDisplayName(name){return String(name||'Server').replace(LEADING_EMOJI,'').trim()||'Server'}
function iconButton(icon,label,handler){const button=document.createElement('button');button.type='button';button.className='icon-button';button.title=label;button.setAttribute('aria-label',label);button.innerHTML='<i data-lucide="'+icon+'"></i>';button.addEventListener('click',handler);return button}
// Convert the panel's existing share profile, preserving its keys and endpoint.
// Only WireGuard client directives are emitted; URI values cannot add config lines.
function wireguardConfig(raw){
 const invalid=()=>{throw Error('Invalid WireGuard profile')};
 if(typeof raw!=='string'||raw.length>16384||/[\x00-\x20\x7f]/.test(raw))invalid();
 const uri=new URL(raw);
 if(uri.protocol!=='wireguard:'||!uri.username||uri.password||!uri.hostname||!uri.port||uri.pathname&&uri.pathname!=='/')invalid();
 const args=new Map();
 for(const [name,value] of uri.searchParams){const key=name.toLowerCase();if(args.has(key)||/[\x00-\x1f\x7f]/.test(value))invalid();args.set(key,value)}
 const field=(...names)=>{const present=names.filter(name=>args.has(name));if(present.length>1)invalid();return present.length?args.get(present[0]):''};
 const key=value=>{if(!/^[A-Za-z0-9+/]{43}=$/.test(value)||atob(value).length!==32||btoa(atob(value))!==value)invalid();return value};
 const ip=value=>{
  if(value.includes(':')){if(!/^[0-9a-f:.]+$/i.test(value))invalid();try{new URL('http://['+value+']/')}catch{invalid()}}
  else if(!/^(0|[1-9]\d{0,2})(\.(0|[1-9]\d{0,2})){3}$/.test(value)||value.split('.').some(n=>Number(n)>255))invalid();
  return value;
 };
 const networks=value=>value.split(',').map(part=>{const pieces=part.trim().split('/');if(pieces.length!==2||!/^\d{1,3}$/.test(pieces[1]))invalid();ip(pieces[0]);if(Number(pieces[1])>(pieces[0].includes(':')?128:32))invalid();return pieces.join('/')}).join(', ');
 const number=(value,min)=>{if(!/^\d{1,5}$/.test(value)||Number(value)<min||Number(value)>65535)invalid();return value};
 const dns=value=>value.split(',').map(part=>{part=part.trim();if(part.includes(':')||/^[\d.]+$/.test(part))return ip(part);if(part.length>253||!part.split('.').every(label=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label)))invalid();return part}).join(', ');
 const host=uri.hostname;
 if(host.startsWith('[')){ip(host.slice(1,-1))}else{dns(host)}
 const reserved=field('reserved');if(reserved&&!['0,0,0','[0,0,0]'].includes(reserved.replace(/\s/g,'')))invalid();
 const lines=['[Interface]','PrivateKey = '+key(decodeURIComponent(uri.username)),'Address = '+networks(field('address','ip'))];
 if(args.has('dns'))lines.push('DNS = '+dns(field('dns')));
 if(args.has('mtu'))lines.push('MTU = '+number(field('mtu'),1));
 lines.push('','[Peer]','PublicKey = '+key(field('publickey')),'Endpoint = '+host+':'+number(uri.port,1),'AllowedIPs = '+networks(field('allowedips')||'0.0.0.0/0, ::/0'));
 if(args.has('presharedkey'))lines.push('PresharedKey = '+key(field('presharedkey')));
 if(args.has('keepalive'))lines.push('PersistentKeepalive = '+number(field('keepalive'),0));
 return lines.join('\n')+'\n';
}
function wireguardFilename(cfg){
 const slug=cfg.name.normalize('NFKD').replace(/[^a-z0-9]+/gi,'-').replace(/^-+|-+$/g,'').toLowerCase().slice(0,6)||'server';
 let hash=2166136261;for(let i=0;i<cfg.raw.length;i++)hash=Math.imul(hash^cfg.raw.charCodeAt(i),16777619);
 return 'wg-'+slug+'-'+(hash>>>0).toString(16).padStart(8,'0').slice(0,4)+'.conf';
}
function downloadWireguard(cfg){
 let text;try{text=wireguardConfig(cfg.raw)}catch{toast('فایل معتبر وایرگارد برای این سرور در دسترس نیست.');return}
 const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));
 const link=document.createElement('a');link.href=url;link.download=wireguardFilename(cfg);document.body.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),30000);toast('دانلود فایل وایرگارد شروع شد');
}
function openQrDialog({label,text,imageUrl}){const dialog=$('#qr-dialog'),target=$('#large-qr');target.replaceChildren();$('#qr-dialog-label').textContent=label;if(imageUrl){const img=document.createElement('img');img.width=320;img.height=320;img.alt=label;img.decoding='async';img.src=imageUrl;target.append(img)}else{try{new QRCode(target,{text,width:320,height:320,colorDark:'#000000',colorLight:'#ffffff',correctLevel:QRCode.CorrectLevel.M});target.removeAttribute('title')}catch{toast('ساخت کد QR برای این سرور ممکن نشد.');return}}if(!dialog.open)dialog.showModal()}
function renderServers(){const query=$('#search').value.trim().toLowerCase();const list=configs.filter(c=>c.name.toLowerCase().includes(query));const container=$('#servers');container.replaceChildren();for(const cfg of list){const row=document.createElement('div');row.className='server';row.dataset.profileName=cfg.originalName||cfg.name;const mark=document.createElement('span');mark.className='flag';mark.setAttribute('aria-hidden','true');mark.textContent=serverFlag(cfg.originalName||cfg.name,cfg.warning);const name=document.createElement('div');name.className='server-name';name.textContent=cfg.name;const wireguard=/^wireguard:\/\//i.test(cfg.raw||'');if(wireguard){row.classList.add('server-wireguard');const protocol=document.createElement('span');protocol.className='muted server-protocol';protocol.textContent='WireGuard';protocol.dir='ltr';protocol.style.marginInlineStart='8px';name.append(protocol)}row.append(mark,name);if(!cfg.warning){const actions=document.createElement('div');actions.className='server-actions';if(wireguard)actions.append(iconButton('download','دانلود فایل وایرگارد '+cfg.name,()=>downloadWireguard(cfg)));actions.append(iconButton('qr-code','نمایش کد QR '+cfg.name,()=>openQrDialog({label:'کد سرور '+cfg.name,text:cfg.raw})),iconButton('copy','کپی لینک '+cfg.name,()=>copy(cfg.raw)));row.append(actions)}container.append(row)}$('#empty').hidden=list.length>0;lucide.createIcons()}
document.querySelectorAll('.disclosure').forEach(button=>button.addEventListener('click',()=>{const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));$('#'+button.getAttribute('aria-controls')).classList.toggle('open',open)}));
$('#search').addEventListener('input',renderServers);
$('#copy-sub').addEventListener('click',()=>copy(subscription));
$('#share').addEventListener('click',async()=>{if(navigator.share){try{await navigator.share({title:clientName,url:subscription})}catch(e){if(e.name!=='AbortError')toast('اشتراک‌گذاری انجام نشد')}}else copy(subscription)});
document.querySelectorAll('[data-app]').forEach(button=>button.addEventListener('click',()=>{location.href=button.dataset.app+'://install-sub?url='+encodeURIComponent(rawImport)+'&name='+encodeURIComponent(clientName||'Subscription')}));
$('#qr-open').addEventListener('click',()=>openQrDialog(signedId?{label:'کد اشتراک شما',text:subscription}:{label:'کد اشتراک شما',imageUrl:subscriptionQrUrl}));$('#qr-close').addEventListener('click',()=>$('#qr-dialog').close());$('#qr-dialog').addEventListener('click',e=>{if(e.target===$('#qr-dialog')||e.target.closest('#large-qr'))$('#qr-dialog').close()});
async function load(){
 try{
  if(!validId)throw Error('invalid subscription');
  const result=await window.subscriptionRequest;
  if(!result||result.error)throw Error('subscription unavailable');
  const {response,body}=result;
  if(!response.ok)throw Error('subscription unavailable');
  let content=body.trim();if(content&&!content.split(/\r?\n/).some(line=>SUBSCRIPTION_SCHEME.test(line.trim())))content=decode64(content);
  if(content.startsWith('<'))throw Error('invalid response');
  const all=content.split(/\r?\n/).map(s=>s.trim()).filter(s=>SUBSCRIPTION_SCHEME.test(s)).map(parseLine);
  const header=response.headers.get('Subscription-Userinfo')||response.headers.get('X-Subscription-Userinfo')||'';
  const info=Object.fromEntries([...header.matchAll(/([a-z_]+)=(-?\d+)/gi)].map(m=>[m[1].toLowerCase(),Number(m[2])]));
  let expire=info.expire||0;if(expire>100000000000)expire/=1000;
  const expired=expire>0&&expire<=Date.now()/1000;const known=Object.hasOwn(info,'total');const unlimited=known&&info.total<=0;
  const used=Math.max(0,info.upload||0)+Math.max(0,info.download||0),total=info.total||0,remaining=Math.max(0,total-used);
  document.body.dataset.state=expired?'expired':unlimited?'unlimited':'active';
  clientName=titleHeader(response.headers.get('X-TG3XBot-Client-Title'))||titleHeader(response.headers.get('Profile-Title')).split(' | ')[0]||'اشتراک شما';
  $('h1').textContent=clientName;document.title=clientName+' · اشتراک';
  $('#status').innerHTML='<b></b>'+(expired?'اشتراک پایان‌یافته':total>0&&remaining===0?'حجم اشتراک تمام شده':'اشتراک فعال');
  $('.identity-meta>span:last-child').textContent='آخرین به‌روزرسانی: '+new Date().toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'});
  $('#plan').textContent=unlimited?'اشتراک نامحدود':known?'سرویس حجمی':'اشتراک';
  $('#volume-label').textContent=unlimited?'حجم مصرف‌شده':'حجم باقی‌مانده';
  $('#remaining').textContent=known?((unlimited?used:remaining)/1073741824).toFixed(1):'--';
  $('#percent').textContent=expired?'زمان اشتراک تمام شده':unlimited?'بدون محدودیت حجم':known?digits.format(total?remaining/total*100:0)+'٪ باقی مانده':'اطلاعات حجم در دسترس نیست';
  const percent=total>0?Math.min(100,remaining/total*100):100;$('.progress span').style.width=(expired?0:percent)+'%';$('.progress').setAttribute('aria-valuenow',String(expired?0:percent));
  $('#usage-caption').textContent=known?bytes(used)+' مصرف‌شده'+(unlimited?'':' از '+bytes(total)):'اطلاعات مصرف در دسترس نیست';
  $('#days').textContent=expire>0?digits.format(Math.max(0,Math.ceil((expire-Date.now()/1000)/86400)))+' روز':expire<0?'شروع با اولین اتصال':'بدون محدودیت زمانی';
  if(expire<=0)$('#days').parentNode.lastChild.textContent='';
  const details=$$('.stats dd');details[0].textContent=bytes(info.download||0);details[1].textContent=bytes(info.upload||0);
  details[2].previousElementSibling.textContent='مدت زمان باقی‌مانده';details[2].textContent=$('#days').textContent;
  details[3].textContent=expire>0?new Date(expire*1000).toLocaleDateString('fa-IR'):expire<0?'پس از اولین اتصال':'بدون محدودیت';
  configs=expired?[{name:'اشتراک شما به پایان رسیده است',warning:true}]:all.filter(c=>!c.raw.includes('00000000-0000-4000-8000-000000000000')).map(c=>({...c,originalName:c.name,name:serverDisplayName(c.name)}));
  $('#server-count').textContent=digits.format(configs.length);renderServers();
  document.body.classList.remove('loading');$('#load-gate').remove();
  subscriptionQrUrl='/tg3xbot-sub-qr/'+encodeURIComponent(subId)+'.png?path='+encodeURIComponent('/'+subId);
  if(signedId){new QRCode($('#qr'),{text:subscription,width:152,height:152,colorDark:'#000000',colorLight:'#ffffff',correctLevel:QRCode.CorrectLevel.M});$('#qr').removeAttribute('title')}else{const img=document.createElement('img');img.width=152;img.height=152;img.alt='کد اشتراک';img.decoding='async';img.src=subscriptionQrUrl;$('#qr').append(img)}
 }catch(e){$('#load-gate').replaceChildren();const message=document.createElement('p');message.textContent='دریافت اشتراک انجام نشد. اتصال اینترنت و لینک اشتراک را بررسی کنید.';const retry=document.createElement('button');retry.className='primary-button';retry.textContent='تلاش دوباره';retry.onclick=()=>location.reload();$('#load-gate').append(message,retry)}
}
function $$(s){return [...document.querySelectorAll(s)]}lucide.createIcons();load();

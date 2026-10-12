(function(root){
 function cleanServerName(name,client){
  let value=String(name||'').trim();
  const variants=[String(client||'').trim(),String(client||'').trim().replace(/-[a-f0-9]{8}$/i,'')].filter(Boolean).sort((a,b)=>b.length-a.length);
  for(const variant of variants){
   const escaped=variant.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
   value=value.replace(new RegExp('[\\s|–—-]+'+escaped+'(?:-[a-f0-9]{8})?$','i'),'').trim();
  }
  return value;
 }
 const collator=new Intl.Collator('en',{numeric:true,sensitivity:'base'});
 function compareServers(a,b){
  const normalize=s=>s.replace(/[۰-۹]/g,c=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c))).replace(/[٠-٩]/g,c=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(c))).replace(/^[^\p{L}\p{N}]+/u,'');
  return collator.compare(normalize(a.name),normalize(b.name));
 }
 root.serverLabels={cleanServerName,compareServers};
 if(typeof module!=='undefined')module.exports=root.serverLabels;
})(globalThis);

/* Opt-in, same-origin observation. No field values, payloads, credentials or user text. */
(()=>{'use strict';
 if(new URLSearchParams(location.search).get('cv-observe')!=='1'||!window.opener)return;
 const parent=window.opener,origin=location.origin;
 try{if(parent.location.origin!==origin)return;}catch(_){return;}
 let active=true,timer;const nativeFetch=window.fetch,knownTargets=new Set(['/api/health']);
 nativeFetch('/functional-map.manifest.json',{cache:'no-store'}).then(r=>r.json()).then(map=>{for(const control of map.current?.controls||[])for(const handler of control.handlers||[])for(const endpoint of handler.endpoints||[])knownTargets.add(endpoint);}).catch(()=>{});
 const clean=value=>typeof value==='string'&&/^[\w#:.>()[\]=" -]{1,240}$/.test(value)?value:null;
 function selector(element){if(element.id)return '#'+element.id;const parts=[];for(let current=element;current;current=current.parentElement){if(current.id){parts.unshift('#'+current.id);break;}const siblings=current.parentElement?[...current.parentElement.children].filter(s=>s.tagName===current.tagName):[current];parts.unshift(current.tagName.toLowerCase()+':nth-of-type('+(siblings.indexOf(current)+1)+')');}return parts.join('>');}
 function send(data){if(active&&!parent.closed)parent.postMessage({channel:'cv-functional-v1',path:location.pathname,...data},origin);}
 function snapshot(){timer=null;const controls=[...document.querySelectorAll('button,a,input,select,textarea,summary')].slice(0,1500).map(element=>({selector:clean(selector(element)),tag:element.tagName.toLowerCase(),disabled:!!element.disabled||element.getAttribute('aria-disabled')==='true'||!!element.closest('[inert]'),hidden:!!element.closest('[hidden]')||getComputedStyle(element).display==='none'||getComputedStyle(element).visibility==='hidden'||element.getClientRects().length===0,busy:element.getAttribute('aria-busy')==='true'})).filter(x=>x.selector);send({type:'snapshot',path:location.pathname,controls});}
 function schedule(){if(!timer&&active)timer=setTimeout(snapshot,250);}
 function target(value){try{const url=new URL(typeof value==='string'?value:value.url,location.href);if(url.origin!==origin)return url.origin;return knownTargets.has(url.pathname)?url.pathname:'/ruta-no-inventariada';}catch(_){return '(destino no identificado)';}}
 window.fetch=function(...args){const destination=target(args[0]);const promise=nativeFetch.apply(this,args);promise.then(response=>send({type:'http',target:destination,status:response.status}),()=>send({type:'http',target:destination,status:0}));return promise;};
 document.addEventListener('click',event=>{const element=event.target.closest?.('button,a,input,select,textarea,summary');if(element){const id=clean(selector(element));if(id)send({type:'action',selector:id});}},true);
 for(const event of ['cv-loading-started','cv-loading-finished','cv-loading-background'])window.addEventListener(event,()=>send({type:'loading',state:event.replace('cv-loading-','')}));
 window.addEventListener('error',()=>send({type:'error',kind:'javascript'}));window.addEventListener('unhandledrejection',()=>send({type:'error',kind:'promise'}));
 const observer=new MutationObserver(schedule);observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','disabled','inert','aria-disabled','aria-busy','class','style','open']});
 window.addEventListener('message',event=>{if(event.origin===origin&&event.source===parent&&event.data?.channel==='cv-functional-stop'){active=false;observer.disconnect();clearTimeout(timer);if(window.fetch!==nativeFetch)window.fetch=nativeFetch;}});
 window.addEventListener('pagehide',()=>send({type:'navigation',target:location.pathname}));snapshot();
})();

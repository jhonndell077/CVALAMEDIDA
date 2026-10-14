(function (root) {
  'use strict';
  // Shared timing for the native adaptation of the expanding-card effect.
  const tokens = Object.freeze({fast:180, normal:350, slow:600, stagger:60,
    ease:'cubic-bezier(.22,1,.36,1)', distance:24});
  const doc=root.document;
  if (!doc || !root.MutationObserver) return;
  const reduced=root.matchMedia?.('(prefers-reduced-motion: reduce)');
  const cards=new WeakSet(), dialogs=new WeakMap(), active=new Map(), ghosts=new Set();
  let origin=null;
  const enabled=()=>!reduced?.matches && !doc.hidden;
  function rect(element) {
    const box=element?.getBoundingClientRect?.();
    return box && box.width>0 && box.height>0 ? {left:box.left,top:box.top,width:box.width,height:box.height} : null;
  }
  function animate(element,frames,options={}) {
    if (!enabled() || !element.animate) return null;
    active.get(element)?.cancel();
    const animation=element.animate(frames,{duration:tokens.normal,easing:tokens.ease,...options});
    active.set(element,animation);
    animation.finished.then(()=>{if(active.get(element)===animation)active.delete(element);},()=>{});
    return animation;
  }
  function transform(from,to) {
    if (!from || !to) return 'translateY(24px) scale(.96)';
    const x=from.left+from.width/2-to.left-to.width/2;
    const y=from.top+from.height/2-to.top-to.height/2;
    return `translate(${x}px,${y}px) scale(${Math.min(1.2,Math.max(.08,from.width/to.width))},${Math.min(1.2,Math.max(.08,from.height/to.height))})`;
  }
  function clearMotion() {
    for(const animation of active.values())animation.cancel();
    active.clear();for(const ghost of ghosts)ghost.remove();ghosts.clear();
  }
  doc.addEventListener('click',event=>{
    const trigger=event.target.closest?.('button,a,summary');
    if (trigger) origin={box:rect(trigger.closest('.profile-node,#employment-results article') || trigger),at:Date.now()};
  },true);
  function cardToggle(card) {
    if (!enabled() || !card.isConnected) return;
    const body=card.querySelector(':scope > .profile-node-body,:scope > .profile-fields');
    const icon=card.querySelector('.profile-card-icon');
    if (card.open) {
      if(body)animate(body,[{opacity:0,transform:'translateY(-24px)'},{opacity:1,transform:'translateY(0)'}]);
      if(icon)animate(icon,[{transform:'scale(1.25) rotate(-8deg)'},{transform:'scale(1) rotate(0)'}]);
    } else animate(card,[{opacity:.65,transform:'translateY(-16px)'},{opacity:1,transform:'translateY(0)'}],{duration:tokens.fast});
    [...doc.querySelectorAll('#profile-tree > .profile-node')].filter(item=>item!==card).forEach((item,index)=>{
      animate(item,[{opacity:1,transform:'translateY(0)'},{opacity:.45,transform:'translateY(-16px)',offset:.35},
        {opacity:1,transform:'translateY(0)'}],{duration:tokens.slow,delay:Math.min(index,5)*tokens.stagger});
    });
  }
  function scan() {
    [...doc.querySelectorAll('#profile-tree > .profile-node')].forEach((card,index)=>{
      if(cards.has(card))return;cards.add(card);
      card.addEventListener('toggle',()=>cardToggle(card));
      animate(card,[{opacity:0,transform:'translateY(24px)'},{opacity:1,transform:'translateY(0)'}],
        {delay:Math.min(index,5)*tokens.stagger});
    });
    for(const dialog of doc.querySelectorAll('dialog')) {
      if(!dialogs.has(dialog))dialogs.set(dialog,{open:dialog.open,source:null,box:null});
    }
  }
  function dialogChanged(dialog) {
    const state=dialogs.get(dialog);if(!state || state.open===dialog.open)return;
    state.open=dialog.open;
    if (dialog.open) {
      state.box=rect(dialog);state.source=origin && Date.now()-origin.at<2000 ? origin.box : null;
      animate(dialog,[{opacity:.15,transform:transform(state.source,state.box)},
        {opacity:1,transform:'translate(0,0) scale(1,1)'}]);
    } else {
      active.get(dialog)?.cancel();active.delete(dialog);
      if(!enabled() || !state.box || !doc.body.animate)return;
      // An inert color cover contracts back to the card; no forms or data are cloned.
      const ghost=doc.createElement('div');ghost.className='cv-motion-cover';ghost.setAttribute('aria-hidden','true');
      Object.assign(ghost.style,{left:state.box.left+'px',top:state.box.top+'px',width:state.box.width+'px',height:state.box.height+'px'});
      doc.body.append(ghost);ghosts.add(ghost);
      const animation=animate(ghost,[{opacity:.35,transform:'scale(1)'},
        {opacity:0,transform:transform(state.source,state.box)}],{duration:tokens.fast});
      const remove=()=>{ghost.remove();ghosts.delete(ghost);};
      if(animation)animation.finished.then(remove,remove);else remove();
    }
  }
  const observer=new root.MutationObserver(records=>{
    scan();
    for(const record of records)if(record.type==='attributes' && record.target.tagName==='DIALOG')dialogChanged(record.target);
  });
  scan();observer.observe(doc.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});
  root.addEventListener('resize',clearMotion);
  doc.addEventListener('visibilitychange',()=>{if(doc.hidden)clearMotion();});
  reduced?.addEventListener?.('change',clearMotion);
})(typeof window !== 'undefined' ? window : globalThis);

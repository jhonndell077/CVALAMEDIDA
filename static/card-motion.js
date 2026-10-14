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
  const revealed=new WeakSet();
  const revealObserver=root.IntersectionObserver ? new root.IntersectionObserver(entries=>{
    for(const entry of entries) {
      if(!entry.isIntersecting || entry.target.hidden) continue;
      const element=entry.target;
      if(enabled()) animate(element,[{opacity:0,transform:'translateY(90px) scale(.86) rotate(-2deg)'},
        {opacity:1,transform:'translateY(-10px) scale(1.025) rotate(.4deg)',offset:.75},
        {opacity:1,transform:'translateY(0) scale(1) rotate(0)'}],{duration:tokens.slow});
      revealObserver.unobserve(element);
    }
  },{threshold:.08}) : null;
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
  doc.addEventListener('pointerdown',event=>{
    const button=event.target.closest?.('button');
    if(button && !button.disabled) animate(button,[{transform:'scale(1)'},{transform:'scale(.9) translateY(3px)'}],{duration:tokens.fast});
  },true);
  doc.addEventListener('click',event=>{
    const button=event.target.closest?.('button');
    if(button && !button.disabled && enabled()) {
      animate(button,[{transform:'scale(.9)'},{transform:'scale(1.09) translateY(-5px)',offset:.5},{transform:'scale(1)'}],{duration:tokens.slow});
      const wave=doc.createElement('span');wave.className='cv-button-wave';wave.setAttribute('aria-hidden','true');
      const box=rect(button);
      if(box) {
        const size=Math.max(box.width,box.height)*2;
        Object.assign(wave.style,{width:size+'px',height:size+'px',left:((event.detail && Number.isFinite(event.clientX) ? event.clientX-box.left : box.width/2)-size/2)+'px',top:((event.detail && Number.isFinite(event.clientY) ? event.clientY-box.top : box.height/2)-size/2)+'px'});
        button.append(wave);ghosts.add(wave);
        const motion=animate(wave,[{transform:'scale(0)',opacity:.65},{transform:'scale(1)',opacity:0}],{duration:tokens.slow});
        const remove=()=>{wave.remove();ghosts.delete(wave);};
        if(motion)motion.finished.then(remove,remove);else remove();
      }
    }
  },true);
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
    for(const panel of doc.querySelectorAll('.shell > .panel,.shell > .hero')) {
      if(revealed.has(panel))continue;revealed.add(panel);revealObserver?.observe(panel);
    }
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

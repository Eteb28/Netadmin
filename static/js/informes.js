// informes.js — Sección de informes de Pucará (datos reales)
let _infDias = 90;

async function loadInformes(){
  const seg = document.getElementById('inf-seg');
  if(seg && !seg._wired){
    seg._wired = true;
    seg.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{
      seg.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
      b.classList.add('on'); _infDias = parseInt(b.dataset.d); loadInformes();
    }));
  }
  const d = await api('/api/informes/resumen?dias=' + _infDias);
  if(!d){ return; }
  const upd = document.getElementById('inf-updated');
  if(upd) upd.textContent = new Date().toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'});

  _infKpis(d.kpis);
  _infChurn(d.altas_bajas, d.meses);
  _infResumen(d.kpis);
  _infRank('inf-vend', d.vendedores, 'altas', 'altas');
  _infRank('inf-tec', d.tecnicos, 'trabajos', 'trab.');
  _infFact(d.facturacion, d.meses);
  _infGauge(d.kpis.cobrabilidad);
  _infCobPills(d.kpis.cobrabilidad);
  _infRentabilidad();
}

function _fmtMoney(n){
  if(n>=1e6) return '$'+(n/1e6).toFixed(1).replace('.',',')+'M';
  if(n>=1e3) return '$'+Math.round(n/1e3)+'k';
  return '$'+n;
}
function _fmtNum(n){ return n.toLocaleString('es-AR'); }

// ── KPIs ──
function _infKpis(k){
  const c = document.getElementById('inf-kpis');
  if(!c) return;
  const cards = [
    {l:'Clientes activos', n:_fmtNum(k.activos), chip:(k.altas_delta>=0?'+':'')+k.altas_delta, cls:k.altas_delta>=0?'up':'down', f:'altas netas 30d vs previo'},
    {l:'Facturación mensual', n:_fmtMoney(k.facturacion), chip:(k.facturacion_delta_pct>=0?'+':'')+k.facturacion_delta_pct+'%', cls:k.facturacion_delta_pct>=0?'up':'down', f:'ARS · cobrado del ERP'},
    {l:'Bajas del mes', n:_fmtNum(k.bajas_30), chip:'30d', cls:'down', f:'rescisiones y bajas'},
    {l:'Cobrabilidad', n:k.cobrabilidad+'%', chip:'pagado', cls:'up', f:'recibos pagados / total'},
  ];
  c.innerHTML = cards.map(x=>`<div class="inf-k">
    <span class="inf-chip ${x.cls}">${x.cls==='up'?'▲':'▼'} ${x.chip}</span>
    <div class="kl">${x.l}</div><div class="kn">${x.n}</div><div class="kf">${x.f}</div>
  </div>`).join('');
}

function _infResumen(k){
  const sub = document.getElementById('inf-ab-sub');
  if(sub) sub.textContent = 'Ventana de 30 días.';
  const p = document.getElementById('inf-ab-pills');
  const neto = k.altas_30 - k.bajas_30;
  if(p) p.innerHTML = `
    <div class="inf-pill"><div class="pl">Altas</div><div class="pv" style="color:var(--i-up)">${k.altas_30}</div></div>
    <div class="inf-pill"><div class="pl">Bajas</div><div class="pv" style="color:var(--i-down)">${k.bajas_30}</div></div>
    <div class="inf-pill"><div class="pl">Neto</div><div class="pv">${neto>=0?'+':''}${neto}</div></div>
    <div class="inf-pill"><div class="pl">Activos</div><div class="pv">${_fmtNum(k.activos)}</div></div>`;
}

function _infCobPills(cob){
  const p = document.getElementById('inf-cob-pills');
  if(p) p.innerHTML = `
    <div class="inf-pill"><div class="pl">Cobrado</div><div class="pv" style="color:var(--i-up)">${cob}%</div></div>
    <div class="inf-pill"><div class="pl">Pendiente</div><div class="pv" style="color:var(--i-gold)">${(100-cob).toFixed(1)}%</div></div>`;
}

// ── Ranking genérico ──
function _infRank(id, items, valKey, unit){
  const c = document.getElementById(id);
  if(!c) return;
  if(!items || !items.length){ c.innerHTML = '<div style="color:var(--i-faint);font-size:.82rem;padding:.5rem 0">Sin datos en el período.</div>'; return; }
  const max = Math.max(...items.map(i=>i[valKey]||0)) || 1;
  c.innerHTML = items.map((it,i)=>`<div class="inf-rrow ${i===0?'gold':''}">
    <span class="rp">${i+1}</span>
    <div><div class="rw">${escHtml(it.nombre)||'—'}</div><div class="rbar"><i style="width:${(it[valKey]||0)/max*100}%"></i></div></div>
    <div class="rv">${it[valKey]||0} <small>${unit}</small></div>
  </div>`).join('');
}

// ── SVG helpers (misma estética de la demo) ──
const _NS='http://www.w3.org/2000/svg';
function _el(t,a){const e=document.createElementNS(_NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
function _smooth(pts){
  if(pts.length<3) return pts.map((p,i)=>(i?'L':'M')+p[0]+' '+p[1]).join(' ');
  let d='M'+pts[0][0]+' '+pts[0][1];
  for(let i=0;i<pts.length-1;i++){
    const p0=pts[i-1]||pts[i],p1=pts[i],p2=pts[i+1],p3=pts[i+2]||p2;
    d+=`C${(p1[0]+(p2[0]-p0[0])/6).toFixed(1)} ${(p1[1]+(p2[1]-p0[1])/6).toFixed(1)},${(p2[0]-(p3[0]-p1[0])/6).toFixed(1)} ${(p2[1]-(p3[1]-p1[1])/6).toFixed(1)},${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}
function _grad(svg,id,c0,c1,vert){
  const defs=_el('defs',{});const g=_el('linearGradient',{id:id,x1:'0',y1:'0',x2:vert?'0':'1',y2:vert?'1':'0'});
  g.appendChild(_el('stop',{offset:'0','stop-color':c0}));g.appendChild(_el('stop',{offset:'1','stop-color':c1}));
  defs.appendChild(g);svg.appendChild(defs);
}
function _mLabels(meses){ // 'YYYY-MM' -> inicial del mes
  const M=['E','F','M','A','M','J','J','A','S','O','N','D'];
  return meses.map(m=>M[parseInt(m.slice(5,7))-1]);
}

// ── Churn: altas/bajas + neto ──
function _infChurn(ab, meses){
  const svg=document.getElementById('inf-churn'); if(!svg) return; svg.innerHTML='';
  const W=720,H=260,pad=30,base=H*0.62;
  const altas=ab.altas.map(x=>x.valor), bajas=ab.bajas.map(x=>x.valor);
  const maxv=Math.max(1,...altas,...bajas);
  const bw=(W-pad*2)/altas.length*0.42;
  svg.appendChild(_el('line',{x1:pad,y1:base,x2:W-pad,y2:base,stroke:'#243A52'}));
  altas.forEach((v,i)=>{
    const x=pad+(i+.5)*((W-pad*2)/altas.length);
    const ha=v/maxv*(base-20), hb=bajas[i]/maxv*(base-20);
    svg.appendChild(_el('rect',{x:x-bw-1,y:base-ha,width:bw,height:ha,rx:3,fill:'#4FB3AA',opacity:'.9'}));
    svg.appendChild(_el('rect',{x:x+1,y:base,width:bw,height:hb,rx:3,fill:'#E08063',opacity:'.85'}));
  });
  // neto acumulado
  let acc=0; const net=altas.map((a,i)=>{acc+=a-bajas[i];return acc;});
  const nmx=Math.max(...net,1),nmn=Math.min(...net,0);
  const npts=net.map((v,i)=>[pad+(i+.5)*((W-pad*2)/altas.length),(H-16)-((v-nmn)/((nmx-nmn)||1))*(H*0.4)]);
  svg.appendChild(_el('path',{d:_smooth(npts),fill:'none',stroke:'#E0A838','stroke-width':'2.5','stroke-linecap':'round'}));
  npts.forEach(p=>svg.appendChild(_el('circle',{cx:p[0],cy:p[1],r:'2.5',fill:'#0A131E',stroke:'#E0A838','stroke-width':'1.5'})));
  // labels
  const L=_mLabels(meses);
  L.forEach((lb,i)=>{const x=pad+(i+.5)*((W-pad*2)/altas.length);const t=_el('text',{x:x,y:base+14,'text-anchor':'middle',fill:'#566B84','font-size':'10','font-family':'monospace'});t.textContent=lb;svg.appendChild(t);});
}

// ── Facturación bars ──
function _infFact(fact, meses){
  const svg=document.getElementById('inf-fact'); if(!svg) return; svg.innerHTML='';
  const W=720,H=240,pad=30,base=H-24;
  const d=fact.map(x=>x.valor); const mx=Math.max(1,...d); const bw=(W-pad*2)/d.length*0.56;
  _grad(svg,'iffg','#E0A838','#9B7327',true);
  const L=_mLabels(meses);
  d.forEach((v,i)=>{
    const x=pad+(i+.5)*((W-pad*2)/d.length); const h=v/mx*(base-14);
    svg.appendChild(_el('rect',{x:x-bw/2,y:base-h,width:bw,height:h,rx:4,fill:'url(#iffg)'}));
    const t=_el('text',{x:x,y:base+14,'text-anchor':'middle',fill:'#566B84','font-size':'10','font-family':'monospace'});t.textContent=L[i];svg.appendChild(t);
  });
  svg.appendChild(_el('line',{x1:pad,y1:base,x2:W-pad,y2:base,stroke:'#243A52'}));
}

// ── Gauge cobrabilidad ──
function _infGauge(pct){
  const svg=document.getElementById('inf-gauge'); if(!svg) return; svg.innerHTML='';
  const cx=110,cy=120,r=80; const p=pct/100;
  function arc(a0,a1,color,w){
    const p0=[cx+r*Math.cos(Math.PI-a0*Math.PI),cy-r*Math.sin(Math.PI-a0*Math.PI)];
    const p1=[cx+r*Math.cos(Math.PI-a1*Math.PI),cy-r*Math.sin(Math.PI-a1*Math.PI)];
    const large=a1-a0>0.5?1:0;
    svg.appendChild(_el('path',{d:`M${p0[0]} ${p0[1]} A${r} ${r} 0 ${large} 1 ${p1[0]} ${p1[1]}`,fill:'none',stroke:color,'stroke-width':w,'stroke-linecap':'round'}));
  }
  arc(0,1,'#243A52',13);
  arc(0,p,'#4FB88A',13);
  const t=_el('text',{x:cx,y:cy-6,'text-anchor':'middle',fill:'var(--card)','font-size':'28','font-family':"'Space Grotesk'",'font-weight':'600'});t.textContent=Math.round(pct)+'%';svg.appendChild(t);
  const t2=_el('text',{x:cx,y:cy+12,'text-anchor':'middle',fill:'#8FA6BF','font-size':'10','font-family':'monospace'});t2.textContent='COBRADO';svg.appendChild(t2);
}

// ── Rentabilidad: Contabilidad → Informes ──
async function _infRentabilidad(){
  const card = document.getElementById('inf-rent-card');
  const empty = document.getElementById('inf-rent-empty');
  if(!card) return;
  const r = await api('/api/contabilidad/resumen');
  // Sin acceso o sin egresos cargados → mostrar el mensaje que guía a Contabilidad
  if(!r || !r.tiene_egresos){
    card.style.display = 'none';
    if(empty) empty.style.display = '';
    return;
  }
  card.style.display = '';
  if(empty) empty.style.display = 'none';
  _infRentChart(r);
  _infRentPills(r);
}

function _infRentChart(r){
  const svg = document.getElementById('inf-rent'); if(!svg) return; svg.innerHTML = '';
  const W=720, H=260, pad=30, base=H*0.62;
  const ing = r.ingresos.map(x=>x.valor), egr = r.egresos.map(x=>x.valor), gan = r.ganancia.map(x=>x.valor);
  const maxv = Math.max(1, ...ing, ...egr);
  const bw = (W-pad*2)/ing.length*0.42;
  svg.appendChild(_el('line', {x1:pad, y1:base, x2:W-pad, y2:base, stroke:'#243A52'}));
  // Barras agrupadas: ingresos (izq) vs egresos (der), ambas hacia arriba
  ing.forEach((v,i)=>{
    const x = pad+(i+.5)*((W-pad*2)/ing.length);
    const hi = v/maxv*(base-20), he = egr[i]/maxv*(base-20);
    svg.appendChild(_el('rect', {x:x-bw-1, y:base-hi, width:bw, height:hi, rx:3, fill:'#4FB3AA', opacity:'.9'}));
    svg.appendChild(_el('rect', {x:x+1, y:base-he, width:bw, height:he, rx:3, fill:'#E08063', opacity:'.85'}));
  });
  // Línea de ganancia (puede ser negativa)
  const gmx = Math.max(...gan, 1), gmn = Math.min(...gan, 0);
  const gpts = gan.map((v,i)=>[pad+(i+.5)*((W-pad*2)/ing.length), (H-16)-((v-gmn)/((gmx-gmn)||1))*(H*0.4)]);
  svg.appendChild(_el('path', {d:_smooth(gpts), fill:'none', stroke:'#E0A838', 'stroke-width':'2.5', 'stroke-linecap':'round'}));
  gpts.forEach(p=>svg.appendChild(_el('circle', {cx:p[0], cy:p[1], r:'2.5', fill:'#0A131E', stroke:'#E0A838', 'stroke-width':'1.5'})));
  // Etiquetas de mes
  const L = _mLabels(r.meses);
  L.forEach((lb,i)=>{
    const x = pad+(i+.5)*((W-pad*2)/ing.length);
    const t = _el('text', {x:x, y:base+14, 'text-anchor':'middle', fill:'#566B84', 'font-size':'10', 'font-family':'monospace'});
    t.textContent = lb; svg.appendChild(t);
  });
}

function _infRentPills(r){
  const p = document.getElementById('inf-rent-pills'); if(!p) return;
  const tIng = r.ingresos.reduce((a,x)=>a+x.valor, 0);
  const tEgr = r.egresos.reduce((a,x)=>a+x.valor, 0);
  const tGan = tIng - tEgr;
  const margen = tIng > 0 ? (tGan/tIng*100) : 0;
  p.innerHTML = `
    <div class="inf-pill"><div class="pl">Ingresos 12m</div><div class="pv" style="color:var(--i-up)">${_fmtMoney(tIng)}</div></div>
    <div class="inf-pill"><div class="pl">Egresos 12m</div><div class="pv" style="color:var(--i-down)">${_fmtMoney(tEgr)}</div></div>
    <div class="inf-pill"><div class="pl">Ganancia 12m</div><div class="pv" style="color:${tGan>=0?'var(--i-up)':'var(--i-down)'}">${_fmtMoney(tGan)}</div></div>
    <div class="inf-pill"><div class="pl">Margen</div><div class="pv">${margen.toFixed(1)}%</div></div>`;
}

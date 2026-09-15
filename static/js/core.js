/* ========================================================
   core.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

let carouselItems=[], carouselIdx=0, carouselTimer=null;

let searchTimeout=null;

/* Escapa texto antes de insertarlo en HTML armado a mano (innerHTML/template
   literals). Usar SIEMPRE con datos que vengan de la base (nombre, dirección,
   observaciones, etc.): cualquier usuario con permiso de editar un cliente
   podría, si no se escapa, inyectar HTML/JS que se ejecute en el navegador
   de otro usuario (ej. un admin) al ver ese registro.
   OJO: a propósito escapa también comillas simples y dobles (no solo &<>),
   así sirve tanto para texto suelto como para meterlo dentro de un atributo
   ( title="...", value="...", onclick="fn('...')" ). Un helper "para texto"
   que no escapara comillas es una trampa: alguien lo termina usando también
   en un atributo tarde o temprano y el escape deja de proteger nada. */
function escHtml(s){
  if(s===null || s===undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* Alias histórico: mismo escapado, para el código que ya lo llama
   pensando específicamente en contexto de atributo. */
function escAttr(s){
  return escHtml(s);
}

/* Para meter texto DENTRO de un string JS embebido en un atributo, tipo
   onclick="fn('${escJs(x)}')". Esto es distinto de escAttr: el navegador
   primero decodifica las entidades HTML del atributo y RECIÉN DESPUÉS
   ejecuta ese texto decodificado como JS. Si solo se escapa como HTML
   (escAttr), un nombre con un apóstrofe (ej. "O'Brien") decodifica de
   vuelta a un apóstrofe suelto y rompe el string JS. Por eso acá primero
   se escapa como string JS (comillas simples y backslash) y DESPUÉS como
   atributo HTML — en el orden inverso al que el navegador va a deshacer. */
function escJs(s){
  const jsEscaped = String(s===null||s===undefined?'':s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  return escHtml(jsEscaped);
}

async function api(url, method='GET', body=null){
  try{
    const opts={method,headers:{'Content-Type':'application/json'},credentials:'same-origin'};
    if(body) opts.body=JSON.stringify(body);
    const r=await fetch(url,opts);
    if(r.status===401){
      // Evitar bucle: solo redirigir si no estamos ya yendo al login
      if(!window._yendoALogin){
        window._yendoALogin = true;
        window.location.href='/login';
      }
      return null;
    }
    if(!r.ok){
      console.warn('api',r.status,url);
      // Si el servidor mandó un JSON con {error:...}, devolverlo para que el front lo muestre
      try{
        const errBody = await r.json();
        if(errBody && typeof errBody === 'object') return errBody;
      }catch(_){ /* no era JSON */ }
      return null;
    }
    return r.json();
  }catch(e){console.error('api error',url,e);return null;}
}

async function loadLocalidades(){
  const locs=await api('/api/localidades');
  if(!locs) return;
  const dl=document.getElementById('loc-datalist');
  dl.innerHTML=locs.map(l=>`<option value="${l}">`).join('');
  // bajas también
  const bl=document.getElementById('baja-loc');
  bl.innerHTML='<option value="">Todas las localidades</option>'+locs.map(l=>`<option value="${l}">${l}</option>`).join('');
  const cl=document.getElementById('cli-loc');
  cl.innerHTML='<option value="">Todas las localidades</option>'+locs.map(l=>`<option value="${l}">${l}</option>`).join('');
}

function buildCarousel(incidencias){
  carouselItems=[];
  // Incidencias activas
  incidencias.filter(i=>i.estado==='abierta').forEach(i=>{
    const icons={critica:'🔴',alta:'🟠',media:'🟡',baja:'🟢'};
    carouselItems.push({
      icon:icons[i.prioridad]||'⚠️',
      title:`${i.tipo.replace(/_/g,' ').toUpperCase()}`,
      text:i.titulo,
      badge:i.prioridad,
      badgeClass:i.prioridad==='critica'?'b-critica':i.prioridad==='alta'?'b-urgente':'b-media'
    });
  });
  if(carouselItems.length===0){
    carouselItems=[{icon:'✅',title:'RED OPERATIVA',text:'Sin incidencias activas en este momento',badge:'OK',badgeClass:''}];
  }
  renderCarousel();
  clearInterval(carouselTimer);
  carouselTimer=setInterval(()=>{carouselIdx=(carouselIdx+1)%carouselItems.length;renderCarousel();},5000);
}

function renderCarousel(){
  const c=carouselItems[carouselIdx]||carouselItems[0];
  if(!c) return;
  document.querySelector('.carousel-icon').textContent=c.icon;
  document.getElementById('carousel-content').innerHTML=`
    <div class="carousel-slide active">
      <span class="carousel-title">${c.title}</span>
      <span class="carousel-text">${c.text}</span>
      ${c.badge?`<span class="carousel-badge">${c.badge.toUpperCase()}</span>`:''}
    </div>`;
}

function carouselNext(){carouselIdx=(carouselIdx+1)%carouselItems.length;renderCarousel();}

function carouselPrev(){carouselIdx=(carouselIdx-1+carouselItems.length)%carouselItems.length;renderCarousel();}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function generateFlatSparkline(len, value) {
  // Genera valores con leve variación para visualizar trend constante
  const arr = [];
  for (let i = 0; i < len; i++) {
    arr.push(value + Math.floor(Math.random() * 3) - 1);
  }
  return arr;
}

function drawBarLocalidades(localidades) {
  const wrap = document.getElementById('bar-localidades');
  if (!wrap || !localidades.length) return;
  const max = Math.max(...localidades.map(l => l.cantidad));
  wrap.innerHTML = '<div style="font-size:.78rem">' + localidades.map(l => {
    const pct = Math.round(l.cantidad * 100 / max);
    return `<div style="display:flex;align-items:center;gap:.5rem;padding:.3rem 0">
      <div style="width:90px;font-weight:700;font-size:.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${l.localidad}">${l.localidad}</div>
      <div style="flex:1;height:14px;background:var(--card);border-radius:3px;overflow:hidden">
        <div style="width:${pct}%;height:100%;background:#2d5a8e"></div>
      </div>
      <div style="width:60px;text-align:right;font-family:monospace;font-size:.78rem">${l.cantidad.toLocaleString()}</div>
    </div>`;
  }).join('') + '</div>';
}

function buildDashIncCompact(incs) {
  const lista = document.getElementById('dash-inc-list');
  const abiertas = incs.filter(i => i.estado === 'abierta' || i.estado === 'en_proceso');
  if (!abiertas.length) {
    lista.innerHTML = '<div class="empty">✅ Sin incidencias activas</div>';
    return;
  }
  lista.innerHTML = '<div class="inc-list-compact">' + abiertas.map(i => `
    <div class="inc">
      <div class="inc-prio ${i.prioridad}"></div>
      <div class="inc-info">
        <div class="inc-titulo">${i.titulo}</div>
        <div class="inc-meta">${i.tipo.replace(/_/g,' ')} ${i.afectados?'· '+i.afectados:''} ${i.tecnico?'· '+i.tecnico:'· Sin asignar'} · ${i.fecha_inicio?.slice(0,16)||''}</div>
      </div>
      <span class="badge b-${i.prioridad}">${(i.prioridad||'').toUpperCase()}</span>
    </div>`).join('') + '</div>';
}

function buildDashInc(incs){
  const lista=document.getElementById('dash-inc-list');
  const abiertas=incs.filter(i=>i.estado==='abierta'||i.estado==='en_proceso');
  if(!abiertas.length){lista.innerHTML='<div class="empty">✅ Sin incidencias activas</div>';return;}
  lista.innerHTML=abiertas.map(i=>`
    <div class="inc-card ${i.prioridad}" style="margin-bottom:.4rem">
      <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
        <span class="badge b-${i.prioridad}">${i.prioridad.toUpperCase()}</span>
        <b style="font-size:.83rem">${i.titulo}</b>
        <span class="badge b-${i.estado}" style="margin-left:auto">${estadoServLabel(i.estado)}</span>
      </div>
      <div style="font-size:.76rem;color:var(--txt2);margin-top:.2rem">${i.tipo.replace(/_/g,' ')} ${i.afectados?'| '+i.afectados:''} | ${i.fecha_inicio?.slice(0,16)||''}</div>
    </div>`).join('');
}

// ── CLIENTES ──

function parseDMS(val){
  if(val===null || val===undefined || val==='') return null;
  // Si ya es número, devolverlo
  if(typeof val === 'number') return isNaN(val) ? null : val;
  const s = String(val).trim();
  if(!s) return null;
  // Si es decimal puro (incluye signo, sin letras/símbolos DMS), parsearlo
  // Acepta: "-31.234", "60.5", "-60,5"
  if(/^-?\d+([.,]\d+)?$/.test(s)){
    return parseFloat(s.replace(',', '.'));
  }
  // Si tiene letras o símbolos DMS, intentar parsear como DMS
  // Formatos aceptados:
  //   31°44'04.2"S
  //   31°44'04"S
  //   -31 44 04.2
  //   31°44.07'S  (DDM, decimal en minutos)
  //   31°S         (sólo grados con cardinal)
  const m = s.match(/^\s*(-?)(\d{1,3})\s*[°ºd:]?\s*(\d{1,2}(?:[.,]\d+)?)?\s*['′m:]?\s*(\d{1,2}(?:[.,]\d+)?)?\s*["″s]?\s*([NSEWnsew]?)\s*$/);
  if(m){
    const deg = parseInt(m[2]);
    const mins = m[3] ? parseFloat(m[3].replace(',','.')) : 0;
    const secs = m[4] ? parseFloat(m[4].replace(',','.')) : 0;
    if(isNaN(deg)) return null;
    let dec = deg + mins/60 + secs/3600;
    const sign = m[1];
    const card = (m[5]||'').toUpperCase();
    if(sign==='-' || card==='S' || card==='W') dec = -dec;
    return Math.round(dec * 10000000) / 10000000;
  }
  // Último intento: parseFloat directo (por si es algo como "31.5  "  con basura)
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}

// Redes cache

function estadoLabel(e){
  return {
    activo:'Vigente', suspendido:'Suspendido', pte_rescision:'Pte. Rescisión',
    rescision:'Rescindido', baja:'Baja',
    pte_instalacion:'Pte. Instalación', pte_cambio:'Pte. Cambio',
    pte_calculo:'Pte. Cálculo', pte_suspension:'Pte. Suspensión',
    borrador:'Borrador', calculado:'Calculado', sin_contrato:'Sin contrato',
    venta:'En venta', activacion_pendiente:'Act. Pendiente',
    instalacion_pendiente:'Inst. Pendiente'
  }[e]||e||'—';
}

function estadoServLabel(e){
  return {pendiente:'Pendiente',en_proceso:'En Proceso',cerrado:'Cerrado',cancelado:'Cancelado',
          abierta:'Abierta',en_proceso:'En Proceso',cerrada:'Cerrada'}[e]||e||'—';
}

function tipoSvcLabel(t){
  const m={reparacion_fibra:'🔧 Rep. Fibra',reparacion_inalambrico:'📡 Rep. Inalámbrico',
    migracion_ftth:'🔄 Migración FTTH',cambio_domicilio:'🏠 Cambio Domicilio',
    instalacion:'🆕 Instalación',retiro_equipo:'📦 Retiro Equipo',
    service_con_costo:'💵 Service c/Costo',otro:'🔩 Otro'};
  return m[t]||t||'—';
}

async function cargarEquiposDatalist(){
  const d=await api('/api/stock');
  if(!d) return;
  const dl=document.getElementById('equipo-datalist');
  if(!dl) return;
  const items=[...(d.instalado||[]),...(d.manual||[])];
  dl.innerHTML=items.map(s=>`<option value="${s.modelo}">`).join('');
}

function renderAgenda(svcs, desde, hasta){
  const cal=document.getElementById('agenda-calendar');
  if(!svcs.length){cal.innerHTML='<div class="empty">Sin servicios para el período seleccionado</div>';return;}

  // Agrupar por fecha
  const byFecha={};
  svcs.forEach(s=>{
    const f=(s.fecha_programada||s.fecha_creacion?.slice(0,10)||'Sin fecha');
    if(!byFecha[f]) byFecha[f]=[];
    byFecha[f].push(s);
  });

  const dias=['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'];
  cal.innerHTML=Object.keys(byFecha).sort().map(fecha=>{
    const d=new Date(fecha+'T12:00:00');
    const diaStr=isNaN(d)?fecha:`${dias[d.getDay()]} ${d.getDate()}/${d.getMonth()+1}`;
    const items=byFecha[fecha];
    return `<div style="margin-bottom:.8rem">
      <div style="background:var(--az2);color:#fff;padding:.35rem .7rem;border-radius:7px 7px 0 0;font-weight:700;font-size:.82rem;display:flex;align-items:center;gap:.4rem">
        📅 ${diaStr} <span style="background:rgba(255,255,255,.2);border-radius:20px;padding:.05rem .45rem;font-size:.73rem">${items.length} servicios</span>
      </div>
      <div style="border:1px solid var(--brd);border-top:none;border-radius:0 0 7px 7px">
        ${items.map(s=>`<div style="padding:.5rem .7rem;border-bottom:1px solid var(--brd);display:flex;align-items:flex-start;gap:.5rem;flex-wrap:wrap">
          <span class="badge b-${s.prioridad||'normal'}">${escHtml((s.prioridad||'normal').toUpperCase())}</span>
          <div style="flex:1;min-width:150px">
            <div style="font-size:.83rem;font-weight:700">${escHtml(tipoSvcLabel(s.tipo))}</div>
            <div style="font-size:.77rem;color:var(--txt2)">${escHtml(s.cliente_nombre)||'Sin cliente'} ${s.cliente_tel?'| 📞 '+escHtml(s.cliente_tel):''}</div>
            <div style="font-size:.73rem;color:var(--txt2)">📍 ${escHtml(s.cliente_dir)||'—'}, ${escHtml(s.cliente_localidad)}</div>
            ${s.descripcion?`<div style="font-size:.72rem;color:var(--txt2);margin-top:.2rem">${escHtml(s.descripcion.slice(0,100))}</div>`:''}
          </div>
          <div style="display:flex;flex-direction:column;gap:.2rem;align-items:flex-end">
            ${s.tecnico?`<span class="badge b-normal">👷 ${escHtml(s.tecnico)}</span>`:'<span style="font-size:.72rem;color:var(--rj)">Sin técnico</span>'}
            <span class="badge b-${s.estado}">${escHtml(estadoServLabel(s.estado))}</span>
            <button class="btn btn-gray btn-xs" onclick="openProgramarSvc(${s.id},'${escJs(s.tecnico)}','${s.fecha_programada||''}')">📅 Reprogramar</button>
          </div>
        </div>`).join('')}
      </div>
    </div>`;
  }).join('');
}

// ══════════ Mosaico de Capacidad / Saturación de APs ══════════
// Mismo lenguaje visual que las tarjetas OLT (ver ap-mosaico.css).
let _capData = null;

async function cargarCapacidad(){
  const cont = document.getElementById('cap-lista');
  cont.innerHTML = '<div style="color:var(--txt2);padding:1rem">Cargando…</div>';
  _capData = await api('/api/capacidad/aps');
  if(!_capData){ cont.innerHTML = '<div style="color:var(--critico);padding:1rem">No se pudo cargar.</div>'; return; }
  renderResumenCap();
  renderCapacidad();
}

/* Mapea el estado del motor a las clases visuales del NOC */
function _capClase(estado){
  return estado==='critico' ? 'critico'
       : estado==='advertencia' ? 'alerta'
       : estado==='normal' ? 'optimo' : 'muerto';
}
function _capRotulo(a){
  if(a.snmp_estado === 'sin_snmp') return 'sin snmp';
  if(a.estado === 'sin_datos')     return 'sin datos';
  return a.estado==='critico' ? 'saturado'
       : a.estado==='advertencia' ? 'atención' : 'en línea';
}

function renderResumenCap(){
  const r = _capData.resumen || {};
  const cont = document.getElementById('cap-resumen');
  cont.className = 'ap-resumen';
  const kpi = (cls,label,val) =>
    `<div class="ap-kpi k-${cls}"><div class="v">${val||0}</div><div class="l">${label}</div></div>`;
  cont.innerHTML =
    kpi('total','APs', r.total) +
    kpi('critico','Saturados', r.criticos) +
    kpi('alerta','Atención', r.advertencia) +
    kpi('optimo','En línea', r.normal) +
    kpi('muerto','Sin datos', r.sin_datos) +
    kpi('total','Desbalance', r.desbalanceados);
}

/* Una celda del mosaico de señal */
function _seg(clase, label, valor){
  return `<div class="ap-seg s-${clase}"><span class="sv">${valor}</span><span class="sl">${label}</span></div>`;
}

function renderCapacidad(){
  const cont = document.getElementById('cap-lista');
  if(!_capData) return;
  const filtro = document.getElementById('cap-filtro').value;
  let aps = _capData.aps || [];
  if(filtro === 'desbalanceado')      aps = aps.filter(a => a.desbalanceado);
  else if(filtro === 'sin_perfil')    aps = aps.filter(a => !a.tiene_perfil);
  else if(filtro)                     aps = aps.filter(a => a.estado === filtro);

  cont.className = 'ap-mosaico';
  if(!aps.length){
    cont.className = '';
    cont.innerHTML = '<div style="color:var(--txt2);padding:1rem">Sin APs para este filtro.</div>';
    return;
  }

  // Orden: primero lo que necesita atención, luego por cantidad de clientes
  const sev = {critico:0, advertencia:1, normal:2, sin_datos:3};
  aps = aps.slice().sort((a,b)=>(sev[a.estado]-sev[b.estado]) || (b.clientes-a.clientes));

  cont.innerHTML = aps.map(a=>{
    const cls  = _capClase(a.estado);
    const d    = a.distribucion || {buena:0,media:0,pobre:0,sin_dato:0};
    const pct  = a.pct_capacidad;
    const rec  = a.recomendados;
    const umbral = a.umbral_advertencia || 80;

    // Barra de ocupación (se recorta al 100% pero el número muestra el real)
    const barra = pct!=null
      ? `<div class="ap-ocup">
           <div class="ap-ocup-tit"><span>Ocupación</span><b>${a.clientes}${rec?` / ${rec}`:''} · ${pct}%</b></div>
           <div class="ap-barra" style="--umbral:${Math.min(umbral,100)}%"><i style="width:${Math.min(pct,100)}%"></i></div>
         </div>`
      : `<div class="ap-ocup">
           <div class="ap-ocup-tit"><span>Ocupación</span><b>${a.clientes} clientes</b></div>
           <div style="font-size:.62rem;color:var(--txt2)">Sin perfil: no se puede calcular saturación</div>
         </div>`;

    // Mosaico de señal (equivalente visual a los puertos PON)
    const mosaico = `<div class="ap-senal">
        ${_seg(d.buena?'buena':'vacio','buena',   d.buena||0)}
        ${_seg(d.media?'media':'vacio','media',   d.media||0)}
        ${_seg(d.pobre?'pobre':'vacio','pobre',   d.pobre||0)}
        ${_seg('vacio','s/dato',                  d.sin_dato||0)}
      </div>`;

    const rssiCls = a.rssi_promedio==null ? '' :
      (a.rssi_promedio < -75 ? 'v-critico' : a.rssi_promedio < -65 ? 'v-alerta' : 'v-optimo');

    const avisos = [];
    if(!a.tiene_perfil)   avisos.push('<span class="ap-chip warn">sin perfil técnico</span>');
    if(a.desbalanceado)   avisos.push('<span class="ap-chip">desbalanceado en su torre</span>');
    if(a.snmp_estado==='sin_snmp') avisos.push('<span class="ap-chip warn">responde ping, no SNMP</span>');

    return `<div class="ap-card e-${cls}">
      <div class="ap-cab">
        <span class="ap-nom" title="${escAttr(a.modelo)}">${escHtml(a.modelo)}</span>
        <span class="ap-torre">${escHtml(a.torre_nombre)||'sin torre'}</span>
        <span class="ap-pill">${escHtml(_capRotulo(a))}</span>
      </div>
      <div class="ap-metricas">
        <div class="ap-metrica"><span class="v">${a.clientes}</span><span class="l">clientes</span></div>
        <div class="ap-metrica ${rssiCls}"><span class="v">${a.rssi_promedio!=null?a.rssi_promedio:'—'}</span><span class="l">rssi medio</span></div>
        <div class="ap-metrica"><span class="v">${rec||'—'}</span><span class="l">recomend.</span></div>
      </div>
      ${barra}
      ${mosaico}
      <div class="ap-motivo"><b>${escHtml(a.motivo)}</b>${avisos.length?`<div class="ap-avisos">${avisos.join('')}</div>`:''}</div>
    </div>`;
  }).join('');
}

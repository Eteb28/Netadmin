// ══════════ Dashboard de Capacidad / Salud de PONs (FTTH — Prioridad 3) ══════════
let _fcapData = null;
let _fcapPonAbierto = null;  // "oltId:pon" del PON expandido

async function cargarFtthCapacidad(){
  const cont = document.getElementById('fcap-lista');
  cont.innerHTML = '<div style="color:var(--txt2)">Cargando…</div>';
  _fcapData = await api('/api/ftth/pons');
  if(!_fcapData){ cont.innerHTML = '<div style="color:var(--critico)">No se pudo cargar.</div>'; return; }
  renderResumenFtth();
  renderFtthCapacidad();
}

function renderResumenFtth(){
  const r = _fcapData.resumen || {};
  const cont = document.getElementById('fcap-resumen');
  cont.className = 'ap-resumen';
  const kpi = (cls,label,val) => `<div class="ap-kpi k-${cls}"><div class="v">${val||0}</div><div class="l">${label}</div></div>`;
  cont.innerHTML =
    kpi('total','OLTs', r.olts) +
    kpi('total','PONs', r.pons) +
    kpi('critico','Saturados', r.criticos) +
    kpi('alerta','Atención', r.advertencia) +
    kpi('optimo','En línea', r.normal) +
    kpi('muerto','ONUs offline', r.onus_offline);
}

function _fcapColor(estado){
  return estado==='critico'?'#c62828':estado==='advertencia'?'#e8a13b':estado==='normal'?'#2e7d32':'#9e9e9e';
}

function renderFtthCapacidad(){
  const cont = document.getElementById('fcap-lista');
  if(!_fcapData) return;
  const filtro = document.getElementById('fcap-filtro').value;
  const olts = _fcapData.olts || [];
  let html = '';
  let algo = false;

  olts.forEach(olt=>{
    const pons = (olt.pons||[]).filter(p=>!filtro || p.estado===filtro);
    if(!pons.length) return;
    algo = true;
    const offOlt = olt.online===0;
    html += `<div style="margin-bottom:1.1rem">
      <div style="font-weight:700;margin-bottom:.5rem;display:flex;align-items:center;gap:.5rem">
        🖥️ ${escHtml(olt.olt)}
        ${offOlt?'<span class="ap-chip warn">OLT offline</span>':''}
        <span style="font-size:.72rem;color:var(--txt2);font-weight:400">${escHtml(olt.ubicacion)} · split ${olt.capacidad_pon}</span>
      </div>
      <div class="ap-mosaico" style="display:grid">`;
    const sev={critico:0,advertencia:1,normal:2,sin_datos:3};
    pons.slice().sort((a,b)=>(sev[a.estado]-sev[b.estado])||(a.pon-b.pon)).forEach(p=>{
      const cls = p.estado==='critico'?'critico':p.estado==='advertencia'?'alerta':p.estado==='normal'?'optimo':'muerto';
      const pct = p.pct_ocupacion;
      const key = `${olt.olt_id}:${p.pon}`;
      const abierto = _fcapPonAbierto===key;
      const rotulo = p.estado==='critico'?'saturado':p.estado==='advertencia'?'atención':p.estado==='normal'?'en línea':'sin datos';
      html += `<div class="ap-card e-${cls}">
        <div class="ap-cab" style="cursor:pointer" onclick="toggleFcapPon(${olt.olt_id},${p.pon})">
          <span class="ap-nom">PON ${p.pon}</span>
          <span class="ap-pill">${rotulo}</span>
        </div>
        <div class="ap-metricas">
          <div class="ap-metrica"><span class="v">${p.onus_total}</span><span class="l">ONUs</span></div>
          <div class="ap-metrica v-optimo"><span class="v">${p.onus_online}</span><span class="l">online</span></div>
          <div class="ap-metrica ${p.onus_offline>0?'v-alerta':''}"><span class="v">${p.onus_offline}</span><span class="l">offline</span></div>
        </div>
        <div class="ap-ocup">
          <div class="ap-ocup-tit"><span>Ocupación del split</span><b>${p.onus_total} / ${p.capacidad}${pct!=null?` · ${pct}%`:''}</b></div>
          <div class="ap-barra" style="--umbral:80%"><i style="width:${pct!=null?Math.min(pct,100):0}%"></i></div>
        </div>
        <div class="ap-motivo"><b>${escHtml(p.motivo)}</b></div>
        <div id="fcap-onus-${olt.olt_id}-${p.pon}" class="ap-motivo" style="border-top:0;padding-top:0">${abierto?'<div style=\"color:var(--txt2);font-size:.75rem\">Cargando ONUs…</div>':'<span style=\"font-size:.62rem;color:var(--txt2)\">▾ tocá para ver las ONUs</span>'}</div>
      </div>`;
    });
    html += `</div></div>`;
  });

  cont.className = '';
  cont.innerHTML = algo ? html : '<div style="color:var(--txt2);padding:1rem">Sin PONs para este filtro. Si no aparece nada, verificá que el poller de OLT haya sondeado las ONUs.</div>';

  // si había un PON abierto, recargar sus ONUs
  if(_fcapPonAbierto){
    const [oid,pon]=_fcapPonAbierto.split(':');
    cargarOnusPon(parseInt(oid), parseInt(pon));
  }
}

function toggleFcapPon(oltId, pon){
  const key = `${oltId}:${pon}`;
  _fcapPonAbierto = (_fcapPonAbierto===key) ? null : key;
  renderFtthCapacidad();
}

async function cargarOnusPon(oltId, pon){
  const cont = document.getElementById(`fcap-onus-${oltId}-${pon}`);
  if(!cont) return;
  const r = await api(`/api/olts/${oltId}/clientes_por_pon?pon=${pon}`);
  const cli = (r && r.clientes) || [];
  if(!cli.length){ cont.innerHTML = '<div style="color:var(--txt2);font-size:.8rem">Sin ONUs reportadas en este PON.</div>'; return; }
  const rxColor = rx => rx==null?'#9e9e9e':(rx<-27||rx>-5)?'#c62828':(rx<-24||rx>-8)?'#e8a13b':'#2e7d32';
  cont.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.76rem">
    <thead><tr style="text-align:left;color:var(--txt2);border-bottom:1px solid var(--brd)">
      <th style="padding:.2rem .3rem">ONU</th><th>Cliente</th><th>RX (dBm)</th><th>Estado</th><th>Serial</th></tr></thead>
    <tbody>${cli.map(c=>`<tr style="border-bottom:1px solid var(--brd)">
      <td style="padding:.2rem .3rem">${c.onu??'—'}</td>
      <td>${escHtml(c.nombre||c.nro_cliente)||'—'}</td>
      <td style="color:${rxColor(c.rx_power)};font-weight:600">${c.rx_power!=null?c.rx_power:'—'}</td>
      <td>${c.online===1?'🟢 online':c.online===0?'🔴 offline':'—'}</td>
      <td style="font-size:.7rem">${c.serial_coincide==='difiere'?'⚠ difiere':escHtml(c.serial_onu)||'—'}</td>
    </tr>`).join('')}</tbody></table></div>`;
}

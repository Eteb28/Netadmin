/* ========================================================
   monitoreo.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadOltDatalist(){
  const olts=await api('/api/olts');
  if(!olts) return;
  oltData=olts;
  document.getElementById('olt-datalist').innerHTML=olts.map(o=>`<option value="${escAttr(o.nombre)}">`).join('');
}

async function showOltsOnMap(){
  removeLayer('olts');
  const data=await api('/api/olts');
  if(!data) return;
  const markers=data.filter(o=>o.lat&&o.lng).map(o=>{
    const icon=L.divIcon({className:'',html:`<div style="background:#0d47a1;color:#fff;border-radius:6px;padding:2px 5px;font-size:.65rem;font-weight:700;white-space:nowrap;border:2px solid var(--brd);box-shadow:0 2px 6px rgba(0,0,0,.3)">OLT</div>`,iconAnchor:[20,12]});
    return L.marker([o.lat,o.lng],{icon}).bindPopup(`<b>OLT: ${escHtml(o.nombre)}</b><br>IP: ${escHtml(o.ip_remota)||'—'}<br>Puertos PON: ${o.puertos_pon}<br>Clientes: ${o.total_clientes||0}`);
  });
  mapaLayers.olts=L.layerGroup(markers).addTo(map);
}

// ── BÚSQUEDA MAPA ──

async function loadOlts(){
  const d=await api('/api/olts');
  if(!d) return;
  const list=document.getElementById('olt-list');
  if(!d.length){list.innerHTML='<div class="empty">Sin OLTs cargadas. Agregá la primera.</div>';return;}
  list.classList.add('olt-mosaico');
  // Estado SNMP: toda la info de la OLT vive en la misma tarjeta
  let estMap = {};
  try {
    const est = await api('/api/olts/estado');
    if(est) est.forEach(e=>{ estMap[e.id] = e; });
  } catch(e){}
  list.innerHTML = d.map(o=>_oltTarjeta(o, estMap[o.id])).join('');
}

/* Tarjeta compacta de OLT (mosaico) */
function _oltTarjeta(o, est){
  const n = escJs(o.nombre);
  const online = est && est.snmp_activo && est.online == 1;
  const sinSnmp = !est || !est.snmp_activo;
  const estado = sinSnmp ? 'muerto' : (online ? _oltSalud(est) : 'critico');
  const rotulo = sinSnmp ? 'sin SNMP' : (online ? _oltRotulo(estado) : 'sin respuesta');
  // Motivo del estado: el backend explica POR QUÉ (antes decía "revisar" a secas)
  const motivo = sinSnmp ? 'El monitoreo SNMP no está activado para esta OLT'
               : (!online ? 'La OLT no respondió en el último sondeo'
               : ((est && est.motivo) || ''));

  // cabecera
  const cab = `<div class="olt-cab">
      <span class="olt-pill" title="${escAttr(motivo)}">${escHtml(rotulo)}</span>
      <span class="olt-nom" title="${escAttr((o.modelo||'')+' '+(o.ubicacion||''))}">${escHtml(o.nombre)}</span>
      ${o.ip_remota
        ? `<a class="olt-ip" href="https://${encodeURIComponent(o.ip_remota)}/action/login.html" target="_blank" rel="noopener" title="Abrir gestión web de la OLT">${escHtml(o.ip_remota)}</a>`
        : `<span class="olt-ip">${o.ip_red||'—'}</span>`}
    </div>`;

  // métricas
  let met = '';
  if(online){
    const t = est.temperatura, v = est.voltaje;
    met = `<div class="olt-metricas">
      <div class="olt-metrica"><span class="v">${_fmtUptime(est.uptime_seg)}</span><span class="l">uptime</span></div>
      <div class="olt-metrica" title="${est.temp_fuente==='sfp'?'Temperatura del SFP más caliente (la del chasis no está disponible por SNMP)':'Temperatura del chasis'}"><span class="v" style="color:${_colorTemp(t, est.temp_fuente)}">${t!=null?t.toFixed(1)+'°':'—'}</span><span class="l">temp ${est.temp_fuente==='sfp'?'(sfp)':''}</span></div>
      <div class="olt-metrica"><span class="v">${v!=null?v.toFixed(2):'—'}</span><span class="l">volt</span></div>
      <div class="olt-metrica"><span class="v">${o.total_clientes||0}</span><span class="l">clientes</span></div>
    </div>`;
  } else if(sinSnmp){
    met = `<div class="olt-vacia">
        <div class="olt-vacia-txt">SNMP no configurado</div>
        <button class="btn btn-prim btn-xs" onclick="configOltSnmp(${o.id},'${n}','${escJs((est&&est.community)||'public')}','${escJs((est&&est.version_snmp)||'2c')}')">⚙ Configurar</button>
      </div>`;
  } else {
    met = `<div class="olt-vacia">
        <div class="olt-vacia-ico">▚▚▚</div>
        <div class="olt-vacia-txt">La OLT no responde por SNMP</div>
        <div class="olt-vacia-sub">${est.last_check?'último contacto '+est.last_check.slice(5,16):''}</div>
      </div>`;
  }

  // puertos PON
  let pon = '';
  // Lista de puertos a dibujar. Antes dependía SÓLO de puertos_json (que llena
  // el SNMP): si eso venía vacío, no se mostraba NINGÚN PON aunque hubiera
  // clientes contados. Ahora hay dos respaldos: los PON que reportaron ONU por
  // SNMP, y la cantidad de puertos configurada en la ficha de la OLT.
  let listaPuertos = (o.puertos || []).filter(p => p.es_pon !== false);
  if(!listaPuertos.length && est && est.pon_data && Object.keys(est.pon_data).length){
    listaPuertos = Object.keys(est.pon_data)
      .map(k => ({puerto: k}))
      .sort((a,b) => Number(a.puerto) - Number(b.puerto));
  }
  if(!listaPuertos.length && o.puertos_pon){
    listaPuertos = Array.from({length: Number(o.puertos_pon)}, (_, i) => ({puerto: String(i+1)}));
  }
  if(listaPuertos.length){
    pon = `<div class="pon-grid">` + listaPuertos.map(p=>{
      // El número de PON es la clave contra pon_data. Si el dato guardado no lo
      // trae (poller viejo), se deriva del nombre: 'GPON0/3' → 3.
      let np = p.puerto;
      if(np==null && p.nombre){ const m = String(p.nombre).match(/(\d+)/g); if(m) np = parseInt(m[m.length-1]); }
      const pd = (est && est.pon_data && np!=null) ? est.pon_data[String(np)] : null;
      const total = pd ? pd.total : (p.total||0);
      const onl = pd ? pd.online : null, off = pd ? pd.offline : null;
      let cls = 'p-vacio';
      if(total>0) cls = (off===null) ? 'p-normal' : (off===0 ? 'p-optimo' : (off>=total ? 'p-critico' : 'p-alerta'));
      const click = total>0 ? `onclick="verClientesPon(${o.id},'${n}','${np}')"` : '';
      const brk = (off!==null && total>0)
        ? `<div class="pon-brk">${onl?`<span class="ok">●${onl}</span>`:''}${off?`<span class="bad">○${off}</span>`:''}</div>` : '';
      // Temperatura del SFP de ESTE PON puntual (no la del chasis). Es normal
      // que un SFP ronde 50-56°C — no usa los umbrales de _salud_olt.
      const tempPon = p.temp_sfp!=null ? `<div class="pon-temp">${p.temp_sfp.toFixed(0)}°</div>` : '';
      const tituloTemp = p.temp_sfp!=null ? ` — SFP ${p.temp_sfp.toFixed(1)}°C` : '';
      return `<div class="pon-port ${cls}" ${click} title="${escAttr(p.nombre||('PON '+np))}${total>0?' — '+total+' clientes':''}${tituloTemp}">
          <div class="pn">P${np!=null?np:'?'}</div><div class="pv">${total}</div>${brk}${tempPon}
        </div>`;
    }).join('') + `</div>`;
  }

  // Franja con el motivo, visible sólo si hay algo que mirar
  const franjaMotivo = (motivo && estado !== 'optimo')
    ? `<div class="olt-motivo">${escHtml(motivo)}${(est && est.espectro && est.espectro.rancias)
        ? ` · ${est.espectro.rancias} ONU sin lectura reciente (no contadas)` : ''}</div>`
    : '';

  // acciones
  const acc = `<div class="olt-acciones">
      ${!sinSnmp?`<button class="btn btn-gray btn-xs" onclick="pollOltAhora(${o.id})" title="Actualizar por SNMP">🔄</button>`:''}
      ${online?`<button class="btn btn-prim btn-xs" onclick="verOnus(${o.id},'${n}')" title="Ver ONUs y su señal">📡 ONUs</button>`:''}
      ${!sinSnmp?`<button class="btn btn-gray btn-xs" onclick="configOltSnmp(${o.id},'${n}','${escJs(est.community)}','${escJs(est.version_snmp)}')" title="Configurar SNMP">⚙</button>`:''}
      <span class="olt-sello">${est&&est.last_check?est.last_check.slice(5,16):''}</span>
      <button class="btn btn-gray btn-xs" onclick="openModalOlt(${o.id})" title="Editar">✏️</button>
      <button class="btn btn-rj btn-xs" onclick="deleteOlt(${o.id})" title="Eliminar">🗑</button>
    </div>`;

  return `<div class="olt-card olt-noc e-${estado}">${cab}${franjaMotivo}${met}${_oltEspectro(est)}${pon}${acc}</div>`;
}

/* Salud general de la OLT según su espectro y temperatura */
function _oltSalud(est){
  // El backend ya calcula estado + motivo (con datos frescos). Si viene, se usa.
  if(est && est.salud) return est.salud;
  const t = est.temperatura;
  if(t!=null && t>=55) return 'critico';
  const e = est.espectro;
  if(e && e.total){
    const mal = (e.critico||0) + (e.sin_senal||0);
    if(mal/e.total > 0.15) return 'critico';
    if(((e.alerta||0)+mal)/e.total > 0.25) return 'alerta';
  }
  if(t!=null && t>=50) return 'alerta';
  return 'optimo';
}
function _oltRotulo(s){ return s==='optimo'?'en línea':(s==='alerta'?'atención':'revisar'); }
function _colorTemp(t, fuente){
  if(t==null) return 'var(--txt)';
  // Los SFP corren más caliente que el chasis: umbrales distintos.
  const crit = fuente==='sfp'?70:55, alerta = fuente==='sfp'?65:50;
  return t>=crit?'var(--critico)':t>=alerta?'var(--alerta)':'var(--optimo)';
}

// Modal para mostrar clientes de un PON
async function verClientesPon(oltId, oltNombre, pon){
  let m = document.getElementById('modal-pon-tmp');
  if(m) m.remove();
  m = document.createElement('div');
  m.id = 'modal-pon-tmp';
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center;padding:1rem';
  m.onclick = e => { if(e.target === m) m.remove(); };
  m.innerHTML = '<div class="card" style="max-width:720px;width:100%;max-height:85vh;overflow:auto;padding:1.1rem"><div style="text-align:center;color:var(--txt2)">Cargando…</div></div>';
  document.body.appendChild(m);

  const r = await api(`/api/olts/${oltId}/clientes_por_pon?pon=${encodeURIComponent(pon)}`);
  const box = m.firstChild;
  if(!r || r.error){
    box.innerHTML = `<div style="color:var(--critico)">No se pudo cargar: ${r?r.error:'sin respuesta'}</div>
      <button class="btn btn-gray btn-sm" style="margin-top:.7rem" onclick="document.getElementById('modal-pon-tmp').remove()">Cerrar</button>`;
    return;
  }
  const filas = (r.clientes||[]).map(c=>{
    const rc = _rxColor(c.rx_power);
    const rx = c.rx_power!=null ? `<b style="color:${rc.c}">${c.rx_power.toFixed(2)} dBm</b> <span style="font-size:.68rem;color:var(--txt2)">${rc.txt}</span>`
             : (c.origen==='registro' ? '<span style="font-size:.72rem;color:var(--txt2)">no reportado por la OLT</span>'
                                      : '<span style="color:var(--critico)">sin señal</span>');
    const est = (c.estado||'—');
    const estCol = est==='activo'?'var(--optimo)':est==='suspendido'?'var(--alerta)':'var(--critico)';
    const onu = c.onu!=null ? `<span class="mono" style="font-size:.7rem;color:var(--txt2)">ONU ${c.onu}</span>` : '';
    const abrir = c.id ? `onclick="document.getElementById('modal-pon-tmp').remove();openModalCliente(${c.id})"` : '';
    const serial = c.serial_coincide==='difiere'
      ? '<span title="El serial de la ONU no coincide con el equipo registrado" style="color:var(--critico);font-size:.7rem">⚠ serial</span>' : '';
    return `<tr style="cursor:${c.id?'pointer':'default'}" ${abrir}>
      <td>${onu}</td>
      <td><b>${c.nombre||'(sin registro en Pucará)'}</b>
          ${c.nro_cliente?`<span class="mono" style="color:var(--txt2);font-size:.72rem"> #${c.nro_cliente}</span>`:''}
          ${serial}
          <div style="font-size:.71rem;color:var(--txt2)">${c.plan||''}${c.direccion?' · '+c.direccion:''}${c.localidad?' '+c.localidad:''}</div></td>
      <td style="text-align:right;white-space:nowrap">${rx}</td>
      <td style="text-align:center"><span style="color:${estCol};font-size:.72rem">${est}</span></td>
      <td style="font-size:.72rem">${c.telefono||''}</td>
    </tr>`;
  }).join('');

  box.innerHTML = `
    <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.7rem">
      <h3 style="margin:0;flex:1;font-size:1rem">🔌 ${r.olt} · PON ${r.pon}</h3>
      <button class="btn btn-gray btn-xs" onclick="document.getElementById('modal-pon-tmp').remove()">✕</button>
    </div>
    <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.7rem">
      <span class="badge" style="background:var(--surf2);color:var(--txt)">${r.total} cliente(s)</span>
      ${r.con_senal?`<span class="badge" style="background:rgba(79,209,165,.16);color:var(--optimo)">${r.con_senal} con señal</span>`:''}
      ${r.sin_senal?`<span class="badge" style="background:rgba(242,96,122,.16);color:var(--critico)">${r.sin_senal} sin señal</span>`:''}
    </div>
    <div class="tbl-wrap" style="max-height:56vh">
      <table><thead><tr><th></th><th>Cliente</th><th style="text-align:right">Señal RX</th><th style="text-align:center">Estado</th><th>Teléfono</th></tr></thead>
      <tbody>${filas || '<tr><td colspan="5" style="color:var(--txt2);padding:.8rem">Sin clientes en este puerto.</td></tr>'}</tbody></table>
    </div>
    <div style="font-size:.7rem;color:var(--txt2);margin-top:.5rem">Tocá un cliente para abrir su ficha.</div>`;
}

async function openModalOlt(id=null){
  ['molt-id','molt-nombre','molt-modelo','molt-ip-remota','molt-ip-red','molt-ubicacion','molt-lat','molt-lng'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('molt-puertos').value=4;
  {const e=document.getElementById('molt-onu-max'); if(e) e.value=128;}
  document.getElementById('molt-title').textContent=id?'Editar OLT':'Nueva OLT';
  if(id){
    const olts=await api('/api/olts');
    const o=olts.find(x=>x.id===id);
    if(o){
      document.getElementById('molt-id').value=o.id;
      document.getElementById('molt-nombre').value=o.nombre;
      document.getElementById('molt-modelo').value=o.modelo||'';
      document.getElementById('molt-ip-remota').value=o.ip_remota||'';
      document.getElementById('molt-ip-red').value=o.ip_red||'';
      document.getElementById('molt-puertos').value=o.puertos_pon||4;
      {const e=document.getElementById('molt-onu-max'); if(e) e.value=o.onu_max_pon||128;}
      document.getElementById('molt-ubicacion').value=o.ubicacion||'';
      document.getElementById('molt-lat').value=o.lat||'';
      document.getElementById('molt-lng').value=o.lng||'';
    }
  }
  document.getElementById('modal-olt').style.display='flex';
}

async function saveOlt(){
  const id=document.getElementById('molt-id').value;
  const data={nombre:document.getElementById('molt-nombre').value,
    modelo:document.getElementById('molt-modelo').value,
    ip_remota:document.getElementById('molt-ip-remota').value,
    ip_red:document.getElementById('molt-ip-red').value,
    puertos_pon:parseInt(document.getElementById('molt-puertos').value)||4,
    onu_max_pon:parseInt((document.getElementById('molt-onu-max')||{}).value)||128,
    ubicacion:document.getElementById('molt-ubicacion').value,
    lat:parseFloat(document.getElementById('molt-lat').value)||null,
    lng:parseFloat(document.getElementById('molt-lng').value)||null};
  if(!data.nombre.trim()){alert('El nombre es obligatorio');return;}
  const r=await api(id?`/api/olts/${id}`:'/api/olts',id?'PUT':'POST',data);
  if(r?.ok){closeModal('modal-olt');loadOlts();loadOltDatalist();}
  else alert('Error al guardar');
}

async function deleteOlt(id){
  if(!confirm('¿Eliminar esta OLT?')) return;
  await api(`/api/olts/${id}`,'DELETE');
  loadOlts();
}

// ── INCIDENCIAS ──

async function loadDashMonitoreo(){
  const d=await api('/api/monitoreo/resumen');
  if(!d) return;
  const badge=document.getElementById('mon-resumen-badge');
  if(badge){
    badge.textContent=`${d.online}/${d.total} online`;
    badge.style.background=d.offline>0?'var(--rj)':'var(--vd)';
    badge.style.color='var(--card)';
  }
  const list=document.getElementById('dash-mon-list');
  if(!list) return;
  if(d.offline_list&&d.offline_list.length){
    list.innerHTML=d.offline_list.map(m=>`<div style="background:var(--tint-rojo);border-radius:8px;padding:.5rem .6rem;border-left:3px solid var(--rj)">
      <div style="font-weight:700;font-size:.78rem;color:var(--rj)">🔴 ${m.nombre}</div>
      <div style="font-size:.7rem;font-family:monospace;color:var(--txt2)">${m.ip}</div>
      <div style="font-size:.68rem;color:var(--txt2)">Fallos: ${m.consecutivos_offline}</div>
    </div>`).join('');
  } else {
    list.innerHTML=`<div style="background:var(--tint-verde);border-radius:8px;padding:.5rem .8rem;border-left:3px solid var(--vd2);grid-column:1/-1">
      <span style="color:var(--vd);font-weight:700">✅ Todos los dispositivos monitoreados están en línea (${d.online}/${d.total})</span>
    </div>`;
  }
}

async function loadMonitoreo(){
  const d=await api('/api/monitoreo');
  if(!d) return;
  const resumen=await api('/api/monitoreo/resumen');
  if(resumen){
    document.getElementById('mon-stats').innerHTML=`
      <div class="stat"><div class="stat-val">${resumen.total}</div><div class="stat-lbl">Total</div></div>
      <div class="stat green"><div class="stat-val">${resumen.online}</div><div class="stat-lbl">Online</div></div>
      <div class="stat red"><div class="stat-val">${resumen.offline}</div><div class="stat-lbl">Offline</div></div>
      <div class="stat"><div class="stat-val">${resumen.total-resumen.online-resumen.offline}</div><div class="stat-lbl">Desconocido</div></div>`;
  }
  const tbody=document.getElementById('mon-tbody');
  tbody.innerHTML=d.map(m=>{
    const est = m.ping_estado || 'desconocido';
    const color={online:'var(--vd)',offline:'var(--rj)',warning:'var(--am)',desconocido:'var(--gris)'}[est]||'var(--gris)';
    const icn={online:'🟢',offline:'🔴',warning:'🟡',desconocido:'⚪'}[est]||'⚪';
    return `<tr>
      <td><b>${m.nombre}</b></td>
      <td><span class="badge b-normal">${m.tipo}</span></td>
      <td style="font-family:monospace;font-size:.8rem">${m.ip||'—'}</td>
      <td><span style="color:${color};font-weight:700">${icn} ${est}</span></td>
      <td>${m.ping_ms?m.ping_ms+'ms':'—'}</td>
      <td style="font-size:.75rem">${m.ultimo_ping?.slice(0,16)||'Nunca'}</td>
      <td>
        <button class="btn btn-am btn-xs" onclick="pingManual(${m.id})">📡 Ping</button>
        <button class="btn btn-rj btn-xs" onclick="deleteMonitoreo(${m.id})">🗑</button>
      </td>
    </tr>`;
  }).join('');
}

async function pingManual(id){
  const btn=event.target; btn.textContent='...'; btn.disabled=true;
  const r=await api(`/api/monitoreo/ping/${id}`,'POST');
  btn.textContent='📡 Ping'; btn.disabled=false;
  if(r) loadMonitoreo();
}

// (pingTodos eliminado — el ping masivo se quitó. Queda el ping individual por dispositivo.)

function openModalMonitoreo(){
  ['mmon-nombre','mmon-ip'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('mmon-tipo').value='torre';
  document.getElementById('modal-monitoreo').style.display='flex';
}

async function saveMonitoreo(){
  const r=await api('/api/monitoreo','POST',{
    nombre:document.getElementById('mmon-nombre').value,
    tipo:document.getElementById('mmon-tipo').value,
    ip:document.getElementById('mmon-ip').value
  });
  if(r?.ok){closeModal('modal-monitoreo');loadMonitoreo();}
  else alert('Error al agregar');
}

async function deleteMonitoreo(id){
  if(!confirm('¿Quitar este dispositivo del monitoreo?')) return;
  await api(`/api/monitoreo/${id}`,'DELETE');
  loadMonitoreo();
}

// ── HISTORIAL DE SEÑAL NAP ──

// ══ Estado SNMP de las OLT (Fase 1) ══════════════════════════════
function _fmtUptime(seg){
  if(!seg && seg !== 0) return '—';
  const d = Math.floor(seg/86400), h = Math.floor((seg%86400)/3600);
  return d > 0 ? `${d}d ${h}h` : `${h}h`;
}

async function loadOltEstado(){
  const grid = document.getElementById('olt-snmp-grid');
  if(!grid) return;
  const olts = await api('/api/olts/estado');
  if(!olts || !olts.length){
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--txt2);padding:1rem">No hay OLT cargadas. Registralas primero en el módulo de OLT.</div>';
    return;
  }
  grid.innerHTML = olts.map(_oltSnmpCard).join('');
}

function _oltSnmpCard(o){
  // OLT sin SNMP configurado → tarjeta apagada con botón de configurar
  if(!o.snmp_activo){
    return `<div style="border:1px solid var(--brd);border-radius:10px;padding:.8rem;background:var(--card);opacity:.85">
      <div style="font-weight:700">${escHtml(o.nombre)}</div>
      <div style="font-size:.75rem;color:var(--txt2);margin:.2rem 0">${escHtml(o.ip)||'sin IP'} · ${escHtml(o.modelo)}</div>
      <div style="font-size:.78rem;color:var(--txt2);margin:.5rem 0">SNMP no configurado</div>
      <button class="btn btn-prim btn-xs" onclick="configOltSnmp(${o.id},'${escJs(o.nombre)}','${escJs(o.community)}','${escJs(o.version_snmp)}')">⚙ Configurar SNMP</button>
    </div>`;
  }
  const online = o.online == 1;
  const borde = online ? '#4FB3AA' : '#E0605F';
  const chip = online
    ? '<span style="background:rgba(79,179,170,.2);color:#4FB3AA;padding:.15rem .5rem;border-radius:20px;font-size:.72rem;font-weight:700">● ONLINE</span>'
    : '<span style="background:rgba(224,96,95,.2);color:#E0605F;padding:.15rem .5rem;border-radius:20px;font-size:.72rem;font-weight:700">● OFFLINE</span>';
  // Puertos GE/GPON con estado
  const puertos = (o.puertos||[]).map(p=>{
    const c = p.up ? '#4FB3AA' : '#E0605F';
    return `<span title="${escAttr(p.nombre)}" style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${c};margin:1px" ></span>`;
  }).join('');
  const temp = o.temperatura != null ? `${o.temperatura}°C` : '—';
  const volt = o.voltaje != null ? `${o.voltaje}V` : '—';
  return `<div style="border:1px solid var(--brd);border-left:4px solid ${borde};border-radius:10px;padding:.8rem;background:var(--card)">
    <div style="display:flex;align-items:center;gap:.4rem">
      <span style="font-weight:700;flex:1">${escHtml(o.nombre)}</span>${chip}
    </div>
    <div style="font-size:.73rem;color:var(--txt2);margin:.2rem 0 .5rem">${escHtml(o.ip)} · ${escHtml(o.modelo)} ${o.firmware?'· '+escHtml(o.firmware):''}</div>
    ${online ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.3rem .6rem;font-size:.8rem">
      <div>⏱ Uptime: <b>${_fmtUptime(o.uptime_seg)}</b></div>
      <div>🌡 Temp: <b>${temp}</b></div>
      <div>⚡ ${volt}</div>
      <div>👥 ${o.total_clientes} clientes</div>
    </div>
    <div style="margin-top:.5rem"><div style="font-size:.68rem;color:var(--txt2);margin-bottom:.2rem">Puertos GE/GPON:</div>${puertos||'—'}</div>
    ` : `<div style="font-size:.78rem;color:#E0605F;margin:.4rem 0">Sin respuesta SNMP</div>`}
    <div style="display:flex;gap:.3rem;margin-top:.6rem;align-items:center">
      <button class="btn btn-gray btn-xs" onclick="pollOltAhora(${o.id})">🔄 Actualizar</button>
      ${online ? `<button class="btn btn-prim btn-xs" onclick="verOnus(${o.id},'${escJs(o.nombre)}')">📡 ONUs</button>` : ''}
      <button class="btn btn-gray btn-xs" onclick="configOltSnmp(${o.id},'${escJs(o.nombre)}','${escJs(o.community)}','${escJs(o.version_snmp)}')">⚙</button>
      <span style="font-size:.68rem;color:var(--txt2);margin-left:auto">${o.last_check ? o.last_check.slice(5,16) : ''}</span>
    </div>
  </div>`;
}

async function pollOltAhora(id){
  const r = await api(`/api/olts/${id}/poll`, 'POST');
  if(r && r.error){ alert('Error: ' + r.error); return; }
  _refrescarOlts();
}

async function configOltSnmp(id, nombre, community, version){
  const comm = prompt(`Community SNMP para "${nombre}":`, community || 'public');
  if(comm === null) return;
  const ver = prompt('Versión SNMP (2c o 1):', version || '2c') || '2c';
  const act = confirm('¿Activar el monitoreo SNMP de esta OLT?\n\nAceptar = activar · Cancelar = desactivar');
  const r = await api(`/api/olts/${id}/snmp`, 'PUT', {community: comm, version_snmp: ver, snmp_activo: act});
  if(r && r.ok && act){
    await api(`/api/olts/${id}/poll`, 'POST');
  }
  _refrescarOlts();
}

// ── Visor de ONUs con señal óptica (Fase 2) ──
function _rxColor(rx){
  if(rx === null || rx === undefined) return {c:'#E0605F', txt:'Sin señal'};
  if(rx >= -23) return {c:'#4FB3AA', txt:'Buena'};
  if(rx >= -26) return {c:'#E0A838', txt:'Aceptable'};
  if(rx >= -29) return {c:'#E08063', txt:'Baja'};
  return {c:'#E0605F', txt:'Crítica'};
}

async function verOnus(oltId, oltNombre){
  let modal = document.getElementById('onu-modal');
  if(!modal){
    modal = document.createElement('div');
    modal.id = 'onu-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center;padding:1rem';
    modal.onclick = (e)=>{ if(e.target===modal) modal.remove(); };
    document.body.appendChild(modal);
  }
  modal.innerHTML = '<div style="background:var(--card);border:1px solid var(--brd);border-radius:12px;padding:1.2rem;max-width:820px;width:100%;max-height:85vh;overflow:auto"><div style="text-align:center;color:var(--txt2)">Cargando ONUs…</div></div>';
  const onus = await api(`/api/olts/${oltId}/onus`);
  const box = modal.firstChild;
  if(!onus || !onus.length){
    box.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem">
      <h3 style="margin:0">📡 ONUs — ${escHtml(oltNombre)}</h3>
      <button class="btn btn-gray btn-xs" onclick="document.getElementById('onu-modal').remove()">✕</button></div>
      <p style="color:var(--txt2)">No hay señal registrada todavía. Tocá "Sondear ahora" para leer la óptica.</p>
      <button class="btn btn-prim btn-sm" onclick="sondearOnus(${oltId},'${escJs(oltNombre)}')">🔍 Sondear ahora</button>`;
    return;
  }
  const bajas = onus.filter(o=>o.rx_power===null || o.rx_power < -27).length;
  const offline = onus.filter(o=>!o.online).length;
  const filas = onus.map(o=>{
    const rc = _rxColor(o.rx_power);
    const rx = o.rx_power!=null ? o.rx_power.toFixed(2)+' dBm' : 'sin señal';
    const cli = escHtml(o.cliente_nombre) || (o.nro_cliente ? '#'+escHtml(o.nro_cliente) : '—');
    let serialCell = '—';
    if(o.serial_onu){
      const badge = {ok:'<span title="coincide con el equipo registrado" style="color:#4FB3AA">✓</span>',
                     difiere:'<span title="NO coincide con el equipo del cliente" style="color:#E0605F">⚠ difiere</span>',
                     sin_registro:'<span title="el cliente no tiene serial cargado" style="color:#E0A838">sin registro</span>'}[o.serial_coincide] || '';
      serialCell = `<span style="font-family:monospace;font-size:.72rem">${escHtml(o.serial_onu)}</span> ${badge}`;
    }
    return `<tr>
      <td style="font-family:monospace">PON${o.pon}/${o.onu}</td>
      <td>${cli}</td>
      <td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${rc.c};margin-right:.4rem"></span><b style="color:${rc.c}">${rx}</b> <span style="font-size:.7rem;color:var(--txt2)">${rc.txt}</span></td>
      <td>${o.tx_power!=null?o.tx_power.toFixed(2):'—'}</td>
      <td>${serialCell}</td>
    </tr>`;
  }).join('');
  box.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.6rem">
      <h3 style="margin:0">📡 ONUs — ${escHtml(oltNombre)}</h3>
      <button class="btn btn-gray btn-xs" onclick="document.getElementById('onu-modal').remove()">✕</button></div>
    <div style="display:flex;gap:.5rem;margin-bottom:.7rem;flex-wrap:wrap">
      <span style="background:rgba(79,179,170,.15);color:#4FB3AA;padding:.3rem .7rem;border-radius:8px;font-size:.8rem">${onus.length} ONUs</span>
      ${bajas?`<span style="background:rgba(224,128,99,.15);color:#E08063;padding:.3rem .7rem;border-radius:8px;font-size:.8rem">⚠ ${bajas} con señal baja/crítica</span>`:''}
      ${offline?`<span style="background:rgba(224,96,95,.15);color:#E0605F;padding:.3rem .7rem;border-radius:8px;font-size:.8rem">${offline} sin señal</span>`:''}
      <button class="btn btn-gray btn-xs" style="margin-left:auto" onclick="sondearOnus(${oltId},'${escJs(oltNombre)}')">🔄 Re-sondear</button>
    </div>
    <div class="tbl-wrap"><table><thead><tr><th>PON/ONU</th><th>Cliente</th><th>RX power</th><th>TX</th><th>Serial ONU</th></tr></thead>
    <tbody>${filas}</tbody></table></div>
    <div style="font-size:.72rem;color:var(--txt2);margin-top:.6rem">Referencia: <b style="color:#4FB3AA">≥-23</b> buena · <b style="color:#E0A838">-23 a -26</b> aceptable · <b style="color:#E08063">-26 a -29</b> baja · <b style="color:#E0605F">&lt;-29</b> crítica</div>`;
}

async function sondearOnus(oltId, oltNombre){
  const modal = document.getElementById('onu-modal');
  if(modal) modal.firstChild.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--txt2)">🔍 Sondeando la óptica de las ONU…<br><span style="font-size:.75rem">Puede tardar unos segundos (lee todas las ONU de la OLT).</span></div>';
  const r = await api(`/api/olts/${oltId}/sondear-onus`, 'POST');
  if(r && r.error){ alert('Error: '+r.error); }
  verOnus(oltId, oltNombre);
  if(typeof loadOnuAlertas==="function"){var pa=document.getElementById("page-onu-alertas");if(pa&&pa.classList.contains("active"))loadOnuAlertas();}
  if(typeof _cargarBannerOnuCriticas==="function") _cargarBannerOnuCriticas();
}

// ── Bloque SNMP embebido en la tarjeta de OLT (FTTH/Red) ──
function _oltSnmpInline(est, id, nombre){
  const n = escJs(nombre);
  if(!est || !est.snmp_activo){
    const comm = est ? est.community : 'public';
    const ver = est ? est.version_snmp : '2c';
    return `<div style="padding:.45rem .7rem;margin:.4rem 0;background:var(--surf2);border-radius:6px;font-size:.78rem;color:var(--txt2);display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
      <span>📡 SNMP no configurado</span>
      <button class="btn btn-prim btn-xs" onclick="configOltSnmp(${id},'${n}','${comm}','${ver}')">⚙ Configurar SNMP</button>
    </div>`;
  }
  const online = est.online == 1;
  const col = online ? '#4FB3AA' : '#E0605F';
  const chip = online
    ? '<span style="color:#4FB3AA;font-weight:700;white-space:nowrap">● ONLINE</span>'
    : '<span style="color:#E0605F;font-weight:700;white-space:nowrap">● OFFLINE</span>';
  const ports = (est.puertos||[]).map(p=>`<span title="${escAttr(p.nombre)}" style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.up?'#4FB3AA':'#E0605F'};margin:1px"></span>`).join('');
  const info = online
    ? `<span style="font-size:.77rem;white-space:nowrap">⏱ ${_fmtUptime(est.uptime_seg)}</span>
       ${est.temperatura!=null?`<span style="font-size:.77rem;white-space:nowrap">🌡 ${est.temperatura}°C</span>`:''}
       ${est.voltaje!=null?`<span style="font-size:.77rem;white-space:nowrap">⚡ ${est.voltaje}V</span>`:''}
       ${est.firmware?`<span style="font-size:.72rem;color:var(--txt2);white-space:nowrap">${est.firmware}</span>`:''}
       ${ports?`<span style="display:inline-flex;align-items:center" title="Puertos GE/GPON">${ports}</span>`:''}`
    : '<span style="font-size:.77rem;color:#E0605F">sin respuesta SNMP</span>';
  return `<div style="padding:.45rem .7rem;margin:.4rem 0;background:var(--surf2);border-radius:6px;border-left:3px solid ${col};display:flex;align-items:center;gap:.7rem;flex-wrap:wrap">
    ${chip} ${info}
    <div style="margin-left:auto;display:flex;gap:.3rem">
      <button class="btn btn-gray btn-xs" onclick="pollOltAhora(${id})" title="Actualizar por SNMP">🔄</button>
      ${online?`<button class="btn btn-prim btn-xs" onclick="verOnus(${id},'${n}')">📡 ONUs</button>`:''}
      <button class="btn btn-gray btn-xs" onclick="configOltSnmp(${id},'${n}','${escJs(est.community)}','${escJs(est.version_snmp)}')" title="Config SNMP">⚙</button>
      ${est.last_check?`<span style="font-size:.66rem;color:var(--txt2);align-self:center">${est.last_check.slice(5,16)}</span>`:''}
    </div>
  </div>`;
}


// Refresca la vista de OLTs esté donde esté el SNMP (FTTH/OLTs o Monitoreo)
function _refrescarOlts(){
  if(document.getElementById('olt-list')) loadOlts();
  if(document.getElementById('olt-snmp-grid')) loadOltEstado();
  // Si el panel de alertas de ONU está a la vista, recargarlo:
  // al pollear una OLT cambian las señales y por lo tanto las alertas.
  var pa = document.getElementById('page-onu-alertas');
  if(pa && pa.classList.contains('active') && typeof loadOnuAlertas === 'function') loadOnuAlertas();
  // y el banner de críticas del dashboard
  if(typeof _cargarBannerOnuCriticas === 'function') _cargarBannerOnuCriticas();
}

// ── Espectro óptico: cómo se reparten las señales de las ONU de una OLT ──
function _oltEspectro(est){
  if(!est || !est.snmp_activo || !est.espectro) return '';
  const e = est.espectro;
  const conSenal = (e.optimo||0)+(e.normal||0)+(e.alerta||0)+(e.critico||0);
  if(!e.total){ return ''; }
  if(!conSenal){
    return `<div class="espectro-wrap">
      <div class="espectro-tit"><span>Espectro óptico</span><span style="color:var(--txt2)">sin señal en ${e.total} ONU</span></div>
      <div class="espectro"><i style="width:100%;background:var(--muerto);opacity:.35"></i></div>
      <div class="espectro-escala"><span>−15</span><span>−23</span><span>−26</span><span>−29</span><span>−32</span></div>
    </div>`;
  }
  const pct = n => (n/conSenal*100);
  const seg = (n,color) => n>0 ? `<i style="width:${pct(n).toFixed(2)}%;background:${color}"${n/conSenal>0.05?` data-n="${n}"`:''} title="${n} ONU"></i>` : '';
  const media = e.media!=null ? e.media.toFixed(1)+' dBm' : '—';
  const colorMedia = e.media==null?'var(--txt2)':e.media>=-23?'var(--optimo)':e.media>=-26?'var(--normal)':e.media>=-29?'var(--alerta)':'var(--critico)';
  const degradadas = (e.alerta||0)+(e.critico||0);
  return `<div class="espectro-wrap">
    <div class="espectro-tit">
      <span>Espectro óptico${degradadas?` · <b style="color:var(--alerta)">${degradadas} degradada${degradadas>1?'s':''}</b>`:''}${e.sin_senal?` · <b style="color:var(--critico)">${e.sin_senal} sin señal</b>`:''}</span>
      <span style="color:${colorMedia}">media ${media}</span>
    </div>
    <div class="espectro">
      ${seg(e.optimo,'var(--optimo)')}${seg(e.normal,'var(--normal)')}${seg(e.alerta,'var(--alerta)')}${seg(e.critico,'var(--critico)')}
    </div>
    <div class="espectro-escala"><span>−15</span><span>−23</span><span>−26</span><span>−29</span><span>−32</span></div>
  </div>`;
}

// ══════════ Enlaces SNMP punto a punto (Fase 7) ══════════
let _enlacesData = [];
let _equiposParaEnlace = null;

async function cargarEnlaces(){
  const cont = document.getElementById('enlaces-lista');
  cont.innerHTML = '<div style="color:var(--txt2)">Cargando…</div>';
  _enlacesData = await api('/api/enlaces') || [];
  if(!_enlacesData.length){
    cont.innerHTML = '<div style="color:var(--txt2);padding:1rem">No hay enlaces cargados. Creá uno con “Nuevo enlace”.</div>';
    return;
  }
  cont.innerHTML = _enlacesData.map(_renderEnlaceCard).join('');
}

function _extremoResumen(ex, letra){
  if(!ex) return `<div style="flex:1"><b>Extremo ${letra}</b><br><span style="color:var(--txt2)">equipo no encontrado</span></div>`;
  return `<div style="flex:1;min-width:180px">
    <div style="font-weight:600">Extremo ${letra}: ${escHtml(ex.modelo||ex.mac||'equipo')}</div>
    <div style="font-size:.78rem;color:var(--txt2)">${escHtml(ex.torre_nombre)||'—'}${ex.localidad?' · '+escHtml(ex.localidad):''}</div>
    <div style="font-size:.78rem;font-family:monospace">${escHtml(ex.ip||ex.snmp_ip)||'sin IP'}</div>
  </div>`;
}

function _renderEnlaceCard(e){
  const badge = e.estado==='activo'
    ? '<span style="background:#1c5b3a;color:#fff;padding:.1rem .5rem;border-radius:10px;font-size:.72rem">activo</span>'
    : '<span style="background:#555;color:#fff;padding:.1rem .5rem;border-radius:10px;font-size:.72rem">inactivo</span>';
  return `<div style="border:1px solid var(--brd);border-radius:10px;padding:.7rem;margin-bottom:.7rem">
    <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem">
      <span style="font-weight:700;flex:1">${escHtml(e.nombre)||'Enlace'} ${badge}</span>
      <button class="btn btn-gray btn-xs" onclick="sondearEnlace(${e.id})">📡 Sondear extremos</button>
      <button class="btn btn-gray btn-xs" onclick="editarEnlace(${e.id})">✏️</button>
    </div>
    <div style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap">
      ${_extremoResumen(e.extremo_a,'A')}
      <div style="font-size:1.3rem;color:var(--txt2)">↔</div>
      ${_extremoResumen(e.extremo_b,'B')}
    </div>
    <div id="enlace-estado-${e.id}" style="margin-top:.5rem"></div>
  </div>`;
}

function _lanChip(lan, alerta){
  if(alerta){
    const i = (lan||[]).find(x=>x.estado_lan==='critico');
    return `<span style="background:#7a1f1f;color:#fff;padding:.1rem .5rem;border-radius:6px;font-weight:600">⚠️ LAN ${alerta.velocidad_mbps} Mbps (${alerta.interfaz})</span>`;
  }
  const up = (lan||[]).filter(x=>x.oper==='up');
  if(!up.length) return '<span style="color:var(--txt2)">LAN sin datos</span>';
  return up.map(i=>`<span style="color:#4FD1A5">🟢 ${escHtml(i.nombre)} ${i.speed_mbps} Mbps</span>`).join(' · ');
}

function _extremoEstado(ex, letra){
  if(!ex || ex.error) return `<div style="flex:1"><b>${letra}</b>: <span style="color:var(--critico)">${ex&&ex.error?ex.error:'sin datos'}</span></div>`;
  const dev = ex.device||{};
  const snmp = ex.snmp_ok ? '🟢 SNMP' : '⚫ sin SNMP';
  return `<div style="flex:1;min-width:200px;font-size:.8rem">
    <div style="font-weight:600">${letra} — ${snmp}</div>
    ${dev.modo?`<div>Modo: ${dev.modo}${dev.essid?' · '+dev.essid:''}</div>`:''}
    ${dev.estaciones_n!=null?`<div>Clientes: ${dev.estaciones_n}</div>`:''}
    <div style="margin-top:.2rem">${_lanChip(ex.lan, ex.lan_alerta)}</div>
  </div>`;
}

async function sondearEnlace(id){
  const box = document.getElementById('enlace-estado-'+id);
  box.innerHTML = '<div style="color:var(--txt2);font-size:.8rem">📡 Sondeando ambos extremos… (unos segundos)</div>';
  const r = await api(`/api/enlaces/${id}/estado`);
  if(!r || r.error){ box.innerHTML = `<div style="color:var(--critico);font-size:.8rem">✗ ${escHtml(r?r.error:'sin respuesta')}</div>`; return; }
  let html = '';
  if(r.alerta_lan_en && r.alerta_lan_en.length){
    html += `<div style="background:#7a1f1f;color:#fff;border-radius:6px;padding:.5rem;margin-bottom:.5rem;font-weight:600">
      ⚠️ Problema de LAN a 10 Mbps en extremo ${r.alerta_lan_en.join(' y ')} — revisar cableado, conector, PoE y puerto.</div>`;
  }
  html += `<div style="display:flex;gap:1rem;flex-wrap:wrap;background:var(--surf2);border-radius:8px;padding:.6rem">
    ${_extremoEstado(r.extremo_a,'A')}
    ${_extremoEstado(r.extremo_b,'B')}
  </div>`;
  box.innerHTML = html;
}

async function _cargarEquiposSelect(){
  // Trae todos los equipos con torre para elegir extremos
  if(!_equiposParaEnlace){
    _equiposParaEnlace = await api('/api/inventario/equipos_con_torre') || [];
  }
  const opts = _equiposParaEnlace.map(e=>
    `<option value="${e.id}">${e.modelo||e.tipo||'equipo'} — ${e.torre_nombre||'sin torre'} (${e.ip||'sin IP'})</option>`).join('');
  document.getElementById('menl-eq-a').innerHTML = opts;
  document.getElementById('menl-eq-b').innerHTML = opts;
}

async function abrirModalEnlace(){
  document.getElementById('menl-title').textContent = 'Nuevo enlace';
  document.getElementById('menl-id').value = '';
  document.getElementById('menl-nombre').value = '';
  document.getElementById('menl-obs').value = '';
  document.getElementById('menl-estado').value = 'activo';
  document.getElementById('menl-del').style.display = 'none';
  await _cargarEquiposSelect();
  document.getElementById('modal-enlace').style.display = 'flex';
}

async function editarEnlace(id){
  const e = _enlacesData.find(x=>x.id===id);
  if(!e) return;
  await _cargarEquiposSelect();
  document.getElementById('menl-title').textContent = 'Editar enlace';
  document.getElementById('menl-id').value = e.id;
  document.getElementById('menl-nombre').value = e.nombre||'';
  document.getElementById('menl-obs').value = e.observaciones||'';
  document.getElementById('menl-estado').value = e.estado||'activo';
  document.getElementById('menl-eq-a').value = e.equipo_a_id;
  document.getElementById('menl-eq-b').value = e.equipo_b_id;
  document.getElementById('menl-del').style.display = '';
  document.getElementById('modal-enlace').style.display = 'flex';
}

async function guardarEnlace(){
  const id = document.getElementById('menl-id').value;
  const payload = {
    nombre: document.getElementById('menl-nombre').value.trim(),
    equipo_a_id: parseInt(document.getElementById('menl-eq-a').value),
    equipo_b_id: parseInt(document.getElementById('menl-eq-b').value),
    estado: document.getElementById('menl-estado').value,
    observaciones: document.getElementById('menl-obs').value.trim(),
  };
  const r = id ? await api(`/api/enlaces/${id}`,'PUT',payload) : await api('/api/enlaces','POST',payload);
  if(r && (r.ok||r.id)){ closeModal('modal-enlace'); cargarEnlaces(); }
  else alert('Error: '+(r&&r.error?r.error:'no se pudo guardar'));
}

async function borrarEnlace(){
  const id = document.getElementById('menl-id').value;
  if(!id || !confirm('¿Eliminar este enlace?')) return;
  const r = await api(`/api/enlaces/${id}`,'DELETE');
  if(r && r.ok){ closeModal('modal-enlace'); cargarEnlaces(); }
}

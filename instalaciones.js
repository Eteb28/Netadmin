/* ========================================================
   instalaciones.js — ERLAN NetAdmin v8
   Workflow de alta de cliente en 3 etapas:
   venta → activacion_pendiente → instalacion_pendiente → activo
   ======================================================== */

// ── Estado helper ──
function _diasEsperaTxt(dias){
  if(dias === null || dias === undefined) return '—';
  if(dias === 0) return '<span style="color:var(--vd)">hoy</span>';
  if(dias <= 3) return `<span style="color:var(--vd)">${dias}d</span>`;
  if(dias <= 7) return `<span style="color:var(--am)">${dias}d</span>`;
  return `<span style="color:var(--rj);font-weight:700">${dias}d ⚠</span>`;
}

function _badgeTipo(tipo){
  return tipo === 'fibra'
    ? '<span class="badge b-fibra">📡 Fibra</span>'
    : '<span class="badge b-inalambrico">📶 Inalámbrico</span>';
}

// ════════════════════════════════════════════════════════
// PÁGINA: ACTIVACIÓN PENDIENTE
// ════════════════════════════════════════════════════════
async function loadActivacionPendiente(){
  const data = await api('/api/instalaciones?estado=venta');
  if(!data) return;
  document.getElementById('act-pte-cnt').textContent = data.length;
  const tbody = document.getElementById('act-pte-tbody');
  if(!data.length){
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#888;padding:1.5rem">Sin clientes esperando activación</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(c => {
    const nro = c.nro_cliente
      ? `<span style="font-family:monospace;font-weight:700">#${c.nro_cliente}</span>`
      : '<span style="color:#aaa">—</span>';
    return `<tr>
      <td>${nro}</td>
      <td><b>${c.nombre||'—'}</b></td>
      <td>${_badgeTipo(c.tipo_servicio)}</td>
      <td>${c.plan||'—'}</td>
      <td>${c.localidad||'—'}</td>
      <td>${_diasEsperaTxt(c.dias_espera)}</td>
      <td style="font-size:.78rem;color:var(--txt2)">${c.usuario_venta||'—'}</td>
      <td>
        <button class="btn btn-prim btn-xs" onclick="abrirActivacion(${c.cliente_id})">⚙️ Activar</button>
        <button class="btn btn-gray btn-xs" onclick="openModalCliente(${c.cliente_id})" title="Ver/editar datos">✏️</button>
      </td>
    </tr>`;
  }).join('');
}

// ════════════════════════════════════════════════════════
// PÁGINA: INSTALACIÓN PENDIENTE
// ════════════════════════════════════════════════════════
async function loadInstalacionPendiente(){
  // Mostrar tanto activacion_pendiente como instalacion_pendiente
  // (técnico ve los listos para ir a campo)
  const dataAct = await api('/api/instalaciones?estado=activacion_pendiente') || [];
  const dataInst = await api('/api/instalaciones?estado=instalacion_pendiente') || [];
  const all = [...dataInst, ...dataAct];  // primero los más urgentes
  document.getElementById('inst-pte-cnt').textContent = all.length;
  
  const tbody = document.getElementById('inst-pte-tbody');
  if(!all.length){
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888;padding:1.5rem">Sin instalaciones pendientes</td></tr>';
    return;
  }
  // Roles que pueden marcar instalado
  const puedeInstalar = currentUser.rol === 'tecnico' || currentUser.rol === 'admin' || currentUser.rol === 'root';
  
  tbody.innerHTML = all.map(c => {
    const nro = c.nro_cliente
      ? `<span style="font-family:monospace;font-weight:700">#${c.nro_cliente}</span>`
      : '<span style="color:#aaa">—</span>';
    const eqIp = (c.equipo_serie || c.ip_asignada)
      ? `<small>S/N: ${c.equipo_serie||'—'}<br>IP: ${c.ip_asignada||'—'}</small>`
      : '<span style="color:#dc3545;font-size:.78rem">⚠ Sin datos técnicos</span>';
    const estadoTag = c.estado === 'instalacion_pendiente'
      ? '<span class="badge b-pendiente">🛠️ Lista p/ instalar</span>'
      : '<span class="badge b-fibra">⚙️ En activación</span>';
    return `<tr>
      <td>${nro}<br>${estadoTag}</td>
      <td><b>${c.nombre||'—'}</b></td>
      <td>${_badgeTipo(c.tipo_servicio)}</td>
      <td style="font-size:.82rem">${c.direccion||'—'}<br><small>${c.localidad||''}</small></td>
      <td>${eqIp}</td>
      <td>${_diasEsperaTxt(c.dias_espera)}</td>
      <td>
        ${c.estado === 'instalacion_pendiente' && puedeInstalar
          ? `<button class="btn btn-vd btn-xs" onclick="abrirMarcarInstalado(${c.cliente_id})">✅ Marcar instalado</button>`
          : c.estado === 'activacion_pendiente'
            ? `<button class="btn btn-prim btn-xs" onclick="abrirActivacion(${c.cliente_id})">⚙️ Editar activación</button>
               <button class="btn btn-am btn-xs" onclick="pasarAInstalacion(${c.cliente_id})">➡️ Pasar a instalación</button>`
            : ''}
        <button class="btn btn-gray btn-xs" onclick="openModalCliente(${c.cliente_id})">✏️</button>
      </td>
    </tr>`;
  }).join('');
}

// ════════════════════════════════════════════════════════
// MODAL: ACTIVACIÓN (asignar datos técnicos)
// ════════════════════════════════════════════════════════
async function abrirActivacion(cid){
  const r = await api(`/api/instalaciones/${cid}`);
  if(!r) return;
  const c = r.cliente, inst = r.instalacion || {};
  
  document.getElementById('mact-cli-id').value = cid;
  document.getElementById('mact-cli-info').innerHTML = `
    <div><b>${c.nombre}</b> · ${c.dni||''} · ${_badgeTipo(c.tipo_servicio)}</div>
    <div style="font-size:.78rem;color:var(--txt2);margin-top:.2rem">
      📍 ${c.direccion||'—'}, ${c.localidad||''}<br>
      💰 ${c.plan||'—'} · ${c.precio||0}
    </div>
  `;
  
  // Toggle FTTH/Inalám fields
  const esFibra = c.tipo_servicio === 'fibra';
  document.getElementById('mact-ftth-fields').style.display = esFibra ? 'block' : 'none';
  document.getElementById('mact-inal-fields').style.display = esFibra ? 'none' : 'block';
  
  // Pre-cargar datos existentes
  document.getElementById('mact-ip').value = c.ip_asignada || inst.ip_asignada || '';
  document.getElementById('mact-pppoe-user').value = inst.pppoe_usuario || c.nro_cliente || '';
  document.getElementById('mact-pppoe-pass').value = inst.pppoe_clave || '';
  document.getElementById('mact-eq-modelo').value = c.equipo_modelo || '';
  document.getElementById('mact-eq-marca').value = c.equipo_marca || '';
  document.getElementById('mact-eq-serie').value = c.equipo_serie || '';
  document.getElementById('mact-eq-mac').value = c.mac_address || '';
  
  if(esFibra){
    document.getElementById('mact-nap').value = c.nap || '';
    document.getElementById('mact-olt').value = c.olt_nombre || '';
    document.getElementById('mact-pon').value = c.olt_puerto || '';
  } else {
    // Cargar torres en el select
    const torres = await api('/api/torres');
    const sel = document.getElementById('mact-torre');
    sel.innerHTML = '<option value="">— Sin torre —</option>' +
      (torres||[]).map(t => `<option value="${t.id}">${t.nombre}${t.localidad?' · '+t.localidad:''}</option>`).join('');
    if(c.torre_id) sel.value = c.torre_id;
    document.getElementById('mact-ap').value = c.ap_nombre || '';
  }
  
  document.getElementById('modal-activacion').style.display = 'flex';
}

function generarPasswordAct(){
  const hex = Math.floor(Math.random() * 0xFFFFF).toString(16).padStart(5,'0');
  document.getElementById('mact-pppoe-pass').value = hex;
}

async function guardarActivacion(pasarAInst){
  const cid = document.getElementById('mact-cli-id').value;
  const ip = document.getElementById('mact-ip').value.trim();
  if(!ip){ alert('La IP asignada es obligatoria'); return; }
  
  const data = {
    ip_asignada: ip,
    pppoe_usuario: document.getElementById('mact-pppoe-user').value.trim(),
    pppoe_clave: document.getElementById('mact-pppoe-pass').value.trim(),
    equipo_modelo: document.getElementById('mact-eq-modelo').value.trim(),
    equipo_marca: document.getElementById('mact-eq-marca').value.trim(),
    equipo_serie: document.getElementById('mact-eq-serie').value.trim(),
    mac_address: document.getElementById('mact-eq-mac').value.trim(),
  };
  // FTTH o Inalámbrico
  const ftthVisible = document.getElementById('mact-ftth-fields').style.display !== 'none';
  if(ftthVisible){
    data.nap = document.getElementById('mact-nap').value.trim();
    data.olt_nombre = document.getElementById('mact-olt').value.trim();
    data.olt_puerto = document.getElementById('mact-pon').value.trim();
  } else {
    data.torre_id = document.getElementById('mact-torre').value || null;
    data.ap_nombre = document.getElementById('mact-ap').value.trim();
  }
  
  const r = await api(`/api/clientes/${cid}/pasar_a_activacion`, 'POST', data);
  if(!r?.ok){ alert('Error: ' + (r?.error||'no se pudo guardar')); return; }
  
  // Si pidió pasar a instalación, hacerlo ahora
  if(pasarAInst){
    const r2 = await api(`/api/clientes/${cid}/pasar_a_instalacion`, 'POST', {});
    if(!r2?.ok){
      alert('Datos guardados pero hubo un error al pasar a instalación: ' + (r2?.error||''));
    }
  }
  
  closeModal('modal-activacion');
  // Refrescar página actual
  if(document.getElementById('page-activacion-pendiente').classList.contains('active')){
    loadActivacionPendiente();
  } else if(document.getElementById('page-instalacion-pendiente').classList.contains('active')){
    loadInstalacionPendiente();
  }
}

async function pasarAInstalacion(cid){
  if(!confirm('¿Pasar este cliente a "Instalación pendiente"?\n\nVa a quedar en la lista del técnico para ir a instalar.')) return;
  const r = await api(`/api/clientes/${cid}/pasar_a_instalacion`, 'POST', {});
  if(r?.ok){
    loadInstalacionPendiente();
  } else {
    alert('Error: ' + (r?.error||''));
  }
}

// ════════════════════════════════════════════════════════
// MODAL: MARCAR COMO INSTALADO
// ════════════════════════════════════════════════════════
async function abrirMarcarInstalado(cid){
  const r = await api(`/api/instalaciones/${cid}`);
  if(!r) return;
  const c = r.cliente, inst = r.instalacion || {};
  
  document.getElementById('minst-cli-id').value = cid;
  document.getElementById('minst-cli-info').innerHTML = `
    <div><b>${c.nombre}</b> · ${_badgeTipo(c.tipo_servicio)}</div>
    <div style="font-size:.78rem;color:var(--txt2);margin-top:.2rem">
      📍 ${c.direccion||'—'}, ${c.localidad||''}<br>
      📡 ${c.equipo_modelo||'—'} · S/N: ${c.equipo_serie||'—'} · IP: ${c.ip_asignada||'—'}
    </div>
  `;
  
  // Cargar técnicos
  const agentes = await api('/api/usuarios/agentes');
  const tecs = (agentes||[]).filter(a => a.rol === 'tecnico' || a.rol === 'admin');
  const sel = document.getElementById('minst-tecnico');
  sel.innerHTML = tecs.map(t => `<option value="${t.id}" data-nombre="${t.nombre}">${t.nombre} (${t.username})</option>`).join('');
  // Pre-seleccionar si el usuario logueado está en la lista
  const myId = currentUser.id;
  if(myId) sel.value = myId;
  
  // Mostrar duración estimada
  if(inst.fecha_venta){
    const ms = Date.now() - new Date(inst.fecha_venta.replace(' ', 'T')).getTime();
    const horas = Math.round(ms / 3600000);
    const dias = Math.round(horas/24*10)/10;
    document.getElementById('minst-duracion-info').innerHTML = 
      `⏱ Tiempo desde la venta: <b>${dias} días</b> (${horas} hs)`;
  }
  
  // Reset campos
  document.getElementById('minst-senal').value = '';
  document.getElementById('minst-obs').value = '';
  
  // Si no es FTTH, ocultar campo señal (no aplica)
  document.getElementById('minst-senal').parentElement.style.display = c.tipo_servicio === 'fibra' ? 'block' : 'none';
  
  document.getElementById('modal-instalado').style.display = 'flex';
}

async function confirmarInstalacion(){
  const cid = document.getElementById('minst-cli-id').value;
  const sel = document.getElementById('minst-tecnico');
  const tec_id = sel.value;
  const tec_nombre = sel.options[sel.selectedIndex]?.dataset.nombre || '';
  
  const data = {
    senal_inicial_dbm: document.getElementById('minst-senal').value || null,
    observaciones: document.getElementById('minst-obs').value || '',
    tecnico_id: tec_id ? parseInt(tec_id) : null,
    tecnico_nombre: tec_nombre,
  };
  
  const r = await api(`/api/clientes/${cid}/marcar_instalado`, 'POST', data);
  if(!r?.ok){ alert('Error: ' + (r?.error||'')); return; }
  
  alert(`✅ Instalación confirmada.\nDuración total: ${r.duracion_horas} horas.`);
  closeModal('modal-instalado');
  loadInstalacionPendiente();
}

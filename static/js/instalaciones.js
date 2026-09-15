/* ========================================================
   instalaciones.js — ERLAN NetAdmin v6
   Conectado a los endpoints reales del ERP:
   - Instalación pendiente  → /api/instalaciones (tipo=instalacion, estado=pendiente)
   - Activación pendiente   → /api/pendientes/pte_activacion (estado del cliente)
   ======================================================== */

function _badgeTipoSvc(medio){
  if(!medio) return '<span class="badge">—</span>';
  const m = medio.toLowerCase();
  if(m.includes('fibra')) return '<span class="badge b-fibra">📡 Fibra</span>';
  return '<span class="badge b-inalambrico">📶 Inalámbrico</span>';
}

function _diasDesde(fechaStr){
  if(!fechaStr) return null;
  try {
    const f = new Date(fechaStr.replace(' ', 'T'));
    return Math.floor((Date.now() - f.getTime()) / 86400000);
  } catch { return null; }
}

function _diasTxt(dias){
  if(dias === null || dias === undefined) return '—';
  if(dias <= 3) return `<span style="color:var(--vd)">${dias}d</span>`;
  if(dias <= 7) return `<span style="color:var(--am)">${dias}d</span>`;
  return `<span style="color:var(--rj);font-weight:700">${dias}d ⚠</span>`;
}

// ════════════════════════════════════════════════════════
// INSTALACIÓN PENDIENTE — soportes tipo instalación del ERP
// ════════════════════════════════════════════════════════
async function loadInstalacionPendiente(){
  const data = await api('/api/instalaciones') || [];
  const cnt = document.getElementById('inst-pte-cnt');
  if(cnt) cnt.textContent = data.length;

  const tbody = document.getElementById('inst-pte-tbody');
  if(!tbody) return;
  if(!data.length){
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888;padding:1.5rem">Sin instalaciones pendientes</td></tr>';
    return;
  }

  tbody.innerHTML = data.map(s => {
    const nro = s.nro_cliente
      ? `<span style="font-family:monospace;font-weight:700">#${s.nro_cliente}</span>`
      : '<span style="color:#aaa">—</span>';
    const dias = _diasDesde(s.fecha_programada || s.fecha_creacion);
    const tec = s.tecnico
      ? `<span style="font-size:.78rem">👷 ${escHtml(s.tecnico)}</span>`
      : '<span style="color:#aaa;font-size:.78rem">sin asignar</span>';
    const equipo = s.descripcion
      ? `<small>${escHtml(s.descripcion.slice(0,40))}</small>`
      : '—';
    const obs = s.observaciones
      ? `<br><small style="color:var(--txt2)" title="${escAttr(s.observaciones)}">${escHtml(s.observaciones.slice(0,50))}${s.observaciones.length>50?'…':''}</small>`
      : '';
    // Datos técnicos según tipo de servicio
    const tipo = (s.cliente_tipo||'').toLowerCase();
    let tecnico_datos = '';
    if(tipo === 'fibra'){
      tecnico_datos = `
        <div style="font-size:.74rem;line-height:1.5">
          ${s.cliente_nap_display ? `🔵 <b>NAP:</b> ${escHtml(s.cliente_nap_display)}` : '<span style="color:#c62828">⚠ sin NAP</span>'}
          ${s.olt_nombre ? `<br>📡 OLT: ${escHtml(s.olt_nombre)}${s.olt_puerto?' / '+escHtml(s.olt_puerto):''}` : ''}
          ${s.pppoe_usuario ? `<br>👤 <b>PPPoE:</b> ${escHtml(s.pppoe_usuario)}` : ''}
          ${s.pppoe_clave ? `<br>🔑 ${escHtml(s.pppoe_clave)}` : ''}
        </div>`;
    } else if(tipo === 'inalambrico'){
      tecnico_datos = `
        <div style="font-size:.74rem;line-height:1.5">
          ${s.ip_asignada ? `🌐 <b>IP:</b> ${escHtml(s.ip_asignada)}` : '<span style="color:#c62828">⚠ sin IP</span>'}
          ${s.pppoe_usuario ? `<br>👤 PPPoE: ${escHtml(s.pppoe_usuario)}` : ''}
          ${s.pppoe_clave ? `<br>🔑 ${escHtml(s.pppoe_clave)}` : ''}
        </div>`;
    } else {
      tecnico_datos = '<small style="color:#aaa">—</small>';
    }
    const planTxt = s.cliente_plan ? `<br><small style="color:#1565c0">📋 ${escHtml(s.cliente_plan)}</small>` : '';
    return `<tr>
      <td>${nro}<br>${tec}</td>
      <td><b>${escHtml(s.cliente_nombre||s.nombre_cliente)||'—'}</b>${planTxt}</td>
      <td>${_badgeTipoSvc(s.medio_transmision||s.cliente_tipo)}</td>
      <td style="font-size:.82rem">${escHtml(s.cliente_dir)||'—'}<br><small>${escHtml(s.cliente_localidad)}</small>${obs}</td>
      <td>${tecnico_datos}</td>
      <td>${_diasTxt(dias)}<br><small style="color:var(--txt2)">prog: ${s.fecha_programada||'—'}</small></td>
      <td>
        <button class="btn btn-gray btn-xs" onclick="openModalCliente(${s.cliente_id})" title="Ver cliente">✏️</button>
      </td>
    </tr>`;
  }).join('');
}

// ════════════════════════════════════════════════════════
// ACTIVACIÓN PENDIENTE — clientes en estado pte_activacion
// ════════════════════════════════════════════════════════
async function loadActivacionPendiente(){
  const data = await api('/api/pendientes/pte_activacion') || [];
  const cnt = document.getElementById('act-pte-cnt');
  if(cnt) cnt.textContent = data.length;

  const tbody = document.getElementById('act-pte-tbody');
  if(!tbody) return;
  if(!data.length){
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#888;padding:1.5rem">Sin clientes esperando activación</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(c => {
    const nro = c.nro_cliente
      ? `<span style="font-family:monospace;font-weight:700">#${c.nro_cliente}</span>`
      : '<span style="color:#aaa">—</span>';
    const dias = _diasDesde(c.creado);
    // Datos de red asignados (IP solo inalámbrico, PPPoE todos)
    const tipo = (c.tipo_servicio||'').toLowerCase();
    const partes = [];
    if(tipo === 'inalambrico'){
      partes.push(c.ip_asignada
        ? `🌐 <b>${escHtml(c.ip_asignada)}</b>`
        : '<span style="color:#c62828">⚠ sin IP</span>');
    } else if(tipo === 'fibra'){
      partes.push(c.nap_display ? `🔵 <b>NAP:</b> ${escHtml(c.nap_display)}` : '<span style="color:#c62828">⚠ sin NAP</span>');
      if(c.cdo) partes.push(`📦 CDO: ${escHtml(c.cdo)}`);
      if(c.red) partes.push(`🌐 Red: ${escHtml(c.red)}`);
      if(c.olt_nombre) partes.push(`📡 OLT: ${escHtml(c.olt_nombre)}${c.olt_puerto?'/'+escHtml(c.olt_puerto):''}`);
    }
    if(c.pppoe_usuario) partes.push(`👤 ${escHtml(c.pppoe_usuario)}`);
    if(c.pppoe_clave) partes.push(`🔑 ${escHtml(c.pppoe_clave)}`);
    const datosRed = partes.length
      ? `<div style="font-size:.74rem;line-height:1.6">${partes.join('<br>')}</div>`
      : '<span style="color:#aaa;font-size:.74rem">sin asignar</span>';
    return `<tr>
      <td>${nro}</td>
      <td><b>${escHtml(c.nombre)||'—'}</b></td>
      <td>${_badgeTipoSvc(c.tipo_servicio)}</td>
      <td>${escHtml(c.plan)||'—'}</td>
      <td>${escHtml(c.localidad)||'—'}</td>
      <td>${datosRed}</td>
      <td>${_diasTxt(dias)}</td>
      <td>
        <button class="btn btn-gray btn-xs" onclick="openModalCliente(${c.id})" title="Ver/editar">✏️</button>
      </td>
    </tr>`;
  }).join('');
}

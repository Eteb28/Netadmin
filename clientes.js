/* ═══════════════════════════════════════════════════════════════════
   clientes.js — NetAdmin v2 (refactor minimalista)
   Usa /api/v2/clientes y /api/v2/clientes/<id>
   ═══════════════════════════════════════════════════════════════════ */

// ─── Estado ───────────────────────────────────────────────────────
let cli2Page    = 1;
let cli2Total   = 0;
let cli2PerPage = 50;
let cli2Timer   = null;
let cli2MapInstance = null;
let cli2MapMarker   = null;
let cli2EditMode    = false;

// ─── Arranque ─────────────────────────────────────────────────────
async function cli2Init() {
  await cli2LoadFiltros();
  await cli2Load();
}

// ─── Cargar opciones de filtros ───────────────────────────────────
async function cli2LoadFiltros() {
  const d = await api('/api/v2/clientes/filtros');
  if (!d) return;

  // Localidades
  const sel = document.getElementById('cli2-loc');
  if (sel) {
    sel.innerHTML = '<option value="">Todas las localidades</option>' +
      d.localidades.map(l => `<option value="${l}">${l}</option>`).join('');
  }

  // Chips de contadores
  const chipTotal  = document.getElementById('cli2-chip-total');
  const chipCoords = document.getElementById('cli2-chip-coords');
  const chipPte    = document.getElementById('cli2-chip-pte');
  if (chipTotal)  chipTotal.textContent  = `👥 ${d.counts.total.toLocaleString()} clientes`;
  if (chipCoords) chipCoords.textContent = `📍 ${d.counts.con_coords.toLocaleString()} georef.`;
  if (chipPte)    chipPte.textContent    = `⚠ ${d.counts.sin_erp} sin ERP`;
}

// ─── Carga principal del listado ──────────────────────────────────
async function cli2Load() {
  const q        = (document.getElementById('cli2-q')?.value || '').trim();
  const estado   = document.getElementById('cli2-estado')?.value || '';
  const tipo     = document.getElementById('cli2-tipo')?.value || '';
  const loc      = document.getElementById('cli2-loc')?.value || '';
  const coords   = document.getElementById('cli2-con-coords')?.checked ? 'true' : '';
  const pteErp   = document.getElementById('cli2-pte-erp')?.checked ? '1' : '';

  const params = new URLSearchParams({
    page: cli2Page, per_page: cli2PerPage,
    ...(q      && { q }),
    ...(estado && { estado }),
    ...(tipo   && { tipo }),
    ...(loc    && { localidad: loc }),
    ...(coords && { con_coords: coords }),
    ...(pteErp && { solo_pte_erp: pteErp }),
  });

  const d = await api(`/api/v2/clientes?${params}`);
  if (!d) return;

  cli2Total = d.total;
  const tbody = document.getElementById('cli2-tbody');
  if (!tbody) return;

  if (!d.data.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="cli2-loading">Sin resultados</td></tr>';
    cli2UpdatePag(0, 0);
    return;
  }

  tbody.innerHTML = d.data.map(c => cli2RowHtml(c)).join('');

  // Paginación
  const desde = (cli2Page - 1) * cli2PerPage + 1;
  const hasta = desde + d.data.length - 1;
  cli2UpdatePag(desde, hasta);
  document.getElementById('cli2-prev').disabled = cli2Page <= 1;
  document.getElementById('cli2-next').disabled = hasta >= cli2Total;
}

function cli2RowHtml(c) {
  const nro = c.nro_cliente
    ? `<span class="cli2-nro">#${c.nro_cliente}</span>`
    : '';
  const sinErp = c.sin_erp
    ? `<span class="cli2-sin-erp-icon" title="Pendiente de cargar al ERP">⚠</span>`
    : '';
  const tipo   = c.tipo_servicio
    ? `<span class="cli2-badge b2-${c.tipo_servicio}">${c.tipo_servicio === 'fibra' ? 'Fibra' : 'Inalám.'}</span>`
    : '—';
  const estado = c.estado
    ? `<span class="cli2-badge b2-${c.estado}">${estadoLabel2(c.estado)}</span>`
    : '—';
  const geo = c.tiene_coords ? '📍' : '<span style="color:var(--txt2);font-size:.7rem">—</span>';

  const nap = (c.nap || '—').length > 18
    ? `<span title="${c.nap}">${(c.nap||'').substring(0, 18)}…</span>`
    : (c.nap || '—');
  const olt = (c.olt_nombre || '—').length > 14
    ? `<span title="${c.olt_nombre}">${(c.olt_nombre||'').substring(0, 14)}…</span>`
    : (c.olt_nombre || '—');

  return `<tr style="cursor:pointer" onclick="cli2OpenDetalle(${c.id})">
    <td>${nro}${sinErp}</td>
    <td><b>${c.nombre || '—'}</b></td>
    <td>${c.dni || '—'}</td>
    <td>${c.telefono || '—'}</td>
    <td>${c.localidad || '—'}</td>
    <td>${tipo}</td>
    <td>${estado}</td>
    <td style="font-size:.75rem">${nap}</td>
    <td style="font-size:.75rem">${olt}</td>
    <td style="text-align:center">${geo}</td>
    <td style="text-align:center">
      <button class="btn btn-gray btn-xs"
        onclick="event.stopPropagation();cli2OpenDetalle(${c.id})">›</button>
    </td>
  </tr>`;
}

function estadoLabel2(e) {
  return { activo:'Activo', suspendido:'Susp.', baja:'Baja',
           rescision:'Rescisión', venta:'Venta' }[e] || e;
}

function cli2UpdatePag(desde, hasta) {
  const el = document.getElementById('cli2-pag-info');
  if (el) {
    if (!cli2Total) { el.textContent = 'Sin resultados'; return; }
    el.textContent = `${desde}-${hasta} de ${cli2Total.toLocaleString()}`;
  }
}

function cli2Debounce() {
  clearTimeout(cli2Timer);
  cli2Timer = setTimeout(() => { cli2Page = 1; cli2Load(); }, 300);
}

function cli2PrevPage() { if (cli2Page > 1) { cli2Page--; cli2Load(); } }
function cli2NextPage() { cli2Page++; cli2Load(); }


// ═══════════════════════════════════════════════════════════════════
// MODAL DETALLE CLIENTE
// ═══════════════════════════════════════════════════════════════════
async function cli2OpenDetalle(id) {
  document.getElementById('modal-cli2').style.display = 'flex';
  document.getElementById('cli2-detalle-content').innerHTML =
    '<div style="text-align:center;padding:2rem;color:var(--txt2)">Cargando…</div>';

  const d = await api(`/api/v2/clientes/${id}`);
  if (!d || d.error) {
    document.getElementById('cli2-detalle-content').innerHTML =
      '<div style="color:red;padding:1rem">Error al cargar el cliente.</div>';
    return;
  }

  document.getElementById('cli2-detalle-content').innerHTML = cli2DetalleHtml(d);
  cli2InitMinimap(d.cliente);
}

function closeCli2Modal() {
  document.getElementById('modal-cli2').style.display = 'none';
  if (cli2MapInstance) { cli2MapInstance.remove(); cli2MapInstance = null; cli2MapMarker = null; }
  cli2EditMode = false;
}

function cli2DetalleHtml(d) {
  const c  = d.cliente;
  const co = d.contrato;
  const ca = d.calculo_enlace;
  const mo = d.morosidad;

  const sinErpBadge = c.origen === 'netadmin'
    ? `<span style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;
         border-radius:10px;font-size:.72rem;padding:1px 8px;margin-left:6px">⚠ Sin ERP</span>`
    : '';

  // Cabecera
  let html = `
    <div style="display:flex;align-items:baseline;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap">
      <h2 style="margin:0;font-size:1.1rem">${c.nombre || '(sin nombre)'}${sinErpBadge}</h2>
      <span style="color:var(--txt2);font-size:.8rem">${c.nro_cliente ? '#'+c.nro_cliente : 'Sin Nº ERP'}</span>
    </div>`;

  // Bloque 1: Datos básicos
  html += cli2Bloque('📋 Datos básicos', `
    <div class="cli2-grid">
      ${cli2Campo('Nº cliente',    c.nro_cliente  || '—')}
      ${cli2Campo('DNI / CUIT',    c.dni          || '—')}
      ${cli2Campo('Email',         c.email        || '—')}
      ${cli2Campo('Teléfono 1',    c.telefono     || '—')}
      ${cli2Campo('Teléfono 2',    c.telefono2    || '—')}
      ${cli2Campo('Dirección',     c.direccion    || '—', 2)}
      ${cli2Campo('Localidad',     c.localidad    || '—')}
    </div>
  `, false);

  // Bloque 2: Estado del servicio
  html += cli2Bloque('📡 Servicio', `
    <div class="cli2-grid">
      ${cli2Campo('Estado',        estadoBadge2(c.estado))}
      ${cli2Campo('Tipo',          c.tipo_servicio === 'fibra' ? 'Fibra óptica' : c.tipo_servicio === 'inalambrico' ? 'Inalámbrico' : c.tipo_servicio || '—')}
      ${cli2Campo('Fecha alta',    c.fecha_alta   || '—')}
      ${cli2Campo('Fecha baja',    c.fecha_baja   || '—')}
      ${cli2Campo('Agente',        c.agente       || '—')}
      ${cli2Campo('Plan / Tarifa', c.plan         || (co?.coste ? '$'+co.coste : '—'))}
      ${co ? cli2Campo('Contrato', co.codigo + ' — ' + (co.estado_workflow || '')) : ''}
    </div>
  `, false);

  // Bloque 3: Datos técnicos (NetAdmin, editables)
  const origenCoords = c.coords_origen === 'netadmin'
    ? '<span class="cli2-origen-netadmin" title="Cargado en NetAdmin">🔒</span>'
    : '<span class="cli2-origen-erp" title="Del ERP, se actualiza solo">🔄</span>';

  html += cli2Bloque('🔧 Datos técnicos (NetAdmin)', `
    <div id="cli2-tec-view-${c.id}">
      <div class="cli2-grid">
        ${cli2Campo('NAP', (c.nap || '—') + (c.nap_origen==='netadmin'?'<span class="cli2-origen-netadmin">🔒</span>':'<span class="cli2-origen-erp">🔄</span>'))}
        ${cli2Campo('OLT', (c.olt_nombre || '—') + (c.olt_origen==='netadmin'?'<span class="cli2-origen-netadmin">🔒</span>':'<span class="cli2-origen-erp">🔄</span>'))}
        ${cli2Campo('Puerto OLT', c.olt_puerto || '—')}
        ${cli2Campo('Torre', c.ap_nombre ? (c.ap_nombre) : '—')}
        ${cli2Campo('Equipo serie', (c.equipo_serie || '—') + (c.equipo_origen==='netadmin'?'<span class="cli2-origen-netadmin">🔒</span>':'<span class="cli2-origen-erp">🔄</span>'))}
        ${cli2Campo('Modelo', c.equipo_modelo || '—')}
        ${cli2Campo('Marca', c.equipo_marca || '—')}
        ${cli2Campo('MAC', c.mac_address || '—')}
        ${cli2Campo('IP asignada', c.ip_asignada || '—')}
        ${cli2Campo('PPPoE usuario', c.pppoe_usuario || '—')}
        ${cli2Campo('Lat / Lng', c.lat ? `${c.lat}, ${c.lng}` : '—')}
        ${cli2Campo('Obs. técnicas', c.observaciones_tecnicas || '—', 2)}
      </div>
      <div style="margin-top:.6rem">
        <button class="btn btn-gray btn-sm" onclick="cli2EditarTecnicos(${c.id})">✏️ Editar técnicos</button>
      </div>
    </div>
    <div id="cli2-tec-edit-${c.id}" style="display:none">
      ${cli2FormTecnicos(c)}
    </div>
  `, false);

  // Mini-mapa
  html += `<div class="cli2-bloque" style="margin-bottom:.7rem">
    <div class="cli2-bloque-hdr" style="cursor:default">🗺️ Mapa</div>
    <div class="cli2-bloque-body">
      <div id="cli2-minimap"></div>
      ${!c.lat ? '<div style="font-size:.8rem;color:var(--txt2);margin-top:.4rem">Sin coordenadas — asignalas en "Datos técnicos"</div>' : ''}
    </div>
  </div>`;

  // Bloque 4: Histórico
  const senales = d.historico?.senales || [];
  const equipos = d.historico?.equipos || [];
  const insts   = d.historico?.instalaciones || [];

  let histHtml = '';
  if (senales.length) {
    histHtml += `<div style="font-size:.78rem;font-weight:600;margin-bottom:.3rem">Señales</div>`;
    histHtml += `<table class="cli2-hist-tabla"><thead><tr><th>Fecha</th><th>dBm</th><th>Tipo</th><th>Obs.</th></tr></thead><tbody>`;
    histHtml += senales.map(s => `<tr>
      <td>${s.fecha ? s.fecha.substring(0,16) : '—'}</td>
      <td>${s.valor_dbm || '—'}</td>
      <td>${s.tipo || '—'}</td>
      <td>${s.observaciones || ''}</td>
    </tr>`).join('');
    histHtml += '</tbody></table><br>';
  }
  if (equipos.length) {
    histHtml += `<div style="font-size:.78rem;font-weight:600;margin-bottom:.3rem">Equipos</div>`;
    histHtml += `<table class="cli2-hist-tabla"><thead><tr><th>Serie</th><th>Modelo</th><th>IP</th><th>Desde</th><th>Hasta</th></tr></thead><tbody>`;
    histHtml += equipos.map(e => `<tr>
      <td>${e.equipo_serie || '—'}</td>
      <td>${e.equipo_modelo || '—'}</td>
      <td>${e.ip_asignada || '—'}</td>
      <td>${e.fecha_asignacion ? e.fecha_asignacion.substring(0,10) : '—'}</td>
      <td>${e.fecha_liberacion ? e.fecha_liberacion.substring(0,10) : '—'}</td>
    </tr>`).join('');
    histHtml += '</tbody></table><br>';
  }
  if (insts.length) {
    histHtml += `<div style="font-size:.78rem;font-weight:600;margin-bottom:.3rem">Instalaciones</div>`;
    histHtml += `<table class="cli2-hist-tabla"><thead><tr><th>Venta</th><th>Instalación</th><th>Técnico</th><th>dBm</th></tr></thead><tbody>`;
    histHtml += insts.map(i => `<tr>
      <td>${i.fecha_venta ? i.fecha_venta.substring(0,10) : '—'}</td>
      <td>${i.fecha_instalacion ? i.fecha_instalacion.substring(0,10) : '—'}</td>
      <td>${i.tecnico_nombre || '—'}</td>
      <td>${i.senal_inicial_dbm || '—'}</td>
    </tr>`).join('');
    histHtml += '</tbody></table>';
  }

  if (histHtml) {
    html += cli2Bloque('📜 Histórico', histHtml, true);
  }

  // Bloque 5: Cálculos de enlace
  if (ca) {
    html += cli2Bloque('📐 Cálculos de enlace (ERP)', `
      <div class="cli2-grid">
        ${cli2Campo('Distancia', ca.distancia_metros ? ca.distancia_metros + ' m' : '—')}
        ${cli2Campo('Altura AP', ca.altura_ap ? ca.altura_ap + ' m' : '—')}
        ${cli2Campo('Altura SM', ca.altura_sm ? ca.altura_sm + ' m' : '—')}
        ${cli2Campo('AirMax', ca.tieneairmax ? '✓ Sí' : 'No')}
        ${ca.observaciones ? cli2Campo('Observaciones', ca.observaciones, 2) : ''}
      </div>
    `, true);
  }

  return html;
}

// ─── Helpers de UI ────────────────────────────────────────────────
function cli2Bloque(titulo, contenido, colapsado = false) {
  const cls = colapsado ? 'cli2-bloque collapsed' : 'cli2-bloque';
  return `
    <div class="${cls}">
      <div class="cli2-bloque-hdr" onclick="cli2ToggleBloque(this)">
        ${titulo} <span class="cli2-chev">▾</span>
      </div>
      <div class="cli2-bloque-body">${contenido}</div>
    </div>`;
}

function cli2ToggleBloque(hdr) {
  hdr.closest('.cli2-bloque').classList.toggle('collapsed');
}

function cli2Campo(label, val, span = 1) {
  const style = span > 1 ? ` style="grid-column:span ${span}"` : '';
  return `<div class="cli2-campo"${style}>
    <label>${label}</label>
    <div class="cli2-val">${val ?? '—'}</div>
  </div>`;
}

function estadoBadge2(e) {
  const map = {
    activo:     ['b2-activo',    'Activo'],
    suspendido: ['b2-suspendido','Suspendido'],
    baja:       ['b2-baja',      'Baja'],
    rescision:  ['b2-rescision', 'Rescisión'],
    venta:      ['',             'En venta'],
  };
  const [cls, label] = map[e] || ['', e || '—'];
  return cls ? `<span class="cli2-badge ${cls}">${label}</span>` : (label || '—');
}

// ─── Mini-mapa ────────────────────────────────────────────────────
function cli2InitMinimap(c) {
  setTimeout(() => {
    const el = document.getElementById('cli2-minimap');
    if (!el || typeof L === 'undefined') return;
    if (cli2MapInstance) { cli2MapInstance.remove(); cli2MapInstance = null; }

    const lat = c.lat || -31.73;
    const lng = c.lng || -60.52;
    const zoom = c.lat ? 15 : 12;

    cli2MapInstance = L.map('cli2-minimap', { zoomControl: true, scrollWheelZoom: false }).setView([lat, lng], zoom);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OSM', maxZoom: 19
    }).addTo(cli2MapInstance);

    if (c.lat) {
      cli2MapMarker = L.marker([lat, lng]).addTo(cli2MapInstance);
      cli2MapMarker.bindPopup(`<b>${c.nombre}</b><br>${c.localidad || ''}`).openPopup();
    }
  }, 80);
}

// ─── Edición de campos técnicos ───────────────────────────────────
function cli2FormTecnicos(c) {
  return `
    <div class="cli2-grid" style="margin-bottom:.6rem">
      <div class="cli2-campo">
        <label>Latitud</label>
        <input id="tec-lat" type="number" step="0.0001" value="${c.lat || ''}">
      </div>
      <div class="cli2-campo">
        <label>Longitud</label>
        <input id="tec-lng" type="number" step="0.0001" value="${c.lng || ''}">
      </div>
      <div class="cli2-campo">
        <label>NAP asignada <span class="cli2-origen-netadmin">se marcará 🔒</span></label>
        <input id="tec-nap" type="text" value="${c.nap || ''}">
      </div>
      <div class="cli2-campo">
        <label>OLT nombre</label>
        <input id="tec-olt" type="text" value="${c.olt_nombre || ''}">
      </div>
      <div class="cli2-campo">
        <label>Puerto OLT</label>
        <input id="tec-olt-puerto" type="text" value="${c.olt_puerto || ''}">
      </div>
      <div class="cli2-campo">
        <label>Torre ID</label>
        <input id="tec-torre" type="number" value="${c.torre_id || ''}">
      </div>
      <div class="cli2-campo">
        <label>AP / Nombre</label>
        <input id="tec-ap" type="text" value="${c.ap_nombre || ''}">
      </div>
      <div class="cli2-campo">
        <label>Equipo serie</label>
        <input id="tec-serie" type="text" value="${c.equipo_serie || ''}">
      </div>
      <div class="cli2-campo">
        <label>Modelo</label>
        <input id="tec-modelo" type="text" value="${c.equipo_modelo || ''}">
      </div>
      <div class="cli2-campo">
        <label>Marca</label>
        <input id="tec-marca" type="text" value="${c.equipo_marca || ''}">
      </div>
      <div class="cli2-campo">
        <label>MAC address</label>
        <input id="tec-mac" type="text" value="${c.mac_address || ''}">
      </div>
      <div class="cli2-campo">
        <label>IP asignada</label>
        <input id="tec-ip" type="text" value="${c.ip_asignada || ''}">
      </div>
      <div class="cli2-campo">
        <label>PPPoE usuario</label>
        <input id="tec-pppoe" type="text" value="${c.pppoe_usuario || ''}">
      </div>
      <div class="cli2-campo" style="grid-column:span 2">
        <label>Observaciones técnicas</label>
        <textarea id="tec-obs" rows="2">${c.observaciones_tecnicas || ''}</textarea>
      </div>
    </div>
    <div style="display:flex;gap:.5rem">
      <button class="btn btn-prim btn-sm" onclick="cli2GuardarTecnicos(${c.id})">💾 Guardar</button>
      <button class="btn btn-gray btn-sm" onclick="cli2CancelarEdicion(${c.id})">Cancelar</button>
    </div>`;
}

function cli2EditarTecnicos(id) {
  document.getElementById(`cli2-tec-view-${id}`).style.display = 'none';
  document.getElementById(`cli2-tec-edit-${id}`).style.display = '';
}

function cli2CancelarEdicion(id) {
  document.getElementById(`cli2-tec-view-${id}`).style.display = '';
  document.getElementById(`cli2-tec-edit-${id}`).style.display = 'none';
}

async function cli2GuardarTecnicos(id) {
  const body = {
    lat:                  parseFloat(document.getElementById('tec-lat')?.value) || null,
    lng:                  parseFloat(document.getElementById('tec-lng')?.value) || null,
    nap:                  document.getElementById('tec-nap')?.value.trim() || null,
    olt_nombre:           document.getElementById('tec-olt')?.value.trim() || null,
    olt_puerto:           document.getElementById('tec-olt-puerto')?.value.trim() || null,
    torre_id:             parseInt(document.getElementById('tec-torre')?.value) || null,
    ap_nombre:            document.getElementById('tec-ap')?.value.trim() || null,
    equipo_serie:         document.getElementById('tec-serie')?.value.trim() || null,
    equipo_modelo:        document.getElementById('tec-modelo')?.value.trim() || null,
    equipo_marca:         document.getElementById('tec-marca')?.value.trim() || null,
    mac_address:          document.getElementById('tec-mac')?.value.trim() || null,
    ip_asignada:          document.getElementById('tec-ip')?.value.trim() || null,
    pppoe_usuario:        document.getElementById('tec-pppoe')?.value.trim() || null,
    observaciones_tecnicas: document.getElementById('tec-obs')?.value.trim() || null,
  };

  // Eliminar nulls (no enviar campos vacíos que sobreescriban innecesariamente)
  Object.keys(body).forEach(k => { if (body[k] === null || body[k] === '') delete body[k]; });

  const r = await fetch(`/api/v2/clientes/${id}/tecnicos`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!data.ok) {
    alert('Error al guardar: ' + (data.error || 'desconocido'));
    return;
  }

  // Actualizar mini-mapa si cambiaron coords
  if (body.lat && body.lng && cli2MapInstance) {
    const pos = [body.lat, body.lng];
    cli2MapInstance.setView(pos, 15);
    if (cli2MapMarker) {
      cli2MapMarker.setLatLng(pos);
    } else {
      cli2MapMarker = L.marker(pos).addTo(cli2MapInstance);
    }
  }

  // Cerrar modo edición y recargar detalle
  closeCli2Modal();
  cli2OpenDetalle(id);
}

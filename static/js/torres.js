/* ════════════════════════════════════════════════════════
   torres.js — Página "🗼 Torres Repetidoras"
   (gestión de torres: alta, edición, proveedores, estados, jerarquía)
   ════════════════════════════════════════════════════════ */

let _torresData = [];
let _debounceTorresTimer = null;

function debouncedLoadTorres(){
  clearTimeout(_debounceTorresTimer);
  _debounceTorresTimer = setTimeout(loadTorres, 300);
}

async function loadTorres(){
  const cont = document.getElementById('torres-list');
  if(cont) cont.innerHTML = '<div style="color:#888;padding:1rem">Cargando torres...</div>';
  const data = await api('/api/torres');
  if(!data){ if(cont) cont.innerHTML = '<div style="color:#888;padding:1rem">No se pudo cargar</div>'; return; }
  _torresData = data;
  renderTorres();
}

function renderTorres(){
  const cont = document.getElementById('torres-list');
  if(!cont) return;
  const q = (document.getElementById('torre-q')?.value || '').toLowerCase();
  const estadoFil = document.getElementById('torre-estado-fil')?.value || '';

  let torres = _torresData;
  if(q) torres = torres.filter(t =>
    [t.nombre, t.localidad, t.direccion, t.proveedor, t.ip_equipos].some(v => (v||'').toLowerCase().includes(q)));
  if(estadoFil) torres = torres.filter(t => (t.estado||'') === estadoFil);

  if(!torres.length){
    cont.innerHTML = '<div style="color:#888;padding:1rem">No hay torres que coincidan</div>';
    return;
  }

  // Mapa id→nombre para mostrar la torre padre
  const nombrePorId = {};
  _torresData.forEach(t => nombrePorId[t.id] = t.nombre);

  const colorEstado = e => ({activa:'#2e7d32', inactiva:'#c62828', mantenimiento:'#e65100', baja:'#757575'}[e] || '#757575');
  const iconTipo = t => ({principal:'🗼', repetidora:'📡', ap:'📶', nodo:'🔀'}[t] || '🗼');

  cont.innerHTML = `<div class="tbl-wrap"><table style="width:100%;border-collapse:collapse">
    <thead><tr style="background:var(--card)">
      <th style="text-align:left;padding:.5rem">Torre</th>
      <th style="text-align:left;padding:.5rem">Tipo</th>
      <th style="text-align:left;padding:.5rem">Localidad</th>
      <th style="text-align:left;padding:.5rem">Proveedor</th>
      <th style="text-align:left;padding:.5rem">Padre</th>
      <th style="text-align:left;padding:.5rem">Altura</th>
      <th style="text-align:left;padding:.5rem">Estado</th>
      <th style="text-align:right;padding:.5rem">Acciones</th>
    </tr></thead>
    <tbody>${torres.map(t=>`<tr style="border-bottom:1px solid var(--brd)">
      <td style="padding:.5rem"><b>${iconTipo(t.tipo)} ${escHtml(t.nombre)||'—'}</b>${t.orientaciones?`<br><small style="color:#999">${escHtml(t.orientaciones)}</small>`:''}</td>
      <td style="padding:.5rem">${escHtml(t.tipo)||'—'}</td>
      <td style="padding:.5rem">${escHtml(t.localidad)||'—'}</td>
      <td style="padding:.5rem">${t.proveedor?`<span style="background:var(--tint-azul);color:#1565c0;border-radius:4px;padding:1px 6px;font-size:.78rem">${escHtml(t.proveedor)}</span>`:'—'}</td>
      <td style="padding:.5rem">${t.torre_padre_id?escHtml(nombrePorId[t.torre_padre_id]||'—'):'<span style="color:#999">principal</span>'}</td>
      <td style="padding:.5rem">${t.altura_mts?escHtml(t.altura_mts)+'m':'—'}</td>
      <td style="padding:.5rem"><span style="color:${colorEstado(t.estado)};font-weight:600">●</span> ${escHtml(t.estado)||'—'}</td>
      <td style="padding:.5rem;text-align:right;white-space:nowrap">
        <button class="btn btn-gray btn-xs" onclick="openModalTorre(${t.id})">✏️</button>
        <button class="btn btn-rj btn-xs" onclick="deleteTorre(${t.id})">🗑</button>
      </td>
    </tr>`).join('')}</tbody>
  </table></div>
  <div style="font-size:.8rem;color:#999;margin-top:.5rem">${torres.length} torre(s)</div>`;
}

// Mostrar/ocultar el campo proveedor según el tipo (solo para principal/backbone)
function torreTypoChange(){
  const tipo = document.getElementById('mtorre-tipo')?.value;
  const provRow = document.getElementById('mtorre-prov-row');
  if(provRow) provRow.style.display = (tipo === 'principal') ? '' : 'none';
}

async function openModalTorre(id=null){
  // Poblar el select de torre padre con las torres existentes
  const selPadre = document.getElementById('mtorre-padre');
  if(selPadre){
    selPadre.innerHTML = '<option value="">Ninguna (torre principal)</option>';
    _torresData.forEach(t=>{
      if(id && t.id===id) return; // no puede ser su propio padre
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.nombre;
      selPadre.appendChild(o);
    });
  }

  const set = (eid, val) => { const el=document.getElementById(eid); if(el) el.value = val ?? ''; };

  if(id){
    const t = _torresData.find(x=>x.id===id);
    if(!t){ alert('Torre no encontrada'); return; }
    document.getElementById('mtorre-title').textContent = 'Editar Torre';
    set('mtorre-id', t.id);
    set('mtorre-nombre', t.nombre);
    set('mtorre-tipo', t.tipo||'repetidora');
    set('mtorre-proveedor', t.proveedor);
    set('mtorre-localidad', t.localidad);
    set('mtorre-direccion', t.direccion);
    set('mtorre-lat', t.lat);
    set('mtorre-lng', t.lng);
    set('mtorre-altura', t.altura_mts);
    set('mtorre-estado', t.estado||'activa');
    set('mtorre-ips', t.ip_equipos);
    set('mtorre-orient', t.orientaciones);
    set('mtorre-padre', t.torre_padre_id);
    set('mtorre-obs', t.observaciones);
  } else {
    document.getElementById('mtorre-title').textContent = 'Nueva Torre';
    ['mtorre-id','mtorre-nombre','mtorre-proveedor','mtorre-localidad','mtorre-direccion',
     'mtorre-lat','mtorre-lng','mtorre-altura','mtorre-ips','mtorre-orient','mtorre-padre','mtorre-obs'
    ].forEach(e=>set(e,''));
    set('mtorre-tipo','repetidora');
    set('mtorre-estado','activa');
  }
  torreTypoChange(); // ajustar visibilidad del proveedor
  // Inventario + valoración: solo en edición
  const invPanel = document.getElementById('mtorre-inventario');
  if(invPanel){
    invPanel.style.display = id ? 'block' : 'none';
    if(id) cargarInventarioTorre(id);
  }
  document.getElementById('modal-torre').style.display = 'flex';
}

/* ══════════ Inventario de equipos por torre (Fase 7-9) ══════════ */
async function cargarInventarioTorre(torreId){
  // Valoración
  try {
    const v = await api(`/api/torres/${torreId}/valoracion`);
    const box = document.getElementById('mtorre-valoracion');
    if(v && box){
      box.innerHTML = `<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:.5rem">
        <div style="background:var(--surf2);border-radius:8px;padding:.6rem">
          <div style="font-size:.68rem;color:var(--txt2);text-transform:uppercase;letter-spacing:.06em">Valor equipos (actual)</div>
          <div style="font-size:1.15rem;font-weight:700;color:var(--optimo)">$${_miles(v.equipos_valor_actual)}</div>
          <div style="font-size:.68rem;color:var(--txt2)">${v.equipos_cantidad} equipos · costo hist. $${_miles(v.equipos_costo_historico)}</div>
        </div>
        <div style="background:var(--surf2);border-radius:8px;padding:.6rem">
          <div style="font-size:.68rem;color:var(--txt2);text-transform:uppercase;letter-spacing:.06em">Ingreso mensual</div>
          <div style="font-size:1.15rem;font-weight:700;color:var(--normal)">$${_miles(v.ingresos_mensuales)}</div>
          <div style="font-size:.68rem;color:var(--txt2)">${v.clientes_cantidad} clientes activos</div>
        </div>
        <div style="grid-column:1/-1;background:linear-gradient(90deg,rgba(124,58,237,.12),transparent);border:1px solid rgba(124,58,237,.3);border-radius:8px;padding:.6rem">
          <div style="font-size:.68rem;color:var(--txt2);text-transform:uppercase;letter-spacing:.06em">Valor total estimado del nodo</div>
          <div style="font-size:1.35rem;font-weight:800;color:#9676F1">$${_miles(v.valor_total_estimado)}</div>
          <div style="font-size:.66rem;color:var(--txt2)">valor equipos + ingresos anualizados (${_miles(v.valor_clientes_anual)}/año)</div>
        </div>
      </div>`;
    }
  } catch(e){}
  // Lista de equipos
  const list = document.getElementById('mtorre-equipos-list');
  const eq = await api(`/api/torres/${torreId}/equipos`);
  if(!eq || !eq.length){
    list.innerHTML = '<div style="color:var(--txt2);font-size:.82rem;padding:.5rem">Sin equipos cargados. Agregá el primero.</div>';
    return;
  }
  const estColor = {operativo:'var(--optimo)',en_reparacion:'var(--alerta)',de_baja:'var(--txt2)',repuesto:'var(--normal)'};
  const snmpDot = e => {
    if(!e.es_ap) return '';
    const c = e.snmp_estado==='online'?'#4FD1A5':e.snmp_estado==='offline'?'#F2607A':'#8FA6BF';
    return `<span title="SNMP: ${e.snmp_estado||'sin datos'}" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${c};margin-left:.3rem"></span>`;
  };
  list.innerHTML = eq.map(e=>`
    <div onclick='editarEquipoInv(${e.id})' style="cursor:pointer;background:var(--card);border:1px solid var(--brd);border-radius:8px;padding:.55rem .7rem;margin-bottom:.4rem;display:flex;align-items:center;gap:.5rem">
      <div style="flex:1">
        <div style="font-weight:600;font-size:.85rem">${escHtml(e.tipo)}${e.modelo?` · <span style="font-weight:400">${escHtml(e.modelo)}</span>`:''}${e.es_ap?' 📡':''}${snmpDot(e)}</div>
        <div style="font-size:.7rem;color:var(--txt2)">${[e.fabricante,e.nro_serie?'S/N '+e.nro_serie:'',e.ip].filter(Boolean).map(escHtml).join(' · ')||'—'}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:.8rem;font-weight:600">$${_miles(e.valor_actual)}</div>
        <div style="font-size:.66rem;color:${estColor[e.estado]||'var(--txt2)'}">${escHtml((e.estado||'').replace('_',' '))}</div>
      </div>
    </div>`).join('');
}

function _miles(n){ return (Math.round(n||0)).toLocaleString('es-AR'); }

async function _cargarTiposEquipo(){
  if(window._tiposEquipo) return window._tiposEquipo;
  window._tiposEquipo = await api('/api/inventario/tipos') || [];
  return window._tiposEquipo;
}

async function abrirEquipoInv(){
  const torreId = document.getElementById('mtorre-id').value;
  if(!torreId){ alert('Guardá la torre primero.'); return; }
  const tipos = await _cargarTiposEquipo();
  const selT = document.getElementById('minv-tipo');
  selT.innerHTML = tipos.map(t=>`<option value="${t}">${t}</option>`).join('');
  document.getElementById('minv-title').textContent = 'Nuevo equipo';
  document.getElementById('minv-id').value = '';
  document.getElementById('minv-torre-id').value = torreId;
  ['minv-fabricante','minv-modelo','minv-serie','minv-firmware','minv-mac','minv-ip',
   'minv-fecha-compra','minv-ubicacion','minv-costo','minv-valor','minv-obs','minv-snmp-ip'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.value='';
  });
  document.getElementById('minv-estado').value = 'operativo';
  document.getElementById('minv-es-ap').checked = false;
  document.getElementById('minv-snmp-comm').value = 'public';
  const verSel = document.getElementById('minv-snmp-ver'); if(verSel) verSel.value = '1';
  document.getElementById('minv-snmp-result').innerHTML = '';
  const detBox = document.getElementById('minv-snmp-detect'); if(detBox) detBox.innerHTML = '';
  _snmpDetectado = null;
  // limpiar marcas verdes de detección previa
  ['minv-fabricante','minv-modelo','minv-firmware','minv-mac'].forEach(id=>{
    const el=document.getElementById(id); if(el){ el.style.borderLeft=''; el.title=''; }
  });
  document.getElementById('minv-del').style.display = 'none';
  _limpiarFisico();
  await _cargarPerfilesSelect();
  minvToggleSnmp();
  abrirModal('modal-inv-equipo');
}

async function editarEquipoInv(eid){
  const torreId = document.getElementById('mtorre-id').value;
  const eq = await api(`/api/torres/${torreId}/equipos`);
  const e = (eq||[]).find(x=>x.id===eid);
  if(!e) return;
  const tipos = await _cargarTiposEquipo();
  document.getElementById('minv-tipo').innerHTML = tipos.map(t=>`<option value="${t}">${t}</option>`).join('');
  document.getElementById('minv-title').textContent = 'Editar equipo';
  const set=(id,val)=>{const el=document.getElementById(id);if(el)el.value=val??'';};
  set('minv-id',e.id); set('minv-torre-id',torreId);
  set('minv-tipo',e.tipo); set('minv-estado',e.estado||'operativo');
  set('minv-fabricante',e.fabricante); set('minv-modelo',e.modelo);
  set('minv-serie',e.nro_serie); set('minv-firmware',e.firmware);
  set('minv-mac',e.mac); set('minv-ip',e.ip);
  set('minv-fecha-compra',e.fecha_compra); set('minv-ubicacion',e.ubicacion);
  set('minv-costo',e.costo_adquisicion); set('minv-valor',e.valor_actual);
  set('minv-obs',e.observaciones);
  document.getElementById('minv-es-ap').checked = !!e.es_ap;
  set('minv-snmp-fab',e.snmp_fabricante||'ubiquiti');
  set('minv-snmp-comm',e.snmp_community||'public');
  set('minv-snmp-ver',e.snmp_version||'1');
  set('minv-snmp-ip',e.snmp_ip);
  _snmpDetectado = null;
  const detBox2 = document.getElementById('minv-snmp-detect'); if(detBox2) detBox2.innerHTML = '';
  ['minv-fabricante','minv-modelo','minv-firmware','minv-mac'].forEach(id=>{
    const el=document.getElementById(id); if(el){ el.style.borderLeft=''; el.title=''; }
  });
  document.getElementById('minv-snmp-result').innerHTML = e.ultimo_snmp?`<div style="font-size:.72rem;color:var(--txt2)">Último SNMP: ${e.ultimo_snmp} (${e.snmp_estado||'—'})</div>`:'';
  document.getElementById('minv-del').style.display = '';
  // Datos físicos / cobertura
  _limpiarFisico();
  await _cargarPerfilesSelect();
  const f = await api(`/api/inventario/equipos/${eid}/fisico`);
  if(f && f.fisico){
    const fi=f.fisico;
    set('minv-perfil', fi.perfil_radio_id||'');
    set('minv-azimut', fi.azimut); set('minv-apertura', fi.apertura_h_override);
    set('minv-alcance', fi.alcance_override_m); set('minv-altura', fi.altura_m);
    set('minv-tilt', fi.tilt); set('minv-polarizacion', fi.polarizacion||'');
    document.getElementById('minv-mostrar-cobertura').checked = !!fi.mostrar_cobertura;
  }
  _actualizarCoberturaEfectiva();
  minvToggleSnmp();
  abrirModal('modal-inv-equipo');
}

function minvToggleSnmp(){
  const on = document.getElementById('minv-es-ap').checked;
  document.getElementById('minv-snmp-fields').style.display = on?'block':'none';
}

// ── Datos físicos / cobertura (Prioridad 1) ──
let _perfilesRadio = [];

async function _cargarPerfilesSelect(seleccion){
  _perfilesRadio = await api('/api/perfiles_radio') || [];
  const sel = document.getElementById('minv-perfil');
  if(!sel) return;
  sel.innerHTML = '<option value="">— Ninguno —</option>' +
    _perfilesRadio.map(p=>`<option value="${p.id}">${p.fabricante} ${p.modelo}${p.tipo_equipo?' ('+p.tipo_equipo+')':''}</option>`).join('');
  if(seleccion) sel.value = seleccion;
}

function _limpiarFisico(){
  ['minv-azimut','minv-apertura','minv-alcance','minv-altura','minv-tilt'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.value='';
  });
  const pol=document.getElementById('minv-polarizacion'); if(pol) pol.value='';
  const per=document.getElementById('minv-perfil'); if(per) per.value='';
  const mc=document.getElementById('minv-mostrar-cobertura'); if(mc) mc.checked=false;
  const hint=document.getElementById('minv-cobertura-efectiva'); if(hint) hint.innerHTML='';
}

function _actualizarCoberturaEfectiva(){
  const hint=document.getElementById('minv-cobertura-efectiva'); if(!hint) return;
  const pid = document.getElementById('minv-perfil').value;
  const perfil = _perfilesRadio.find(p=>String(p.id)===String(pid));
  const apOv = parseFloat(document.getElementById('minv-apertura').value);
  const alOv = parseFloat(document.getElementById('minv-alcance').value);
  const ap = !isNaN(apOv)?apOv : (perfil?perfil.apertura_horizontal:null);
  const al = !isNaN(alOv)?alOv : (perfil?perfil.alcance_teorico_m:null);
  const nd = v => (v===null||v===undefined||v==='')?'<span style="color:var(--alerta)">No disponible</span>':v;
  hint.innerHTML = `Cobertura efectiva: apertura ${nd(ap)}${ap!=null&&ap!==''?'°':''} · alcance ${nd(al)}${al!=null&&al!==''?' m':''}`
    + (perfil && (isNaN(apOv)||isNaN(alOv)) ? ' <span style="color:var(--txt2)">(del perfil salvo override)</span>':'');
}

function _fisicoPayload(){
  const num=id=>{const v=parseFloat(document.getElementById(id).value);return isNaN(v)?null:v;};
  return {
    perfil_radio_id: document.getElementById('minv-perfil').value ? parseInt(document.getElementById('minv-perfil').value) : null,
    azimut: num('minv-azimut'),
    apertura_h_override: num('minv-apertura'),
    alcance_override_m: num('minv-alcance'),
    altura_m: num('minv-altura'),
    tilt: num('minv-tilt'),
    polarizacion: document.getElementById('minv-polarizacion').value || null,
    mostrar_cobertura: document.getElementById('minv-mostrar-cobertura').checked ? 1 : 0,
    fuente: 'manual'
  };
}

function _fisicoTieneDatos(p){
  // ¿vale la pena guardar? (algún dato físico cargado o quiere mostrar cobertura)
  return p.mostrar_cobertura || p.perfil_radio_id!=null || p.azimut!=null ||
         p.apertura_h_override!=null || p.alcance_override_m!=null ||
         p.altura_m!=null || p.tilt!=null || p.polarizacion;
}

function _minvPayload(){
  const v=id=>document.getElementById(id).value;
  return {
    torre_id: v('minv-torre-id'), tipo: v('minv-tipo'), estado: v('minv-estado'),
    fabricante: v('minv-fabricante'), modelo: v('minv-modelo'), nro_serie: v('minv-serie'),
    firmware: v('minv-firmware'), mac: v('minv-mac'), ip: v('minv-ip'),
    fecha_compra: v('minv-fecha-compra'), ubicacion: v('minv-ubicacion'),
    costo_adquisicion: parseFloat(v('minv-costo'))||0, valor_actual: parseFloat(v('minv-valor'))||0,
    observaciones: v('minv-obs'),
    es_ap: document.getElementById('minv-es-ap').checked?1:0,
    snmp_fabricante: v('minv-snmp-fab'), snmp_community: v('minv-snmp-comm'), snmp_ip: v('minv-snmp-ip'),
    snmp_version: (document.getElementById('minv-snmp-ver')||{}).value || '1',
    datos_snmp: _snmpDetectado || undefined
  };
}

async function guardarEquipoInv(){
  const id = document.getElementById('minv-id').value;
  const payload = _minvPayload();
  if(!payload.tipo){ alert('El tipo es obligatorio'); return; }
  const r = id ? await api(`/api/inventario/equipos/${id}`,'PUT',payload)
              : await api('/api/inventario/equipos','POST',payload);
  if(r && (r.ok||r.id)){
    // Guardar datos físicos / cobertura (upsert) contra el id resultante
    const eid = id || r.id;
    const fis = _fisicoPayload();
    if(eid && _fisicoTieneDatos(fis)){
      await api(`/api/inventario/equipos/${eid}/fisico`,'PUT',fis);
    }
    closeModal('modal-inv-equipo');
    cargarInventarioTorre(payload.torre_id);
  } else {
    alert('Error: '+(r&&r.error?r.error:'no se pudo guardar'));
  }
}

async function borrarEquipoInv(){
  const id = document.getElementById('minv-id').value;
  const torreId = document.getElementById('minv-torre-id').value;
  if(!id || !confirm('¿Eliminar este equipo del inventario?')) return;
  const r = await api(`/api/inventario/equipos/${id}`,'DELETE');
  if(r && r.ok){ closeModal('modal-inv-equipo'); cargarInventarioTorre(torreId); }
}

// ── Autocompletado del equipo vía SNMP (descubrimiento) ──
let _snmpDetectado = null;   // snapshot del último descubrimiento (se guarda como datos_snmp)

function _snmpFill(fieldId, valor, conflictos){
  // Completa un campo SOLO si está vacío; si tiene otro valor, lo reporta como conflicto
  if(valor === null || valor === undefined || valor === '') return;
  const el = document.getElementById(fieldId);
  if(!el) return;
  const actual = (el.value||'').trim();
  if(!actual){
    el.value = valor;
    el.style.borderLeft = '3px solid #4FD1A5';       // verde = detectado por SNMP
    el.title = 'Detectado automáticamente por SNMP';
  } else if(actual.toLowerCase() !== String(valor).toLowerCase()){
    conflictos.push({fieldId, valor, actual, label: el.previousElementSibling ? '' : fieldId});
  }
}

async function detectarEquipoSnmp(){
  const box = document.getElementById('minv-snmp-detect');
  const ip = (document.getElementById('minv-snmp-ip').value.trim() || document.getElementById('minv-ip').value.trim());
  if(!ip){ box.innerHTML = '<div style="color:var(--critico);font-size:.78rem">Cargá la IP de gestión (o la IP SNMP) primero.</div>'; return; }
  const community = document.getElementById('minv-snmp-comm').value.trim() || 'public';
  const version = document.getElementById('minv-snmp-ver').value || '1';
  const fabricante = document.getElementById('minv-snmp-fab').value || '';
  box.innerHTML = '<div style="color:var(--txt2);font-size:.78rem">🔎 Consultando equipo por SNMP… (unos segundos)</div>';

  const r = await api('/api/inventario/detectar','POST',{ip, community, version, fabricante});
  if(!r || !r.ok){
    box.innerHTML = `<div style="color:var(--critico);font-size:.8rem">✗ ${r?r.error:'Sin respuesta'}</div>`;
    return;
  }
  const dev = r.device || {};
  _snmpDetectado = dev;   // se enviará como datos_snmp al guardar

  // Autocompletar campos vacíos (sin pisar lo cargado a mano)
  const conflictos = [];
  _snmpFill('minv-fabricante', dev.fabricante, conflictos);
  _snmpFill('minv-modelo',     dev.modelo,     conflictos);
  _snmpFill('minv-firmware',   dev.firmware,   conflictos);
  _snmpFill('minv-mac',        dev.mac,        conflictos);
  // Si el adaptador no estaba elegido y se detectó, ajustarlo
  if(r.fabricante_detectado){
    const selFab = document.getElementById('minv-snmp-fab');
    if(selFab && [...selFab.options].some(o=>o.value===r.fabricante_detectado)) selFab.value = r.fabricante_detectado;
  }

  // Panel de datos detectados (incluye lo que no va a un campo del formulario)
  const nd = v => (v===null||v===undefined||v==='') ? '<span style="color:var(--txt2)">No disponible</span>' : escHtml(v);
  const filas = [
    ['Fabricante', dev.fabricante], ['Hostname', dev.hostname],
    ['Sistema', dev.sistema_operativo], ['Firmware', dev.firmware],
    ['Modelo', dev.modelo], ['MAC (radio)', dev.mac], ['Uptime', dev.uptime],
    ['Modo', dev.modo], ['SSID', dev.essid], ['Frecuencia', dev.frecuencia?dev.frecuencia+' MHz':null],
    ['Canal', dev.canal], ['Ancho', dev.ancho_mhz?dev.ancho_mhz+' MHz':null],
    ['Potencia TX', dev.potencia_tx], ['Antena', dev.antena],
    ['Clientes', dev.estaciones_n],
  ];
  let html = `<div style="background:var(--surf2);border-radius:8px;padding:.6rem;font-size:.78rem">
    <div style="font-weight:600;margin-bottom:.4rem">✓ Equipo detectado — revisá antes de guardar</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.15rem .8rem">
      ${filas.map(([k,v])=>`<div><span style="color:var(--txt2)">${k}:</span> ${nd(v)}</div>`).join('')}
    </div>`;
  // Interfaces LAN (IF-MIB) + alerta de 10 Mbps
  const lan = r.lan || [];
  if(r.lan_alerta){
    html += `<div style="margin-top:.5rem;background:#7a1f1f;color:#fff;border-radius:6px;padding:.5rem;font-weight:600">
      ⚠️ LAN NEGOCIADA A ${r.lan_alerta.velocidad_mbps} Mbps — Revisar cableado, conector, PoE/inyector y puerto.<br>
      <span style="font-weight:400;font-size:.75rem">Interfaz afectada: ${r.lan_alerta.interfaz}</span></div>`;
  }
  if(lan.length){
    html += `<div style="margin-top:.5rem;border-top:1px solid var(--brd);padding-top:.4rem">
      <div style="font-weight:600;margin-bottom:.2rem">🔌 Puertos LAN</div>
      ${lan.map(i=>{
        const est=i.estado_lan;
        const col = est==='critico'?'#F2607A':est==='down'?'var(--txt2)':est==='advertencia'?'#E8B04B':'#4FD1A5';
        const ic = est==='critico'?'🔴':est==='down'?'⚫':est==='advertencia'?'🟡':'🟢';
        const vel = i.oper==='up' ? `${i.speed_mbps} Mbps` : 'DOWN';
        const errs = (i.in_errors||i.out_errors)?` · err ${i.in_errors||0}/${i.out_errors||0}`:'';
        return `<div style="display:flex;gap:.5rem;padding:.12rem 0"><span>${ic}</span>
          <span style="flex:1">${escHtml(i.nombre)}</span>
          <span style="color:${col};font-weight:600">${vel}</span>
          <span style="color:var(--txt2);font-size:.72rem">${i.oper}${errs}</span></div>`;
      }).join('')}
    </div>`;
  }
  if(conflictos.length){
    html += `<div style="margin-top:.5rem;border-top:1px solid var(--brd);padding-top:.4rem">
      <div style="color:#8a3b0b;font-weight:600;margin-bottom:.2rem">⚠️ Difieren de lo cargado (no se sobrescribió):</div>
      ${conflictos.map((c,i)=>`<div style="display:flex;gap:.4rem;align-items:center;padding:.1rem 0">
        <span style="flex:1">manual: <b>${escHtml(c.actual)}</b> · SNMP: <b>${escHtml(c.valor)}</b></span>
        <button type="button" class="btn btn-am btn-xs" onclick="document.getElementById('${escJs(c.fieldId)}').value='${escJs(c.valor)}';this.closest('div').remove()">usar SNMP</button>
      </div>`).join('')}
    </div>`;
  }
  html += `<div style="color:var(--txt2);font-size:.7rem;margin-top:.4rem">Los campos completados en verde vienen de SNMP. Podés editarlos antes de guardar.</div></div>`;
  box.innerHTML = html;
}

function _renderLanInterfaces(box, data){
  const lan = data.lan || [];
  const inter = data.interfaces || [];
  if(!lan.length && !inter.length){ box.innerHTML = '<div style="color:var(--txt2);font-size:.78rem">Sin interfaces reportadas por IF-MIB.</div>'; return; }
  let html = '<div style="background:var(--surf2);border-radius:8px;padding:.6rem;font-size:.78rem">';
  if(data.lan_alerta){
    html += `<div style="margin-bottom:.5rem;background:#7a1f1f;color:#fff;border-radius:6px;padding:.5rem;font-weight:600">
      ⚠️ LAN NEGOCIADA A ${data.lan_alerta.velocidad_mbps} Mbps — Revisar cableado, conector, PoE/inyector y puerto.<br>
      <span style="font-weight:400;font-size:.75rem">Interfaz afectada: ${data.lan_alerta.interfaz}</span></div>`;
  }
  const linea = i=>{
    const est=i.estado_lan;
    const col = est==='critico'?'#F2607A':est==='down'||i.oper!=='up'?'var(--txt2)':est==='advertencia'?'#E8B04B':'#4FD1A5';
    const ic = est==='critico'?'🔴':(i.oper!=='up')?'⚫':est==='advertencia'?'🟡':'🟢';
    const vel = i.oper==='up' ? `${i.speed_mbps} Mbps` : 'DOWN';
    const errs = (i.in_errors||i.out_errors)?` · err ${i.in_errors||0}/${i.out_errors||0}`:'';
    return `<div style="display:flex;gap:.5rem;padding:.12rem 0"><span>${ic}</span>
      <span style="flex:1">${escHtml(i.nombre)}</span>
      <span style="color:${col};font-weight:600">${vel}</span>
      <span style="color:var(--txt2);font-size:.72rem">${i.oper}${errs}</span></div>`;
  };
  html += '<div style="font-weight:600;margin-bottom:.2rem">🔌 Puertos LAN</div>';
  html += (lan.length?lan:inter.filter(i=>i.es_lan)).map(linea).join('') || '<div style="color:var(--txt2);font-size:.72rem">Sin puertos ethernet.</div>';
  const otras = inter.filter(i=>!i.es_lan && i.nombre!=='lo');
  if(otras.length){
    html += '<div style="font-weight:600;margin:.4rem 0 .2rem;color:var(--txt2)">Otras interfaces</div>' + otras.map(linea).join('');
  }
  html += '</div>';
  box.innerHTML = html;
}

async function verInterfacesLan(){
  const id = document.getElementById('minv-id').value;
  const box = document.getElementById('minv-snmp-result');
  if(!id){ box.innerHTML = '<div style="color:var(--alerta);font-size:.75rem">Guardá el equipo primero para consultar sus interfaces.</div>'; return; }
  box.innerHTML = '<div style="color:var(--txt2);font-size:.78rem">🔌 Consultando interfaces LAN…</div>';
  const d = await api(`/api/inventario/equipos/${id}/interfaces`);
  if(!d || d.error){ box.innerHTML = `<div style="color:var(--critico);font-size:.8rem">✗ ${d?d.error:'sin respuesta'}</div>`; return; }
  _renderLanInterfaces(box, d);
}

async function probarSnmpEquipo(){
  const id = document.getElementById('minv-id').value;
  const box = document.getElementById('minv-snmp-result');
  if(!id){ box.innerHTML = '<div style="color:var(--alerta);font-size:.75rem">Guardá el equipo primero para poder sondearlo.</div>'; return; }
  box.innerHTML = '<div style="color:var(--txt2);font-size:.78rem">Sondeando… (puede tardar unos segundos)</div>';
  const d = await api(`/api/inventario/equipos/${id}/snmp_test`);
  if(!d || d.error){ box.innerHTML = `<div style="color:var(--critico);font-size:.78rem">✗ ${d?d.error:'sin respuesta'}</div>`; return; }
  const dev = d.device||{}; const est = d.estaciones||[];
  const vinc = est.filter(e=>e.cliente_id).length;
  box.innerHTML = `
    <div style="background:var(--surf2);border-radius:8px;padding:.6rem;font-size:.78rem">
      <div style="font-weight:600;margin-bottom:.3rem">✓ ${dev.essid||'AP'} · modo ${dev.modo||'?'} · ${est.length} estaciones (${vinc} vinculadas)</div>
      ${est.slice(0,12).map(e=>{
        const c=e.rssi>=-65?'#4FD1A5':e.rssi>=-75?'#E8B04B':'#F2607A';
        return `<div style="display:flex;gap:.5rem;padding:.15rem 0;border-bottom:1px solid var(--brd)">
          <span style="flex:1">${e.nombre||e.mac||'?'}</span>
          <span style="color:${c};font-weight:600">${e.rssi} dBm</span>
          <span style="color:var(--txt2);width:70px;text-align:right">${e.ccq!=null?'CCQ '+e.ccq+'%':''}</span>
          <span style="width:60px;text-align:right;color:${e.cliente_id?'var(--optimo)':'var(--txt2)'}">${e.cliente_id?'#'+e.cliente_id:'—'}</span>
        </div>`;
      }).join('')}
      ${est.length>12?`<div style="color:var(--txt2);margin-top:.3rem">+${est.length-12} más…</div>`:''}
    </div>`;
}

async function saveTorre(){
  const v = id => document.getElementById(id)?.value?.trim() || '';
  const nombre = v('mtorre-nombre');
  if(!nombre){ alert('El nombre es obligatorio'); return; }
  const id = v('mtorre-id');
  const payload = {
    nombre,
    tipo: v('mtorre-tipo') || 'repetidora',
    proveedor: v('mtorre-tipo')==='principal' ? v('mtorre-proveedor') : '',
    localidad: v('mtorre-localidad'),
    direccion: v('mtorre-direccion'),
    lat: v('mtorre-lat') || null,
    lng: v('mtorre-lng') || null,
    altura_mts: v('mtorre-altura') || null,
    estado: v('mtorre-estado') || 'activa',
    ip_equipos: v('mtorre-ips'),
    orientaciones: v('mtorre-orient'),
    torre_padre_id: v('mtorre-padre') || null,
    observaciones: v('mtorre-obs'),
  };
  const r = id
    ? await api(`/api/torres/${id}`, 'PUT', payload)
    : await api('/api/torres', 'POST', payload);
  if(r && (r.ok || r.id)){
    toast(id ? 'Torre actualizada' : 'Torre creada', 'ok');
    closeModal('modal-torre');
    loadTorres();
  } else {
    alert('Error: ' + (r?.error || 'no se pudo guardar la torre'));
  }
}

async function deleteTorre(id){
  if(!await confirmar('¿Eliminar esta torre? Esta acción no se puede deshacer.')) return;
  const r = await api(`/api/torres/${id}`, 'DELETE');
  if(r && r.ok){ toast('Torre eliminada', 'ok'); loadTorres(); }
  else alert('Error: ' + (r?.error || 'no se pudo eliminar'));
}

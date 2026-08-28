/* ========================================================
   clientes.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

function debouncedLoadClientes(){
  clearTimeout(searchTimeout);
  searchTimeout=setTimeout(loadClientes,300);
}

async function loadClientes(){
  const q=document.getElementById('cli-q').value;
  const estado=document.getElementById('cli-estado').value;
  const tipo=document.getElementById('cli-tipo').value;
  const loc=document.getElementById('cli-loc').value;
  const impagas=document.getElementById('cli-impagas')?.value||'';
  const d=await api(`/api/clientes?q=${encodeURIComponent(q)}&estado=${estado}&tipo=${tipo}&localidad=${encodeURIComponent(loc)}&impagas=${impagas}&page=${cliPage}&per_page=50`);
  if(!d) return;
  cliTotal=d.total;
  document.getElementById('cli-pag-info').textContent=`Mostrando ${d.clientes.length} de ${d.total}`;
  document.getElementById('cli-prev').disabled=cliPage<=1;
  document.getElementById('cli-next').disabled=d.clientes.length<50;
  const tbody=document.getElementById('cli-tbody');
  tbody.innerHTML=d.clientes.map(c=>{
    const nro = c.nro_cliente
      ? `<span style="font-family:monospace;font-weight:700;color:var(--prim2,#1976d2);font-size:.78rem">#${escHtml(c.nro_cliente)}</span><br>`
      : '';
    return `<tr>
    <td>${nro}<b>${escHtml(c.nombre)}</b><br><small style="color:var(--txt2)">${escHtml(c.direccion)}</small></td>
    <td>${escHtml(c.telefono)||'—'}</td>
    <td>${escHtml(c.localidad)||'—'}</td>
    <td><span class="badge b-${escHtml(c.tipo_servicio)}">${escHtml(c.tipo_servicio)}</span></td>
    <td>${escHtml(c.plan)||'—'}</td>
    <td>${escHtml(c.nap)||'—'}</td>
    <td><span class="badge b-${escHtml(c.estado)}">${escHtml(estadoLabel(c.estado))}</span></td>
    <td>${escHtml(c.ultimo_pago)||'—'}</td>
    <td>
      <button class="btn btn-gray btn-xs" onclick="openModalCliente(${c.id})">✏️</button>
      <button class="btn btn-am btn-xs" onclick="openModalServicio(null,${c.id},'${escJs(c.nombre)}')">🔧</button>
    </td>
  </tr>`;}).join('');
}

// ── MODAL CLIENTE ──

let _abonosCache = null;  // cache de abonos para autocompletar precio

async function _loadAbonosCache(){
  if(!_abonosCache){
    _abonosCache = await api('/api/abonos') || [];
  }
  return _abonosCache;
}

function onPlanChange(){
  // Autocompletar precio cuando cambia el plan, sólo si el campo precio está vacío o = 0
  const plan = document.getElementById('mcli-plan').value.trim();
  if(!plan) return;
  const precioInput = document.getElementById('mcli-precio');
  // Detectar si fue editado manualmente: si el input tiene un flag data-manual=true, NO sobrescribir
  if(precioInput.dataset.manual === '1') return;
  if(!_abonosCache) return; // todavía no cargó (se carga en openModalCliente)
  const a = _abonosCache.find(x => (x.nombre||'').toUpperCase() === plan.toUpperCase());
  if(a){
    precioInput.value = a.precio;
  }
}

// Marcar precio como editado manualmente cuando el usuario lo modifica
document.addEventListener('input', (e) => {
  if(e.target && e.target.id === 'mcli-precio'){
    e.target.dataset.manual = '1';
  }
});

async function openModalCliente(id=null){
  clearModalCliente();
  document.getElementById('ftth-potencial-info').style.display='none';
  document.getElementById('hist-section').style.display = id ? 'block' : 'none';
  // Pestañas: solo en modo edición (en alta nueva es un form corrido)
  const tabsBar = document.getElementById('mcli-tabs');
  if(tabsBar){
    tabsBar.style.display = id ? 'flex' : 'none';
    if(id){ mcliTab('general'); }
    else {
      // alta nueva: mostrar todo junto (sin pestañas)
      document.querySelectorAll('#modal-cliente .mcli-pane').forEach(p=>p.style.display='block');
    }
  }
  // resetear los flags de carga de cada pestaña (para que otro cliente recargue)
  ['mon-grafico','mcli-admin-cont','mcli-tec-cont','mcli-gen-hist','mcli-rec-cont'].forEach(cid=>{
    const el=document.getElementById(cid); if(el){ delete el.dataset.cargado; el.innerHTML=''; }
  });
  
  // Pre-cargar combos
  await _loadAbonosCache();
  await _poblarCombosCliente();
  
  if(id){
    document.getElementById('mcli-title').textContent='Editar Cliente';
    const d=await api(`/api/clientes/${id}`);
    if(!d) return;
    const c=d.cliente;
    document.getElementById('mcli-id').value=c.id;
    document.getElementById('mcli-nro').value=c.nro_cliente||'';
    document.getElementById('mcli-nombre').value=c.nombre||'';
    document.getElementById('mcli-dni').value=c.dni||'';
    document.getElementById('mcli-email').value=c.email||'';
    document.getElementById('mcli-dir').value=c.direccion||'';
    document.getElementById('mcli-loc').value=c.localidad||'';
    document.getElementById('mcli-lat').value=c.lat||'';
    document.getElementById('mcli-lng').value=c.lng||'';
    document.getElementById('mcli-tipo').value=c.tipo_servicio||'inalambrico';
    document.getElementById('mcli-estado').value=c.estado||'activo';
    document.getElementById('mcli-plan').value=c.plan||'';
    document.getElementById('mcli-precio').value=c.precio||'';
    document.getElementById('mcli-precio').dataset.manual = '1'; // ya tiene un valor; no sobrescribir
    document.getElementById('mcli-nap').value=c.nap||'';
    window._napOriginal = c.nap||'';
    if(typeof verNapOcupacion==='function') verNapOcupacion();
    document.getElementById('mcli-agente').value=c.agente||'';
    document.getElementById('mcli-equipo-modelo').value=c.equipo_modelo||'';
    document.getElementById('mcli-equipo-marca').value=c.equipo_marca||'';
    document.getElementById('mcli-serie').value=c.equipo_serie||'';
    document.getElementById('mcli-ip').value=c.ip_asignada||'';
    document.getElementById('mcli-mac').value=c.mac_address||'';
    document.getElementById('mcli-pppoe-user').value=c.pppoe_usuario||'';
    // Red avanzada: IP pública / puertos / modo / VLAN
    {const e=document.getElementById('mcli-modo-equipo'); if(e) e.value=c.modo_equipo||'';}
    {const e=document.getElementById('mcli-vlan'); if(e) e.value=c.vlan||'';}
    {const e=document.getElementById('mcli-ip-publica'); if(e) e.value=c.ip_publica||'';}
    {const e=document.getElementById('mcli-puertos-asignados'); if(e) e.value=c.puertos_asignados||'';}
    {const e=document.getElementById('mcli-tiene-ip-publica');
     if(e){ e.checked = !!(c.tiene_ip_publica || c.ip_publica || c.puertos_asignados);
            if(typeof mcliToggleIpPublica==='function') mcliToggleIpPublica(); }}
    document.getElementById('mcli-pppoe-pass').value=c.pppoe_clave||'';
    document.getElementById('mcli-olt-nombre').value=c.olt_nombre||'';
    document.getElementById('mcli-olt-puerto').value=c.olt_puerto||'';
    _cargarSenalCliente(id);
    if(c.nro_cliente) _cargarReclamosCliente(c.nro_cliente);
    if(document.getElementById('mcli-torre')) document.getElementById('mcli-torre').value = c.torre_id||'';
    if(document.getElementById('mcli-ap'))    document.getElementById('mcli-ap').value    = c.ap_nombre||'';
    document.getElementById('mcli-fecha-alta').value=c.fecha_alta||'';
    document.getElementById('mcli-ultimo-pago').value=c.ultimo_pago||'';
    document.getElementById('mcli-obs').value=c.observaciones||'';
    // Checkbox necesita NAP (visible solo para pte_calculo)
    const nnapWrap = document.getElementById('mcli-necesita-nap-wrap');
    if(nnapWrap) nnapWrap.style.display = (c.estado==='pte_calculo')?'block':'none';
    const nnapCb = document.getElementById('mcli-necesita-nap');
    if(nnapCb) nnapCb.checked = !!c.necesita_nap;
    
    // Cargar teléfonos
    _renderTelefonos(d.telefonos || []);
    
    toggleFtthFields();

    // Banner de afectación por incidencia
    let banner = document.getElementById('mcli-afectado-banner');
    if(!banner){
      banner = document.createElement('div');
      banner.id = 'mcli-afectado-banner';
      const form = document.getElementById('mcli-nombre')?.closest('.modal-body') || document.getElementById('mcli-nombre')?.parentElement?.parentElement;
      if(form) form.insertBefore(banner, form.firstChild);
    }
    if(c.afectado_por_incidencia){
      banner.style.display = 'block';
      banner.style.cssText = 'display:block;background:var(--card);border:2px solid #c62828;border-radius:8px;padding:.6rem .8rem;margin-bottom:.8rem;color:#b71c1c;font-weight:600;font-size:.85rem';
      banner.innerHTML = '🔴 Cliente afectado: ' + escHtml(c.motivo_afectacion||'Incidencia en infraestructura');
    } else {
      banner.style.display = 'none';
    }
    
    // Cargar tab por defecto de histórico
    showHistTab('equipos');
    
    // Migración FTTH potencial
    if(c.tipo_servicio!=='fibra' && c.lat){
      const pot=await api(`/api/clientes/${id}/ftth_potencial`);
      if(pot && pot.puede_migrar){
        document.getElementById('ftth-potencial-info').innerHTML=`
          <div class="alert-box ok">🔄 <b>¡Potencial de migración a FTTH!</b>
          Hay ${pot.vecinos_fibra} cliente(s) de fibra y ${pot.naps_cercanos?.length||0} NAP(s) cercanos.
          <button class="btn btn-vd btn-xs" style="margin-left:.5rem" onclick="openModalServicio(null,${id},'${escJs(c.nombre)}','migracion_ftth')">Crear Servicio de Migración</button>
          </div>`;
        document.getElementById('ftth-potencial-info').style.display='block';
      }
    }
  } else {
    document.getElementById('mcli-title').textContent='Nuevo Cliente';
    document.getElementById('mcli-fecha-alta').value=new Date().toISOString().slice(0,10);
    // Inicializar con 2 inputs de teléfono vacíos
    _renderTelefonos([{telefono:'',tipo:'movil'},{telefono:'',tipo:'movil'}]);
    document.getElementById('mcli-precio').dataset.manual = '0';
    toggleFtthFields();
  }
  document.getElementById('modal-cliente').style.display='flex';
  await _aplicarPermisosCampos();
  // Mostrar botón "Crear como venta nueva" solo en alta (no edición)
  const btnVenta = document.getElementById('btn-cli-venta');
  if(btnVenta) btnVenta.style.display = id ? 'none' : 'inline-block';
}

// Mapa: id de input del modal → bloque de permiso
const _CAMPO_BLOQUE = {
  'mcli-nro':'personales','mcli-nombre':'personales','mcli-dni':'personales',
  'mcli-email':'personales','mcli-dir':'personales','mcli-loc':'personales',
  'mcli-lat':'personales','mcli-lng':'personales',
  'mcli-plan':'comercial','mcli-precio':'comercial','mcli-agente':'comercial','mcli-ultimo-pago':'comercial','mcli-fecha-alta':'comercial',
  'mcli-tipo':'tecnico','mcli-nap':'tecnico','mcli-equipo-modelo':'tecnico','mcli-equipo-marca':'tecnico',
  'mcli-serie':'tecnico','mcli-ip':'tecnico','mcli-mac':'tecnico','mcli-olt-nombre':'tecnico',
  'mcli-olt-puerto':'tecnico','mcli-pppoe-user':'tecnico','mcli-pppoe-pass':'tecnico',
  'mcli-modo-equipo':'tecnico','mcli-vlan':'tecnico','mcli-tiene-ip-publica':'tecnico',
  'mcli-ip-publica':'tecnico','mcli-puertos-asignados':'tecnico',
  'mcli-torre':'tecnico','mcli-ap':'tecnico','mcli-senal-instalacion':'tecnico','mcli-necesita-nap':'tecnico',
  'mcli-estado':'estado',
  'mcli-obs':'observaciones',
};
let _permCamposCache = null;

async function _aplicarPermisosCampos(){
  if(!_permCamposCache){
    _permCamposCache = await api('/api/clientes/permisos_campos');
  }
  if(!_permCamposCache) return;
  const editables = _permCamposCache.bloques_editables || [];
  // admin/root: todo editable, no tocar nada
  if(_permCamposCache.rol === 'admin' || _permCamposCache.rol === 'root') return;
  Object.entries(_CAMPO_BLOQUE).forEach(([campoId, bloque])=>{
    const el = document.getElementById(campoId);
    if(!el) return;
    const puede = editables.includes(bloque);
    el.disabled = !puede;
    el.style.background = puede ? '' : 'var(--surf2)';
    el.style.cursor = puede ? '' : 'not-allowed';
    if(!puede) el.title = 'No tenés permiso para editar este campo';
  });
  // Aviso visual de qué puede editar
  const aviso = document.getElementById('mcli-perm-aviso');
  if(aviso){
    const nombres = {personales:'datos personales', comercial:'comercial/pagos', tecnico:'técnico/red', estado:'estado', observaciones:'observaciones'};
    aviso.textContent = '🔒 Tu rol (' + _permCamposCache.rol + ') puede editar: ' + editables.map(b=>nombres[b]||b).join(', ');
    aviso.style.display = 'block';
  }
}

async function _poblarCombosCliente(){
  // Combo agentes
  const agentes = await api('/api/usuarios/agentes');
  const sel = document.getElementById('mcli-agente');
  if(sel && agentes){
    const currentVal = sel.value;
    sel.innerHTML = '<option value="">— Sin asignar —</option>' +
      agentes.map(a => `<option value="${a.nombre}">${a.nombre} (${a.username})</option>`).join('');
    if(currentVal) sel.value = currentVal;
  }
  // Combo torres
  const torres = await api('/api/torres');
  const tSel = document.getElementById('mcli-torre');
  if(tSel && torres){
    const currentVal = tSel.value;
    tSel.innerHTML = '<option value="">— Sin torre —</option>' +
      torres.map(t => `<option value="${t.id}">${t.nombre}${t.localidad?' · '+t.localidad:''}</option>`).join('');
    if(currentVal) tSel.value = currentVal;
  }
}

function clearModalCliente(){
  ['mcli-id','mcli-nro','mcli-nombre','mcli-dni','mcli-email','mcli-dir','mcli-loc',
   'mcli-lat','mcli-lng','mcli-plan','mcli-precio','mcli-nap','mcli-agente',
   'mcli-equipo-modelo','mcli-equipo-marca','mcli-serie','mcli-ip','mcli-mac',
   'mcli-pppoe-user','mcli-pppoe-pass',
   'mcli-vlan','mcli-ip-publica','mcli-puertos-asignados',
   'mcli-olt-nombre','mcli-olt-puerto','mcli-fecha-alta','mcli-ultimo-pago','mcli-obs',
   'mcli-torre','mcli-ap','mcli-senal-instalacion']
  .forEach(id=>{const el=document.getElementById(id);if(el){el.value='';if(el.dataset)el.dataset.manual='0';}});
  document.getElementById('mcli-tipo').value='inalambrico';
  document.getElementById('mcli-estado').value='activo';
  // Reset teléfonos
  const tList = document.getElementById('mcli-tels-list');
  if(tList) tList.innerHTML = '';
  toggleFtthFields();
}

function toggleFtthFields(){
  const tipo=document.getElementById('mcli-tipo').value;
  const ftth = document.getElementById('ftth-fields');
  const inal = document.getElementById('inal-fields');
  if(ftth) ftth.style.display = tipo==='fibra' ? 'block' : 'none';
  if(inal) inal.style.display = tipo==='inalambrico' ? 'block' : 'none';
  // Mostrar checkbox necesita_nap solo para pte_calculo
  const estado = document.getElementById('mcli-estado')?.value;
  const nnapWrap = document.getElementById('mcli-necesita-nap-wrap');
  if(nnapWrap) nnapWrap.style.display = (estado==='pte_calculo')?'block':'none';
}

// ── Teléfonos múltiples ──
function _renderTelefonos(tels){
  const list = document.getElementById('mcli-tels-list');
  if(!list) return;
  // Si vienen 0, mostrar 2 vacíos por defecto
  if(!tels || tels.length === 0) tels = [{telefono:'',tipo:'movil'},{telefono:'',tipo:'movil'}];
  // Si viene 1, agregar otro vacío
  if(tels.length === 1) tels.push({telefono:'',tipo:'movil'});
  list.innerHTML = '';
  tels.forEach((t,i) => _appendTelefonoRow(t, i));
}

function _appendTelefonoRow(t, idx){
  const list = document.getElementById('mcli-tels-list');
  if(!list) return;
  const row = document.createElement('div');
  row.className = 'tel-row';
  row.style.cssText = 'display:flex;gap:.4rem;margin-bottom:.3rem;align-items:center';
  const isPrincipal = idx === 0;
  row.innerHTML = `
    <input type="text" class="tel-input" placeholder="${isPrincipal?'Principal':'Adicional'}" value="${(t?.telefono||'').replace(/"/g,'&quot;')}" style="flex:1">
    <select class="tel-tipo" style="width:auto">
      <option value="movil"${(t?.tipo==='movil')?' selected':''}>📱 Móvil</option>
      <option value="fijo"${(t?.tipo==='fijo')?' selected':''}>☎️ Fijo</option>
      <option value="laboral"${(t?.tipo==='laboral')?' selected':''}>💼 Laboral</option>
      <option value="otro"${(t?.tipo==='otro')?' selected':''}>📞 Otro</option>
    </select>
    ${idx>=2?'<button type="button" class="btn btn-rj btn-xs" onclick="this.parentElement.remove()" title="Quitar">−</button>':'<span style="width:24px"></span>'}
  `;
  list.appendChild(row);
}

function agregarTelefono(){
  const list = document.getElementById('mcli-tels-list');
  const idx = list.children.length;
  _appendTelefonoRow({telefono:'',tipo:'movil'}, idx);
}

function _readTelefonos(){
  const rows = document.querySelectorAll('#mcli-tels-list .tel-row');
  const out = [];
  rows.forEach(r => {
    const num = r.querySelector('.tel-input')?.value.trim();
    const tipo = r.querySelector('.tel-tipo')?.value || 'movil';
    if(num) out.push({telefono:num, tipo:tipo});
  });
  return out;
}

// ── Históricos ──
let _histTabActual = 'equipos';

async function showHistTab(tab, targetId){
  _histTabActual = tab;
  const id = document.getElementById('mcli-id').value;
  if(!id) return;
  const cont = document.getElementById(targetId || 'hist-tab-content');
  if(!cont) return;
  cont.innerHTML = '<div style="color:#888;padding:.4rem">Cargando...</div>';
  if(tab === 'equipos'){
    const rows = await api(`/api/clientes/${id}/equipos_historico`);
    if(!rows?.length){ cont.innerHTML = '<div style="color:#888">Sin histórico de equipos</div>'; return; }
    cont.innerHTML = `<table style="width:100%;font-size:.78rem;border-collapse:collapse">
      <thead><tr style="background:var(--card)"><th style="text-align:left;padding:.3rem">Serie</th><th style="text-align:left;padding:.3rem">Modelo</th><th style="text-align:left;padding:.3rem">IP</th><th style="text-align:left;padding:.3rem">Asignación</th><th style="text-align:left;padding:.3rem">Liberación</th><th style="text-align:left;padding:.3rem">Motivo</th></tr></thead>
      <tbody>${rows.map(r=>`<tr ${r.fecha_liberacion?'':'style="background:var(--card)"'}>
        <td style="padding:.3rem;font-family:monospace">${escHtml(r.equipo_serie)||'—'}</td>
        <td style="padding:.3rem">${escHtml(r.equipo_modelo)||'—'}</td>
        <td style="padding:.3rem;font-family:monospace">${escHtml(r.ip_asignada)||'—'}</td>
        <td style="padding:.3rem">${escHtml(r.fecha_asignacion)}</td>
        <td style="padding:.3rem">${r.fecha_liberacion?escHtml(r.fecha_liberacion):'<span style="color:#2e7d32;font-weight:700">ACTIVO</span>'}</td>
        <td style="padding:.3rem">${escHtml(r.motivo_liberacion)||'—'}</td>
      </tr>`).join('')}</tbody></table>`;
  } else if(tab === 'torre_ap'){
    const rows = await api(`/api/clientes/${id}/torre_ap_historico`);
    if(!rows?.length){ cont.innerHTML = '<div style="color:#888">Sin histórico de Torre/AP. Se registra al sondear el equipo.</div>'; return; }
    cont.innerHTML = `<table style="width:100%;font-size:.82rem;border-collapse:collapse">
      <thead><tr style="background:var(--card)">
        <th style="text-align:left;padding:.4rem">Fecha</th>
        <th style="text-align:left;padding:.4rem">SSID (AP)</th>
        <th style="text-align:left;padding:.4rem">AP MAC</th>
        <th style="text-align:left;padding:.4rem">Señal</th>
      </tr></thead>
      <tbody>${rows.map((r,i)=>`<tr ${i===0?'style="background:var(--card)"':''}>
        <td style="padding:.4rem;white-space:nowrap">${escHtml((r.fecha||'').slice(0,16))}</td>
        <td style="padding:.4rem;font-weight:600">${escHtml(r.ssid)||'—'}${i===0?' <span style="color:#2e7d32;font-size:.7rem">ACTUAL</span>':''}</td>
        <td style="padding:.4rem;font-family:monospace;font-size:.78rem">${escHtml(r.ap_mac)||'—'}</td>
        <td style="padding:.4rem">${r.signal!=null?escHtml(r.signal)+' dBm':'—'}</td>
      </tr>`).join('')}</tbody></table>
      <div style="font-size:.72rem;color:#999;margin-top:.4rem">Muestra los cambios de AP enlazado a lo largo del tiempo (el más reciente arriba).</div>`;
  } else if(tab === 'senales'){
    const rows = await api(`/api/clientes/${id}/senales`);
    if(!rows?.length){ cont.innerHTML = '<div style="color:#888">Sin registros de señal</div>'; return; }
    // Mini-gráfico ASCII + tabla
    const vals = rows.slice().reverse().map(r => parseFloat(r.valor_dbm));
    const min = Math.min(...vals), max = Math.max(...vals);
    const range = max - min || 1;
    const bars = vals.map(v => {
      const norm = (v - min) / range;
      const h = Math.round(norm * 30) + 4;
      const color = v < -28 ? '#dc3545' : v < -25 ? '#ff9800' : '#2e7d32';
      return `<div style="display:inline-block;width:14px;margin:0 1px;background:${color};height:${h}px;vertical-align:bottom" title="${v} dBm"></div>`;
    }).join('');
    cont.innerHTML = `
      <div style="background:var(--card);padding:.5rem;border-radius:4px;margin-bottom:.5rem">
        <div style="font-size:.72rem;color:#666;margin-bottom:.3rem">Evolución (más vieja → más reciente)</div>
        <div style="height:40px;display:flex;align-items:flex-end;gap:0">${bars}</div>
        <div style="font-size:.7rem;color:#888;margin-top:.2rem">Rango: ${min.toFixed(1)} a ${max.toFixed(1)} dBm</div>
      </div>
      <table style="width:100%;font-size:.78rem;border-collapse:collapse">
        <thead><tr style="background:var(--card)"><th style="text-align:left;padding:.3rem">Fecha</th><th style="text-align:left;padding:.3rem">Valor (dBm)</th><th style="text-align:left;padding:.3rem">Tipo</th><th style="text-align:left;padding:.3rem">Usuario</th><th style="text-align:left;padding:.3rem">Notas</th></tr></thead>
        <tbody>${rows.map(r=>{
          const v = parseFloat(r.valor_dbm);
          const cls = v < -28 ? 'color:#dc3545;font-weight:700' : v < -25 ? 'color:#ff9800;font-weight:700' : 'color:#2e7d32';
          return `<tr><td style="padding:.3rem">${escHtml(r.fecha)}</td><td style="padding:.3rem;font-family:monospace;${cls}">${escHtml(r.valor_dbm)}</td><td style="padding:.3rem">${escHtml(r.tipo)||'—'}</td><td style="padding:.3rem">${escHtml(r.usuario)||'—'}</td><td style="padding:.3rem">${escHtml(r.observaciones)}</td></tr>`;
        }).join('')}</tbody>
      </table>`;
  } else if(tab === 'completo'){
    const d = await api(`/api/clientes/${id}/historial_completo`);
    if(!d || !d.eventos?.length){ cont.innerHTML = '<div style="color:#888">Sin historial registrado para este cliente</div>'; return; }
    const ICONO = {instalacion:'🔧', servicio:'🛠️', trabajo_interior:'👷', cambio_abono:'💰'};
    const COLOR = {instalacion:'#2e7d32', servicio:'#1565c0', trabajo_interior:'#6a1b9a', cambio_abono:'#e65100'};
    cont.innerHTML = `<div style="position:relative;padding-left:.5rem">
      ${d.eventos.map(e=>{
        const ico = ICONO[e.tipo] || '•';
        const col = COLOR[e.tipo] || '#888';
        const fecha = (e.fecha||'').replace('T',' ').slice(0,16);
        return `<div style="display:flex;gap:.6rem;padding:.5rem 0;border-bottom:1px solid var(--brd)">
          <div style="font-size:1.1rem;flex-shrink:0">${ico}</div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;gap:.5rem;flex-wrap:wrap">
              <b style="color:${col};font-size:.82rem">${escHtml(e.titulo)}</b>
              <span style="font-size:.72rem;color:#999">${escHtml(fecha||'sin fecha')}</span>
            </div>
            <div style="font-size:.78rem;color:var(--txt2);margin-top:.1rem">${escHtml(e.detalle)}</div>
            ${e.tecnico && e.tecnico!=='—' ? `<div style="font-size:.72rem;color:#777;margin-top:.1rem">👤 ${escHtml(e.tecnico)}${e.estado?` · ${escHtml(e.estado)}`:''}</div>` : ''}
          </div>
        </div>`;
      }).join('')}
    </div>`;
  } else if(tab === 'pagos'){
    const d = await api(`/api/clientes/${id}`);
    const pagos = (d && d.pagos) || [];
    if(!pagos.length){ cont.innerHTML = '<div style="color:#888">Sin pagos registrados. Se sincronizan desde el ERP.</div>'; return; }
    const fmt = n => '$' + (Number(n)||0).toLocaleString('es-AR', {minimumFractionDigits:2});
    // Detectar si un pago está pendiente (por estado_pago o por el texto de la referencia)
    const esPendiente = p => {
      const e = (p.estado_pago || '').toLowerCase();
      if(e) return e.includes('pend') || e.includes('impag') || e.includes('deud');
      // Fallback: si no hay estado_pago, mirar la referencia
      return /pendiente|impago/i.test(p.referencia || '');
    };
    const pagado = pagos.filter(p=>!esPendiente(p)).reduce((s,p)=>s+(Number(p.monto)||0),0);
    const pendiente = pagos.filter(p=>esPendiente(p)).reduce((s,p)=>s+(Number(p.monto)||0),0);
    const nPend = pagos.filter(esPendiente).length;
    cont.innerHTML = `
      <div style="font-size:.78rem;color:var(--txt2);margin-bottom:.5rem;display:flex;gap:1rem;flex-wrap:wrap">
        <span>${pagos.length} recibo(s) · fuente: ERP</span>
        <span style="color:#2e7d32">Cobrado: <b>${fmt(pagado)}</b></span>
        ${nPend ? `<span style="color:#c62828">Pendiente: <b>${fmt(pendiente)}</b> (${nPend})</span>` : ''}
      </div>
      <table style="width:100%;font-size:.78rem;border-collapse:collapse">
        <thead><tr style="background:var(--card)">
          <th style="text-align:left;padding:.3rem">Fecha</th>
          <th style="text-align:right;padding:.3rem">Monto</th>
          <th style="text-align:left;padding:.3rem">Medio</th>
          <th style="text-align:left;padding:.3rem">Detalle</th>
        </tr></thead>
        <tbody>${pagos.map(p=>{
          const pend = esPendiente(p);
          const color = pend ? '#c62828' : '#2e7d32';
          return `<tr ${pend?'style="background:var(--card)"':''}>
          <td style="padding:.3rem">${(p.fecha||'').slice(0,10)}</td>
          <td style="padding:.3rem;text-align:right;font-weight:600;color:${color}">${fmt(p.monto)}${pend?' ⚠':''}</td>
          <td style="padding:.3rem">${p.medio||'—'}</td>
          <td style="padding:.3rem;color:#666">${p.observaciones||p.referencia||''}</td>
        </tr>`;
        }).join('')}</tbody>
      </table>`;
  } else if(tab === 'equipo'){
    const ip = document.getElementById('mcli-ip')?.value;
    let html = `<div style="margin-bottom:.6rem">
      <button class="btn btn-prim btn-sm" onclick="sondearEquipoActual()" ${!ip?'disabled title="El cliente no tiene IP"':''}>
        📡 Sondear equipo ahora${!ip?' (sin IP)':''}</button>
      <span style="font-size:.72rem;color:#999;margin-left:.5rem">Lee el equipo en vivo. Señal y AP quedan en sus pestañas.</span>
    </div>`;
    const rows = await api(`/api/clientes/${id}/chequeos`);
    if(!rows?.length){
      html += '<div style="color:#888">Sin chequeos registrados. Tocá "Sondear equipo" o esperá el sondeo automático diario.</div>';
    } else {
      html += rows.map((r,i)=>{
        const ultimo = i===0;
        // Cotejos legibles
        const macOk = r.mac_coincide===1;
        const modOk = r.modelo_coincide===1;
        const macTxt = r.observaciones?.includes('sin N')
          ? '<span style="color:#999">sin serie en sistema</span>'
          : (macOk ? '<span style="color:#2e7d32;font-weight:600">✓ MAC coincide con N° serie</span>'
                   : '<span style="color:#c62828;font-weight:600">⚠ MAC NO coincide</span>');
        const modTxt = modOk ? '<span style="color:#2e7d32;font-weight:600">✓ modelo coincide</span>'
          : (r.observaciones?.includes('Modelo: ⚠') ? '<span style="color:#c62828;font-weight:600">⚠ modelo NO coincide</span>' : '<span style="color:#999">sin modelo</span>');
        return `<div style="border:1px solid ${ultimo?'#90caf9':'var(--surf2)'};border-radius:8px;padding:.6rem .8rem;margin-bottom:.5rem;background:${ultimo?'var(--card)':'var(--card)'}">
          <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:.3rem;margin-bottom:.4rem">
            <b style="font-size:.85rem">${(r.fecha||'').slice(0,16)}${ultimo?' <span style="color:#1565c0;font-size:.72rem">último</span>':''}</b>
            <span style="font-size:.72rem;color:#888">${r.origen||''} · ${r.ip||''}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.3rem .8rem;font-size:.8rem">
            <div>📦 <b>Modelo:</b> ${r.device_model||'—'}</div>
            <div>🔧 <b>Firmware:</b> ${r.firmware||'—'}</div>
            <div>🔌 <b>LAN:</b> ${r.lan_estado||'—'}</div>
            <div>⏱ <b>Uptime:</b> ${r.uptime_txt||'—'}</div>
            <div style="grid-column:1/3">📡 <b>WLAN0 MAC:</b> <span style="font-family:monospace">${r.wlan0_mac||'—'}</span></div>
          </div>
          <div style="margin-top:.4rem;padding-top:.4rem;border-top:1px dashed var(--brd);font-size:.78rem;display:flex;gap:1rem;flex-wrap:wrap">
            ${macTxt} ${modTxt}
          </div>
        </div>`;
      }).join('');
    }
    cont.innerHTML = html;
  } else if(tab === 'tendencia'){
    const d = await api(`/api/clientes/${id}/tendencia_senal`);
    if(!d || !d.puntos?.length){
      cont.innerHTML = '<div style="color:#888">Sin datos de tendencia. Se acumulan con cada sondeo del equipo.</div>';
      return;
    }
    const pts = d.puntos.filter(p=>p.signal!=null);
    if(pts.length < 2){
      cont.innerHTML = '<div style="color:#888">Hace falta al menos 2 sondeos para ver la tendencia. Seguí sondeando el equipo.</div>';
      return;
    }
    // Banner de tendencia
    let banner = '';
    if(d.tendencia){
      const t = d.tendencia;
      const cfg = {
        empeorando: {col:'#c62828', ico:'📉', txt:`Señal empeorando (${t.delta} dBm)`},
        mejorando: {col:'#2e7d32', ico:'📈', txt:`Señal mejorando (+${t.delta} dBm)`},
        estable: {col:'#1565c0', ico:'➡️', txt:'Señal estable'},
      }[t.estado];
      banner = `<div style="background:${cfg.col}15;border-left:4px solid ${cfg.col};padding:.5rem .8rem;border-radius:4px;margin-bottom:.8rem;font-size:.85rem">
        ${cfg.ico} <b style="color:${cfg.col}">${cfg.txt}</b> — comparando primeros vs últimos sondeos</div>`;
    }
    // Gráfico SVG de señal en el tiempo
    const W=560, H=180, pad=40;
    const sigs = pts.map(p=>p.signal);
    const min = Math.min(...sigs, -90), max = Math.max(...sigs, -40);
    const range = max - min || 1;
    const x = i => pad + (i/(pts.length-1))*(W-pad-10);
    const y = v => pad/2 + (1-(v-min)/range)*(H-pad);
    const linePts = pts.map((p,i)=>`${x(i)},${y(p.signal)}`).join(' ');
    // Líneas de referencia (-65 buena, -75 límite)
    const refLine = (val,col,lbl)=> (val>=min&&val<=max) ?
      `<line x1="${pad}" y1="${y(val)}" x2="${W-10}" y2="${y(val)}" stroke="${col}" stroke-dasharray="3,3" opacity=".5"/>
       <text x="${W-8}" y="${y(val)-2}" font-size="9" fill="${col}">${lbl}</text>` : '';
    const dots = pts.map((p,i)=>{
      const col = p.signal>-65?'#2e7d32':p.signal>-75?'#e65100':'#c62828';
      return `<circle cx="${x(i)}" cy="${y(p.signal)}" r="3" fill="${col}"><title>${(p.fecha||'').slice(0,16)}: ${p.signal} dBm, CCQ ${p.ccq||'?'}%</title></circle>`;
    }).join('');
    cont.innerHTML = `${banner}
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;background:var(--card);border-radius:8px">
        ${refLine(-65,'#2e7d32','-65 buena')}
        ${refLine(-75,'#c62828','-75 límite')}
        <polyline points="${linePts}" fill="none" stroke="#1565c0" stroke-width="2"/>
        ${dots}
        <text x="${pad}" y="${H-4}" font-size="9" fill="#999">${(pts[0].fecha||'').slice(0,10)}</text>
        <text x="${W-60}" y="${H-4}" font-size="9" fill="#999">${(pts[pts.length-1].fecha||'').slice(0,10)}</text>
      </svg>
      <div style="font-size:.75rem;color:#999;margin-top:.4rem">${pts.length} sondeos · cada punto es un chequeo · pasá el mouse para ver detalle</div>`;
  }
}

async function sondearEquipoActual(){
  const id = document.getElementById('mcli-id').value;
  if(!id) return;
  const cont = document.getElementById('hist-tab-content');
  cont.innerHTML = '<div style="color:#888;padding:.4rem">📡 Conectando al equipo... (puede tardar unos segundos)</div>';
  const r = await api(`/api/clientes/${id}/sondear_equipo`, 'POST', {});
  if(r && r.ok){
    const d = r.datos, c = r.cotejo;
    let msg = `✓ Equipo leído: ${d.device_model}, señal ${d.signal} dBm, CCQ ${d.ccq}%`;
    toast(msg, 'ok');
    // Avisar si hay discrepancia en el cotejo
    if(c.mac_estado?.includes('NO coincide') || c.modelo_estado?.includes('NO coincide')){
      alert(`⚠ Atención — discrepancia detectada:\n\nMAC: ${c.mac_estado}\nModelo: ${c.modelo_estado}\n\nVerificá que el equipo cargado en el sistema sea el correcto.`);
    }
    showHistTab('equipo'); // refrescar la tabla
  } else {
    const msg = r?.error || 'No hubo respuesta del servidor (revisá que el equipo responda y que ubiquiti_poller.py esté en el servidor)';
    cont.innerHTML = `<div style="color:#c62828;padding:.5rem">❌ No se pudo sondear: ${msg}</div>
      <button class="btn btn-gray btn-sm" onclick="showHistTab('equipo')">Volver</button>`;
  }
}

async function agregarSenalNueva(){
  const id = document.getElementById('mcli-id').value;
  if(!id){alert('Primero guardá el cliente'); return;}
  const valor = await pedirDato('Valor de señal en dBm (ej: -23.5):');
  if(!valor) return;
  const tipo = await pedirDato('Tipo de medición:\n- rutina (default)\n- queja\n- instalacion\n- mantenimiento','rutina') || 'rutina';
  const obs = await pedirDato('Observaciones (opcional):','') || '';
  const r = await api(`/api/clientes/${id}/senales`, 'POST', {valor_dbm:valor, tipo, observaciones:obs});
  if(r?.ok){
    showHistTab('senales');
  } else {
    alert('Error: ' + (r?.error || 'no se pudo registrar'));
  }
}

async function saveCliente(_force, comoVenta){
  const id=document.getElementById('mcli-id').value;
  const tipoSvc = document.getElementById('mcli-tipo').value;
  const data={
    nro_cliente:document.getElementById('mcli-nro').value.trim(),
    nombre:document.getElementById('mcli-nombre').value,
    dni:document.getElementById('mcli-dni').value,
    email:document.getElementById('mcli-email').value,
    direccion:document.getElementById('mcli-dir').value,
    localidad:document.getElementById('mcli-loc').value,
    lat:parseDMS(document.getElementById('mcli-lat').value),
    lng:parseDMS(document.getElementById('mcli-lng').value),
    tipo_servicio:tipoSvc,
    estado:document.getElementById('mcli-estado').value,
    plan:document.getElementById('mcli-plan').value,
    precio:parseFloat(document.getElementById('mcli-precio').value)||0,
    agente:document.getElementById('mcli-agente').value,
    equipo_modelo:document.getElementById('mcli-equipo-modelo').value,
    equipo_marca:document.getElementById('mcli-equipo-marca').value,
    equipo_serie:document.getElementById('mcli-serie').value,
    ip_asignada:document.getElementById('mcli-ip').value,
    mac_address:document.getElementById('mcli-mac').value,
    pppoe_usuario:document.getElementById('mcli-pppoe-user').value,
    modo_equipo:(document.getElementById('mcli-modo-equipo')||{}).value||null,
    vlan:(document.getElementById('mcli-vlan')||{}).value||null,
    tiene_ip_publica:(document.getElementById('mcli-tiene-ip-publica')||{}).checked?1:0,
    ip_publica:(document.getElementById('mcli-ip-publica')||{}).value||null,
    puertos_asignados:(document.getElementById('mcli-puertos-asignados')||{}).value||null,
    pppoe_clave:document.getElementById('mcli-pppoe-pass').value,
    fecha_alta:document.getElementById('mcli-fecha-alta').value,
    ultimo_pago:document.getElementById('mcli-ultimo-pago').value,
    observaciones:document.getElementById('mcli-obs').value,
    necesita_nap: document.getElementById('mcli-necesita-nap')?.checked ? 1 : 0,
    telefonos: _readTelefonos()
  };
  // Si se pidió "Crear como venta nueva", forzar estado=venta
  // y dispara workflow de instalaciones automáticamente
  if(comoVenta && !id){
    data.estado = 'venta';
  }
  // Campos según tipo
  if(tipoSvc === 'fibra'){
    data.nap = document.getElementById('mcli-nap').value;
    data.olt_nombre = document.getElementById('mcli-olt-nombre').value;
    data.olt_puerto = document.getElementById('mcli-olt-puerto').value;
    data.torre_id = null;
    data.ap_nombre = '';
  } else {
    data.torre_id = document.getElementById('mcli-torre')?.value || null;
    data.ap_nombre = document.getElementById('mcli-ap')?.value || '';
    data.nap = '';
    data.olt_nombre = '';
    data.olt_puerto = '';
  }
  // Campo legacy telefono: poner el primer teléfono ahí también para compat
  data.telefono = (data.telefonos[0]?.telefono) || '';
  
  if(_force) data.force=true;
  if(!data.nombre.trim()){alert('El nombre es obligatorio');return;}
  // ── Freno preventivo: NAP llena o inexistente, ANTES de guardar ──
  // Solo si la NAP cambió respecto de la original (no molesta al editar otros campos).
  const napElegida = (data.nap||'').trim();
  if(napElegida && napElegida.toUpperCase() !== (window._napOriginal||'').trim().toUpperCase()){
    try{
      const oc = await api(`/api/naps/ocupacion?nombre=${encodeURIComponent(napElegida)}`);
      if(oc && !oc.existe){
        if(!confirm(`⚠ La NAP "${napElegida}" NO existe en el sistema.\n¿Es un error de tipeo? ¿Guardar igual?`)) return;
      } else if(oc && oc.libre <= 0){
        if(!confirm(`🔴 La NAP ${napElegida} está LLENA (${oc.total}/${oc.capacidad}).\nAsignar este cliente la deja sobrepasada y el técnico puede viajar en vano.\n¿Asignar de todos modos?`)) return;
      }
    }catch(e){}
  }
  const url=id?`/api/clientes/${id}`:'/api/clientes';
  const method=id?'PUT':'POST';
  const r=await api(url,method,data);
  if(r?.ok||r?.id){
    // Asignaciones automáticas (IP / PPPoE al pasar a Activación Pendiente)
    if(r.asignaciones && r.asignaciones.length){
      alert('✅ Asignación automática:\n\n' + r.asignaciones.join('\n'));
    }
    // Advertencias del backend (IP/serie duplicada, etc.)
    if(r.advertencias && r.advertencias.length){
      alert('Guardado, pero con advertencias:\n\n' + r.advertencias.join('\n'));
    }
    // Si en alta de FTTH se ingresó señal, registrarla
    const cid = id || r.id;
    const senal = document.getElementById('mcli-senal-instalacion')?.value.trim();
    if(!id && senal && tipoSvc === 'fibra'){
      await api(`/api/clientes/${cid}/senales`, 'POST', {
        valor_dbm: senal, tipo: 'instalacion', observaciones: 'Señal al alta'
      });
    }
    closeModal('modal-cliente');
    loadClientes();
    loadLocalidades();
    // Si fue "Crear como venta nueva", llevar al usuario al módulo de Activación Pendiente
    if(comoVenta && !id){
      setTimeout(() => {
        if(typeof navGo === 'function') navGo('activacion-pendiente');
      }, 200);
    }
    return;
  }
  if(r?.error==='duplicado'){
    mostrarConflictoDuplicado(r);
    return;
  }
  alert('Error al guardar' + (r?.error?': '+r.error:''));
}

// ── Manejo de conflicto por duplicado (MAC/IP) ──

let _conflictoActual=null;

function mostrarConflictoDuplicado(info){
  _conflictoActual=info;
  const labels = {
    'equipo_serie':'MAC/Número de serie',
    'ip_asignada':'IP',
    'nro_cliente':'N° de Cliente'
  };
  const campoLabel = labels[info.campo] || info.campo;
  document.getElementById('dup-mensaje').innerHTML =
    `El <b>${escHtml(campoLabel)}</b> <code style="background:var(--tint-ambar);padding:.1rem .35rem;border-radius:3px">${escHtml(info.valor)}</code> ya está asignado a otro cliente.`;
  document.getElementById('dup-conflicto-nombre').textContent = info.conflicto_nombre || '(sin nombre)';
  document.getElementById('dup-conflicto-id').textContent = `ID #${info.conflicto_id}`;
  const btnForzar=document.getElementById('dup-btn-forzar');
  btnForzar.style.display = info.puede_forzar ? 'inline-block' : 'none';
  document.getElementById('modal-duplicado').style.display='flex';
}

function abrirFichaConflicto(){
  if(!_conflictoActual) return;
  const id=_conflictoActual.conflicto_id;
  closeModal('modal-duplicado');
  closeModal('modal-cliente');
  openModalCliente(id);
}

async function forzarGuardadoCliente(){
  if(!_conflictoActual) return;
  if(!await confirmar(`¿Confirmás forzar el guardado a pesar del duplicado con "${_conflictoActual.conflicto_nombre}"?\n\nEsta acción quedará registrada en el historial.`)) return;
  closeModal('modal-duplicado');
  await saveCliente(true);
}

// ── MAPA ──
// Coordenadas: DMS → Decimal

const COLOR_CLI={
  activo:'#2e7d32',
  suspendido:'#e65100',
  pte_rescision:'#c62828',
  rescision:'#4a0e0e',
  baja:'#9e9e9e',
  pte_instalacion:'#1565c0',
  pte_cambio:'#00897b',
  pte_calculo:'#f9a825',
  pte_suspension:'#ef6c00',
  borrador:'#78909c',
  calculado:'#0097a7',
  sin_contrato:'#8e24aa',
  venta:'#9c27b0',
  activacion_pendiente:'#1976d2',
  instalacion_pendiente:'#ff9800',
};

const COLOR_TIPO={fibra:'#1565c0',inalambrico:'#6a1b9a'};

async function reloadMapaClientes(){
  if(!mapaInited) return;
  removeLayer('clientes');
  removeLayer('heat');
  // Leer estados tildados (checkboxes)
  const estados = Array.from(document.querySelectorAll('.map-estado-chk:checked')).map(c=>c.value);
  const tipo = document.querySelector('input[name="map-tipo-r"]:checked')?.value || '';
  const svcPend = document.getElementById('map-svc-pendiente')?.checked ? '1' : '';
  // Actualizar contador del botón
  const cnt = document.getElementById('map-filtros-count');
  if(cnt) cnt.textContent = estados.length;
  const params = new URLSearchParams();
  if(estados.length) params.set('estado', estados.join(','));
  if(tipo) params.set('tipo', tipo);
  if(svcPend) params.set('con_servicio_pendiente', svcPend);
  const data = await api(`/api/clientes/mapa?${params.toString()}`);
  if(!data) return;
  mapaCliData=data;
  if(mapaChips.clientes) renderMapaClientes(data);
  if(mapaChips.heat) showHeatMap();
}

function toggleFiltrosMapa(){
  const p = document.getElementById('map-filtros-panel');
  if(p) p.style.display = p.style.display==='none' ? 'block' : 'none';
}

function _esWorkflowEstado(estado){
  return ['venta','activacion_pendiente','instalacion_pendiente'].includes(estado);
}

function _crearDivIcon(html, sz){
  return L.divIcon({className:'',html:html,iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]});
}

function _iconoEstado(c, color){
  // Necesita NAP → estrella dorada grande
  if(c.necesita_nap) return _crearDivIcon(`<div style="font-size:22px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.5))">⭐</div>`,26);
  const e = c.estado;
  // Suspendido → cuadrado naranja con pausa
  if(e==='suspendido') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:3px;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:12px;box-shadow:0 2px 5px rgba(0,0,0,.4)">⏸</div>`,22);
  // Pte rescisión → rombo rojo
  if(e==='pte_rescision') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);width:18px;height:18px;transform:rotate(45deg);display:flex;align-items:center;justify-content:center;box-shadow:0 2px 5px rgba(0,0,0,.4)"><span style="transform:rotate(-45deg);font-size:10px">⚠</span></div>`,22);
  // Pte instalación → cuadrado azul con herramienta
  if(e==='pte_instalacion') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:13px;box-shadow:0 2px 5px rgba(0,0,0,.4)">🔧</div>`,24);
  // Pte cálculo → triángulo amarillo
  if(e==='pte_calculo') return _crearDivIcon(`<div style="width:0;height:0;border-left:12px solid transparent;border-right:12px solid transparent;border-bottom:22px solid ${color};filter:drop-shadow(0 2px 3px rgba(0,0,0,.4))"></div>`,24);
  // Borrador → círculo gris chico con lápiz
  if(e==='borrador') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;box-shadow:0 2px 4px rgba(0,0,0,.3)">📝</div>`,20);
  // Rescindido → X roja
  if(e==='rescision') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:50%;width:18px;height:18px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;box-shadow:0 2px 4px rgba(0,0,0,.3)">✕</div>`,18);
  // Workflow
  if(e==='venta') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:5px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:13px;box-shadow:0 2px 5px rgba(0,0,0,.4)">🆕</div>`,24);
  if(e==='activacion_pendiente') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:5px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:13px;box-shadow:0 2px 5px rgba(0,0,0,.4)">⚙️</div>`,24);
  if(e==='instalacion_pendiente') return _crearDivIcon(`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:5px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:13px;box-shadow:0 2px 5px rgba(0,0,0,.4)">🛠️</div>`,24);
  return null; // usa circleMarker
}

function renderMapaClientes(data){
  removeLayer('clientes');
  const markers=[];
  data.forEach(c=>{
    if(!c.lat||!c.lng) return;
    const color=COLOR_CLI[c.estado]||'#546e7a';
    const tipoColor=c.tipo_servicio==='fibra'?'#1565c0':'#6a1b9a';
    const afectado = c.afectado_por_incidencia;
    const svcPend = c.tiene_servicio_pendiente;

    const popupHtml=`<b>${c.nombre}</b>${c.nro_cliente?' <small>('+c.nro_cliente+')</small>':''}<br>
      <span class="badge b-${c.estado}" style="font-size:.7rem">${estadoLabel(c.estado)}</span> · ${c.tipo_servicio||''}<br>
      ${afectado?'<span style="color:#c62828;font-weight:700">🔴 '+c.motivo_afectacion+'</span><br>':''}
      ${svcPend?'<span style="color:#e65100;font-weight:700">🔧 Servicio técnico pendiente</span><br>':''}
      ${c.nap?'NAP: '+c.nap+'<br>':''}
      ${c.plan?'Plan: '+c.plan+'<br>':''}
      ${c.direccion?c.direccion+', '+(c.localidad||'')+'<br>':''}
      ${c.telefono?'📞 '+c.telefono+'<br>':''}
      ${c.necesita_nap?'<b style="color:#e65100">⭐ Necesita NAP</b><br>':''}
      ${c.estado==='pte_calculo'?'<button class="btn btn-xs" style="margin-top:.3rem;background:#f9a825;color:var(--txt)" onclick="verCobertura('+c.lat+','+c.lng+',this)">📐 Ver cobertura</button><br>':''}
      <button class="btn btn-prim btn-xs" style="margin-top:.3rem" onclick="openModalCliente(${c.id})">Ver detalle</button>`;

    const icon = _iconoEstado(c, color);
    let marker;
    if(svcPend && !afectado){
      // Cliente con servicio técnico pendiente: anillo naranja con llave
      const sz = 22;
      const svcIcon = L.divIcon({className:'',
        html:`<div style="position:relative;width:${sz}px;height:${sz}px">
          <div style="position:absolute;top:-4px;left:-4px;width:${sz+8}px;height:${sz+8}px;border:3px solid #e65100;border-radius:50%"></div>
          <div style="background:${color};border:2px solid #e65100;border-radius:50%;width:${sz}px;height:${sz}px;display:flex;align-items:center;justify-content:center;font-size:12px">🔧</div>
        </div>`,
        iconSize:[sz,sz], iconAnchor:[sz/2,sz/2]
      });
      marker = L.marker([c.lat, c.lng], {icon:svcIcon}).bindPopup(popupHtml);
    } else if(icon){
      marker = L.marker([c.lat, c.lng], {icon}).bindPopup(popupHtml);
    } else if(afectado){
      // Cliente afectado por incidencia: círculo con anillo rojo pulsante
      const sz = 20;
      const afIcon = L.divIcon({className:'',
        html:`<div style="position:relative;width:${sz}px;height:${sz}px">
          <div style="position:absolute;top:-4px;left:-4px;width:${sz+8}px;height:${sz+8}px;border:3px solid #ff0000;border-radius:50%;animation:pulse-inc 1.5s infinite"></div>
          <div style="background:${color};border:2px solid ${tipoColor};border-radius:50%;width:${sz}px;height:${sz}px"></div>
        </div>`,
        iconSize:[sz,sz], iconAnchor:[sz/2,sz/2]
      });
      marker = L.marker([c.lat, c.lng], {icon:afIcon}).bindPopup(popupHtml);
    } else {
      marker=L.circleMarker([c.lat,c.lng],{
        radius:6, fillColor:color, color:tipoColor, weight:2, opacity:1, fillOpacity:.85
      }).bindPopup(popupHtml);
    }
    markers.push(marker);
  });
  mapaLayers.clientes=L.layerGroup(markers).addTo(map);
}

// ── Posible cliente: evaluar cobertura ──
let _posibleClienteMarker = null;

// Construye el HTML del popup con el resultado de cobertura
function _popupCobertura(lat, lng, cob){
  let html = `<b>📍 Posible cliente</b><br>Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}<br><hr>`;
  if(cob){
    if(cob.naps_cercanos?.length){
      html += `<b>📦 NAPs cercanos (150m):</b><br>`;
      cob.naps_cercanos.forEach(n=>{
        const color = n.lleno ? '#c62828' : '#2e7d32';
        html += `<span style="color:${color}">• ${n.nombre} — ${n.distancia_m}m — ${n.ocupacion}/${n.capacidad} ${n.lleno?'<b>LLENO</b>':n.libre+' libre(s)'}</span><br>`;
      });
    } else {
      html += '<span style="color:#e65100">📦 Sin NAPs en 150m</span><br>';
    }
    if(cob.torres_cercanas?.length){
      html += `<b>📡 Torres cercanas:</b><br>`;
      cob.torres_cercanas.slice(0,5).forEach(t=>{ html += `• ${t.nombre} (${t.distancia_m}m) — ${t.tipo}<br>`; });
    } else {
      html += '<span style="color:#c62828">📡 Sin torres cercanas</span><br>';
    }
    html += `<hr><b>Cobertura:</b> ${cob.tiene_cobertura?'✅ Viable':'❌ Sin cobertura'}<br>`;
    html += `<b>Tipo sugerido:</b> ${cob.tipo_sugerido||'N/A'}`;
  }
  html += `<br><button class="btn btn-prim btn-xs" style="margin-top:.4rem" onclick="map.removeLayer(_posibleClienteMarker);_posibleClienteMarker=null">Quitar</button>`;
  return html;
}

// Coloca (o mueve) el marcador en lat/lng, centra el mapa y calcula la cobertura
async function _colocarPosibleCliente(lat, lng, centrar){
  if(_posibleClienteMarker) map.removeLayer(_posibleClienteMarker);
  const icon = L.divIcon({className:'',
    html:'<div style="background:#ff5722;color:#fff;border:3px solid var(--brd);border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-size:16px;box-shadow:0 3px 8px rgba(0,0,0,.5);animation:pulse 1.5s infinite">👤</div>',
    iconSize:[30,30], iconAnchor:[15,15]
  });
  _posibleClienteMarker = L.marker([lat, lng], {icon, draggable:true}).addTo(map);
  if(centrar) map.setView([lat, lng], 17);
  const cob = await api(`/api/cobertura?lat=${lat}&lng=${lng}`);
  _posibleClienteMarker.bindPopup(_popupCobertura(lat, lng, cob)).openPopup();
  // Al arrastrar el punto, recalcula la cobertura en la nueva posición
  _posibleClienteMarker.on('dragend', async function(){
    const p = _posibleClienteMarker.getLatLng();
    const c2 = await api(`/api/cobertura?lat=${p.lat}&lng=${p.lng}`);
    _posibleClienteMarker.setPopupContent(_popupCobertura(p.lat, p.lng, c2)).openPopup();
  });
}

// Modo "click en el mapa" (lo de siempre)
function activarModoPosibleCliente(){
  toast('Hacé click en el mapa para colocar un posible cliente (o usá "pegar coordenadas")', 'info');
  map.once('click', function(e){
    _colocarPosibleCliente(e.latlng.lat, e.latlng.lng, false);
  });
}

// Parsea coordenadas en formato DECIMAL (-31.7325, -60.5295) o
// GMS / grados-minutos-segundos (31°43'57"S, 60°31'46"W). Devuelve {lat,lng} o null.
function _parsearCoords(txt){
  txt = (txt||'').trim();
  if(!txt) return null;
  const esGMS = /[°'"′″]|[NSEWnsew]/.test(txt);
  if(esGMS){
    // grados ° minutos ' segundos " hemisferio
    const re = /(\d+(?:\.\d+)?)\s*°\s*(?:(\d+(?:\.\d+)?)\s*['′]\s*)?(?:(\d+(?:\.\d+)?)\s*["″]\s*)?\s*([NSEWnsew])/g;
    const matches = [...txt.matchAll(re)];
    if(matches.length < 2) return null;
    const toDec = (m)=>{
      const g = parseFloat(m[1]||0), min = parseFloat(m[2]||0), seg = parseFloat(m[3]||0);
      let dec = g + min/60 + seg/3600;
      const hemi = (m[4]||'').toUpperCase();
      if(hemi === 'S' || hemi === 'W') dec = -dec;
      return dec;
    };
    const lat = toDec(matches[0]), lng = toDec(matches[1]);
    if(isNaN(lat)||isNaN(lng)||Math.abs(lat)>90||Math.abs(lng)>180) return null;
    return {lat, lng};
  }
  // Decimal: separador coma, espacio o ;
  const partes = txt.replace(/;/g,',').split(/[, ]+/).filter(Boolean);
  if(partes.length < 2) return null;
  const lat = parseFloat(partes[0]), lng = parseFloat(partes[1]);
  if(isNaN(lat)||isNaN(lng)||Math.abs(lat)>90||Math.abs(lng)>180) return null;
  return {lat, lng};
}

// Modo "pegar coordenadas": acepta decimal y grados-minutos-segundos de Google Maps
async function posibleClientePorCoords(){
  const txt = await pedirDato(
    'Pegá las coordenadas (como se copian de Google Maps):\n\n' +
    'Decimal:  -31.7325, -60.5295\n' +
    'O GMS:    31°43\'57"S, 60°31\'46"W',
    '', {titulo:'Posible cliente por coordenadas'});
  if(!txt) return;
  const c = _parsearCoords(txt);
  if(!c){
    alert('No pude interpretar esas coordenadas.\n\nFormatos válidos:\n• Decimal: -31.7325, -60.5295\n• GMS: 31°43\'57"S, 60°31\'46"W');
    return;
  }
  await _colocarPosibleCliente(c.lat, c.lng, true);
}

async function showFtthPotenciales(){
  removeLayer('ftth_pot');
  const data=await api('/api/clientes/migracion_ftth');
  if(!data) return;
  const markers=data.map(c=>{
    if(!c.lat||!c.lng) return null;
    const icon=L.divIcon({className:'',html:`<div style="background:#ff6f00;color:#fff;border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:.7rem;border:2px solid var(--brd);box-shadow:0 2px 6px rgba(0,0,0,.3)">🔄</div>`,iconSize:[20,20],iconAnchor:[10,10]});
    return L.marker([c.lat,c.lng],{icon}).bindPopup(`<b>${c.nombre}</b><br>Potencial migración a FTTH<br>${c.vecinos_fibra} vecino(s) de fibra`);
  }).filter(Boolean);
  mapaLayers.ftth_pot=L.layerGroup(markers).addTo(map);
}

// ── Capa de Torres en el mapa (con enlaces padre-hijo) ──
async function showTorresOnMap(){
  removeLayer('torres');
  const data = await api('/api/torres/mapa_red');
  if(!data || !data.length) return;
  const grupo = L.layerGroup();
  data.forEach(t=>{
    if(!t.lat || !t.lng) return;
    // Color según estado/incidencia
    let color = '#1565c0';
    if(t.incidencia_activa) color = '#c62828';
    else if(t.afectada_por_incidencia || t.requiere_revision) color = '#e65100';
    else if(t.estado === 'inactiva') color = '#757575';
    const icon = L.divIcon({className:'',
      html:`<div style="background:${color};color:#fff;border:2px solid var(--brd);border-radius:6px;width:26px;height:26px;display:flex;align-items:center;justify-content:center;font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,.4)">🗼</div>`,
      iconSize:[26,26], iconAnchor:[13,13]});
    const inc = t.incidencia_activa ? '<br><span style="color:#c62828">⚠ Con incidencia activa</span>' : '';
    const hijos = t.hijos ? `<br>${t.hijos} torre(s) hija(s)` : '';
    const m = L.marker([t.lat, t.lng], {icon}).bindPopup(
      `<b>🗼 ${t.nombre||'Torre'}</b><br>Tipo: ${t.tipo||'—'} · Estado: ${t.estado||'—'}${hijos}${inc}`);
    grupo.addLayer(m);
    // Dibujar enlace a la torre padre (línea)
    if(t.padre_lat && t.padre_lng){
      const linea = L.polyline([[t.lat, t.lng], [t.padre_lat, t.padre_lng]],
        {color: t.afectada_por_incidencia?'#e65100':'#1565c0', weight:2, opacity:.6, dashArray:'5,5'});
      grupo.addLayer(linea);
    }
  });
  grupo.addTo(map);
  mapaLayers.torres = grupo;
}

// ── Capa de OLTs en el mapa ──
async function showOltsOnMap(){
  removeLayer('olts');
  const data = await api('/api/olts');
  if(!data || !data.length) return;
  const grupo = L.layerGroup();
  data.forEach(o=>{
    if(!o.lat || !o.lng) return;
    const icon = L.divIcon({className:'',
      html:`<div style="background:#00897b;color:#fff;border:2px solid var(--brd);border-radius:6px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:12px;box-shadow:0 2px 6px rgba(0,0,0,.4)">🔌</div>`,
      iconSize:[24,24], iconAnchor:[12,12]});
    const puertos = o.puertos_usados!=null ? `<br>Puertos: ${o.puertos_usados}/${o.puertos_total||'?'}` : '';
    grupo.addLayer(L.marker([o.lat, o.lng], {icon}).bindPopup(
      `<b>🔌 ${o.nombre||'OLT'}</b><br>${o.localidad||''}${puertos}`));
  });
  grupo.addTo(map);
  mapaLayers.olts = grupo;
}

async function searchClienteForSvc(){
  const q=document.getElementById('msvc-cli-q').value;
  const drop=document.getElementById('msvc-cli-drop');
  if(q.length<2){drop.style.display='none';return;}
  const data=await api(`/api/clientes/buscar?q=${encodeURIComponent(q)}`);
  if(!data?.length){drop.style.display='none';return;}
  drop.innerHTML=data.map(c=>`<div class="item" style="padding:.4rem .7rem;cursor:pointer;border-bottom:1px solid var(--brd)" onclick="selectSvcCliente(${c.id},'${escJs(c.nombre)}')">
    <div style="font-weight:600;font-size:.82rem">${escHtml(c.nombre)}</div>
    <div style="font-size:.72rem;color:var(--txt2)">${escHtml(c.direccion)} ${escHtml(c.localidad)}</div>
  </div>`).join('');
  drop.style.display='block';
}

function selectSvcCliente(id,nombre){
  document.getElementById('msvc-cli-id').value=id;
  document.getElementById('msvc-cli-q').value=nombre;
  document.getElementById('msvc-cli-drop').style.display='none';
}

async function verCobertura(lat, lng, btn){
  btn.textContent = 'Calculando...';
  btn.disabled = true;
  const c = await api(`/api/cobertura?lat=${lat}&lng=${lng}`);
  if(!c) { btn.textContent = 'Error'; return; }
  let html = '<div style="margin-top:.3rem;font-size:.8rem;border-top:1px solid var(--brd);padding-top:.3rem">';
  if(c.naps_cercanos?.length){
    html += '<b>📦 NAPs (150m):</b><br>';
    c.naps_cercanos.forEach(n=>{
      const color = n.lleno ? '#c62828' : '#2e7d32';
      html += `<span style="color:${color}">• ${n.nombre} — ${n.distancia_m}m — ${n.ocupacion}/${n.capacidad} ${n.lleno?'LLENO':n.libre+' libre(s)'}</span><br>`;
    });
  } else html += '<span style="color:#e65100">Sin NAPs en 150m</span><br>';
  if(c.torres_cercanas?.length){
    html += '<b>📡 Torres:</b><br>';
    c.torres_cercanas.slice(0,3).forEach(t=>{ html += `• ${t.nombre} (${t.distancia_m}m)<br>`; });
  }
  html += `<b>Tipo sugerido:</b> ${c.tipo_sugerido}</div>`;
  btn.outerHTML = html;
}


// ── Exportación de clientes (KMZ / PDF / CSV) — solo admin ──
function abrirExportarClientes(){
  // Construir la query con los filtros activos
  const q = document.getElementById('cli-q').value;
  const estado = document.getElementById('cli-estado').value;
  const tipo = document.getElementById('cli-tipo').value;
  const loc = document.getElementById('cli-loc').value;
  const params = new URLSearchParams();
  if(q) params.set('q', q);
  if(estado) params.set('estado', estado);
  if(tipo) params.set('tipo', tipo);
  if(loc) params.set('localidad', loc);
  const base = params.toString();

  // Resumen de filtros para el diálogo
  const filtros = [];
  if(estado) filtros.push('estado: '+document.getElementById('cli-estado').selectedOptions[0].text);
  if(tipo) filtros.push('tipo: '+document.getElementById('cli-tipo').selectedOptions[0].text);
  if(loc) filtros.push('localidad: '+loc);
  if(q) filtros.push('búsqueda: '+q);
  const resumen = filtros.length ? filtros.join(' · ') : 'todos los clientes (sin filtro)';

  const html = `
    <div style="padding:.5rem 0">
      <div style="font-size:.85rem;color:var(--txt2);margin-bottom:.8rem">
        Vas a exportar: <b>${resumen}</b>
      </div>
      <div style="display:grid;gap:.5rem">
        <button class="btn btn-prim" onclick="descargarExport('kmz','${base}')">
          🌍 KMZ (Google Earth) — ubicación, nombre, N° y abono</button>
        <button class="btn btn-prim" onclick="descargarExport('pdf','${base}')">
          📄 PDF — listado completo con todos los datos</button>
        <button class="btn btn-prim" onclick="descargarExport('csv','${base}')">
          📊 CSV (Excel) — todos los datos para planilla</button>
      </div>
    </div>`;
  _modalSimple('Exportar clientes', html);
}

function descargarExport(formato, base){
  const url = `/api/clientes/exportar?formato=${formato}${base?'&'+base:''}`;
  window.open(url, '_blank');
  // cerrar el modal simple si existe
  const m = document.getElementById('modal-simple-gen');
  if(m) m.remove();
}

// Modal genérico mínimo (si no existe uno en el sistema)
function _modalSimple(titulo, htmlContenido){
  let m = document.getElementById('modal-simple-gen');
  if(m) m.remove();
  m = document.createElement('div');
  m.id = 'modal-simple-gen';
  m.className = 'modal-overlay';
  m.style = 'display:flex;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center';
  m.innerHTML = `<div class="modal-box" style="background:var(--card);border-radius:10px;max-width:440px;width:92vw;box-shadow:0 8px 30px rgba(0,0,0,.3)">
    <div class="modal-hd" style="display:flex;justify-content:space-between;align-items:center;padding:.8rem 1rem;border-bottom:1px solid var(--brd)">
      <b>${titulo}</b><button onclick="document.getElementById('modal-simple-gen').remove()" style="border:none;background:none;font-size:1.3rem;cursor:pointer">×</button>
    </div>
    <div style="padding:1rem">${htmlContenido}</div>
  </div>`;
  m.onclick = (e)=>{ if(e.target===m) m.remove(); };
  document.body.appendChild(m);
}

// ── Ocupación de la NAP elegida, en vivo (al salir del campo) ──
async function verNapOcupacion(){
  const inp = document.getElementById('mcli-nap');
  const est = document.getElementById('mcli-nap-estado');
  if(!inp || !est) return;
  const nombre = (inp.value||'').trim();
  if(!nombre){ est.textContent=''; return; }
  est.textContent = '…'; est.style.color = '#999';
  const oc = await api(`/api/naps/ocupacion?nombre=${encodeURIComponent(nombre)}`);
  if(!oc){ est.textContent=''; return; }
  if(!oc.existe){
    est.textContent = '✗ no existe (¿tipeo?)'; est.style.color = '#c62828';
  } else if(oc.libre <= 0){
    est.textContent = `🔴 LLENA ${oc.total}/${oc.capacidad}`; est.style.color = '#c62828';
  } else if(oc.libre === 1){
    est.textContent = `⚠ ${oc.total}/${oc.capacidad} (último puerto)`; est.style.color = '#e65100';
  } else {
    est.textContent = `✓ ${oc.total}/${oc.capacidad} (${oc.libre} libres)`; est.style.color = '#2e7d32';
  }
}

// ── Señal óptica en vivo + histórico en la ficha del cliente ──
async function _cargarSenalCliente(cid){
  const panel = document.getElementById('mcli-senal-live');
  const cont = document.getElementById('mcli-senal-contenido');
  if(!panel || !cont) return;
  panel.style.display = 'none';
  let s = null;
  try { s = await api(`/api/clientes/${cid}/senal`); } catch(e){ return; }
  if(!s){ return; }  // sin señal registrada → no mostrar el panel
  panel.style.display = 'block';
  const rx = s.rx_power;
  const rc = _rxColorFicha(rx);
  const rxTxt = rx != null ? rx.toFixed(2)+' dBm' : 'sin señal';
  cont.innerHTML = `
    <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
      <div><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${rc.c};margin-right:.4rem"></span>
        RX: <b style="color:${rc.c};font-size:1.05rem">${rxTxt}</b> <span style="font-size:.72rem;color:var(--txt2)">(${rc.txt})</span></div>
      <div style="font-size:.82rem;color:var(--txt2)">TX: ${s.tx_power!=null?s.tx_power.toFixed(2)+' dBm':'—'}</div>
      <div style="font-size:.82rem;color:var(--txt2)">${s.temperatura!=null?s.temperatura.toFixed(1)+'°C':''}</div>
      <div style="font-size:.72rem;color:var(--txt2);margin-left:auto">${s.olt_nombre||''} · ${s.last_check?s.last_check.slice(5,16):''}</div>
    </div>
    ${_serialFichaHtml(s)}
    <div id="mcli-senal-hist" style="margin-top:.5rem"></div>`;
  // Histórico (mini gráfico)
  try {
    const hist = await api(`/api/clientes/${cid}/senal_hist`);
    if(hist && hist.length >= 2) _dibujarHistSenal(hist);
  } catch(e){}
}

function _rxColorFicha(rx){
  if(rx === null || rx === undefined) return {c:'#E0605F', txt:'sin señal'};
  // Demasiada luz es tan problema como poca: por encima de -8 dBm el receptor
  // de la ONU se satura y termina dañándose. Antes esto caía en "buena" porque
  // la única condición era rx >= -23, y un cliente a -1.5 dBm se veía perfecto.
  if(rx > -8)  return {c:'#E0605F', txt:'saturada — falta atenuación'};
  if(rx >= -23) return {c:'#4FB3AA', txt:'buena'};
  if(rx >= -26) return {c:'#E0A838', txt:'aceptable'};
  if(rx >= -29) return {c:'#E08063', txt:'baja'};
  return {c:'#E0605F', txt:'crítica'};
}

function _dibujarHistSenal(hist){
  const cont = document.getElementById('mcli-senal-hist');
  if(!cont) return;
  const vals = hist.map(h=>h.rx_power).filter(v=>v!=null);
  if(vals.length < 2) return;
  const W=320, H=60, pad=4;
  const min = Math.min(...vals, -30), max = Math.max(...vals, -15);
  const rango = (max-min) || 1;
  const pts = vals.map((v,i)=>{
    const x = pad + i*((W-pad*2)/(vals.length-1));
    const y = (H-pad) - ((v-min)/rango)*(H-pad*2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const ultimo = vals[vals.length-1];
  const rc = _rxColorFicha(ultimo);
  cont.innerHTML = `<div style="font-size:.68rem;color:var(--txt2);margin-bottom:.2rem">Histórico RX (últimas ${vals.length} lecturas)</div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;height:${H}px">
      <line x1="${pad}" y1="${(H-pad)-((-29-min)/rango)*(H-pad*2)}" x2="${W-pad}" y2="${(H-pad)-((-29-min)/rango)*(H-pad*2)}" stroke="#E0605F" stroke-width="0.5" stroke-dasharray="3,3" opacity="0.5"/>
      <polyline points="${pts}" fill="none" stroke="${rc.c}" stroke-width="1.5"/>
    </svg>`;
}


function _serialFichaHtml(s){
  if(!s.serial_onu) return '';
  let badge = '';
  if(s.serial_coincide === 'ok') badge = '<span style="color:#4FB3AA">✓ coincide con el equipo registrado</span>';
  else if(s.serial_coincide === 'difiere') badge = `<span style="color:#E0605F">⚠ NO coincide (registrado: ${s.equipo_serie||'—'})</span>`;
  else if(s.serial_coincide === 'sin_registro') badge = '<span style="color:#E0A838">el cliente no tiene serial cargado</span>';
  return `<div style="font-size:.76rem;margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--brd)">
    Serial ONU (reportado): <b style="font-family:monospace">${s.serial_onu}</b> &nbsp; ${badge}</div>`;
}

/* ════════ Modal cliente por pestañas (Fase 1) ════════ */
function mcliTab(pane){
  document.querySelectorAll('#modal-cliente .mcli-tab').forEach(b=>
    b.classList.toggle('active', b.dataset.pane===pane));
  document.querySelectorAll('#modal-cliente .mcli-pane').forEach(p=>
    p.style.display = (p.dataset.pane===pane)?'block':'none');
  const id = document.getElementById('mcli-id').value;
  if(!id) return;  // en alta nueva no hay históricos
  // Cargar el contenido de cada pestaña la primera vez que se abre
  if(pane==='admin'){
    const c=document.getElementById('mcli-admin-cont');
    if(c && !c.dataset.cargado){ c.dataset.cargado='1'; showHistTab('pagos','mcli-admin-cont'); }
  } else if(pane==='tecnico'){
    const c=document.getElementById('mcli-tec-cont');
    if(c && !c.dataset.cargado){ c.dataset.cargado='1'; showHistTab('equipo','mcli-tec-cont'); }
  } else if(pane==='general'){
    const c=document.getElementById('mcli-gen-hist');
    if(c && !c.dataset.cargado){ c.dataset.cargado='1'; showHistTab('completo','mcli-gen-hist'); }
  } else if(pane==='monitoreo'){
    const g=document.getElementById('mon-grafico');
    if(g && !g.dataset.cargado){ cargarMonitoreoCliente(168); }
  } else if(pane==='reclamos'){
    const c=document.getElementById('mcli-rec-cont');
    if(c && !c.dataset.cargado && typeof cargarReclamosCliente==='function'){
      c.dataset.cargado='1'; cargarReclamosCliente();
    }
  }
}

/* Ver el cliente en el mapa (usa las coordenadas ya cargadas en el form) */
function verClienteEnMapa(){
  const lat = parseFloat(document.getElementById('mcli-lat').value);
  const lng = parseFloat(document.getElementById('mcli-lng').value);
  const nombre = document.getElementById('mcli-nombre').value || 'Cliente';
  if(isNaN(lat) || isNaN(lng)){
    alert('Este cliente no tiene coordenadas cargadas.');
    return;
  }
  closeModal('modal-cliente');
  navGo('mapa');
  // esperar a que el mapa exista y centrar
  let intentos = 0;
  const t = setInterval(()=>{
    intentos++;
    if(typeof map!=='undefined' && map){
      clearInterval(t);
      map.setView([lat,lng], 17);
      const mk = L.marker([lat,lng]).addTo(map);
      mk.bindPopup('<b>'+nombre+'</b>').openPopup();
      setTimeout(()=>{ if(map.hasLayer(mk)) map.removeLayer(mk); }, 15000);
    }
    if(intentos>40) clearInterval(t);
  }, 150);
}

/* Construir la URL de gestión: http://IP  o  http://IP:PUERTO */
function _urlGestion(){
  const ip = (document.getElementById('mcli-ip').value||'').trim();
  if(!ip) return null;
  const puerto = (document.getElementById('mcli-ip-puerto').value||'').trim();
  return 'http://' + ip + (puerto ? ':'+puerto : '');
}
function abrirIpGestion(){
  const url = _urlGestion();
  if(!url){ alert('No hay IP de gestión cargada.'); return; }
  window.open(url, '_blank', 'noopener');
}
function copiarIpGestion(){
  const ip = (document.getElementById('mcli-ip').value||'').trim();
  if(!ip){ alert('No hay IP de gestión cargada.'); return; }
  navigator.clipboard.writeText(ip).then(
    ()=>{ if(typeof toast==='function') toast('IP copiada: '+ip); else console.log('IP copiada'); },
    ()=>alert('No se pudo copiar.')
  );
}

/* Monitoreo: gráfica histórica de señal óptica (reusa onu_senal_hist) */
async function cargarMonitoreoCliente(horas){
  const cid = document.getElementById('mcli-id').value;
  const tipo = document.getElementById('mcli-tipo').value;
  const g = document.getElementById('mon-grafico');
  const avisoInal = document.getElementById('mon-inalambrico-aviso');
  if(!g) return;
  g.dataset.cargado = '1';
  // marcar el botón de período activo
  document.querySelectorAll('#mon-periodo-btns .mon-per').forEach(b=>{
    b.classList.toggle('btn-prim', b.dataset.h==String(horas));
    b.classList.toggle('btn-gray', b.dataset.h!=String(horas));
  });
  const titulo = document.getElementById('mon-titulo');
  const btnPeriodo = document.getElementById('mon-periodo-btns');
  if(tipo==='inalambrico'){
    // Señal INALÁMBRICA histórica (RSSI/dBm), mismo lugar y concepto visual
    if(titulo) titulo.textContent = '📡 Señal inalámbrica histórica';
    if(btnPeriodo) btnPeriodo.style.display='none';   // /senales trae las últimas N, sin filtro horario
    if(avisoInal) avisoInal.style.display='none';
    g.innerHTML = '<div style="color:var(--txt2);text-align:center;padding:1rem">Cargando…</div>';
    let rows=null;
    try { rows = await api(`/api/clientes/${cid}/senales`); } catch(e){}
    if(!rows || !rows.length){
      g.innerHTML = '<div style="color:var(--txt2);text-align:center;padding:1.2rem">Sin registros de señal inalámbrica.<br><span style="font-size:.75rem">Se registran al sondear el equipo o manualmente. El monitoreo automático (SNR/CCQ) depende del poller de Ubiquiti.</span></div>';
      return;
    }
    // rows viene nuevo→viejo; para el gráfico lo damos viejo→nuevo
    const puntos = rows.slice().reverse().map(r=>({rx_power: parseFloat(r.valor_dbm), fecha: r.fecha, obs: r.observaciones}));
    g.innerHTML = _sparkInalambrico(puntos);
    return;
  }
  // FTTH: señal óptica histórica (RX/TX)
  if(titulo) titulo.textContent = '📈 Señal óptica histórica';
  if(btnPeriodo) btnPeriodo.style.display='flex';
  if(avisoInal) avisoInal.style.display='none';
  g.innerHTML = '<div style="color:var(--txt2);text-align:center;padding:1rem">Cargando…</div>';
  let d = null;
  try { d = await api(`/api/clientes/${cid}/senal_hist?horas=${horas}`); } catch(e){}
  if(!d || !d.puntos || !d.puntos.length){
    g.innerHTML = '<div style="color:var(--txt2);text-align:center;padding:1.5rem">Sin registros de señal en este período.</div>';
    return;
  }
  g.innerHTML = _sparkSenal(d.puntos);
}

/* Mini-gráfica SVG de la señal (sin librerías) */
function _sparkSenal(puntos){
  const W=520, H=170, pad=28;
  const rx = puntos.map(p=>p.rx_power).filter(v=>v!=null);
  if(!rx.length) return '<div style="color:var(--txt2);padding:1rem">Sin datos de RX.</div>';
  let min=Math.min(...rx), max=Math.max(...rx);
  if(max-min<2){ min-=1; max+=1; }
  const n=puntos.length;
  const x=i=>pad+(i/(n-1||1))*(W-pad*2);
  const y=v=>pad+(1-(v-min)/(max-min))*(H-pad*2);
  const col=v=>v>=-23?'#4FD1A5':v>=-26?'#4FB3AA':v>=-29?'#E8B04B':'#F2607A';
  let path='', pts='';
  puntos.forEach((p,i)=>{
    if(p.rx_power==null) return;
    const X=x(i).toFixed(1), Y=y(p.rx_power).toFixed(1);
    path += (path?'L':'M')+X+' '+Y+' ';
    pts += `<circle cx="${X}" cy="${Y}" r="2.5" fill="${col(p.rx_power)}"><title>${p.fecha||''}: ${p.rx_power} dBm</title></circle>`;
  });
  // líneas de umbral
  const umbral=(v,c,txt)=>{ if(v<min||v>max) return ''; const Y=y(v).toFixed(1);
    return `<line x1="${pad}" y1="${Y}" x2="${W-pad}" y2="${Y}" stroke="${c}" stroke-dasharray="3 3" opacity=".4"/>
            <text x="${W-pad+2}" y="${Y}" font-size="9" fill="${c}" dominant-baseline="middle">${txt}</text>`; };
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:var(--noc-up);border:1px solid var(--noc-line-soft);border-radius:6px">
    ${umbral(-23,'#4FD1A5','-23')}${umbral(-26,'#4FB3AA','-26')}${umbral(-29,'#F2607A','-29')}
    <text x="4" y="${pad}" font-size="9" fill="#8FA6BF">${max.toFixed(1)}</text>
    <text x="4" y="${H-pad+4}" font-size="9" fill="#8FA6BF">${min.toFixed(1)}</text>
    <path d="${path}" fill="none" stroke="#5B9BD5" stroke-width="1.5"/>${pts}
  </svg>
  <div style="font-size:.72rem;color:var(--txt2);text-align:center;margin-top:.3rem">${n} lecturas · RX en dBm</div>`;
}

/* Gráfica de señal inalámbrica histórica (RSSI en dBm; umbrales de WISP) */
function _sparkInalambrico(puntos){
  const W=520, H=170, pad=28;
  const vals = puntos.map(p=>p.rx_power).filter(v=>!isNaN(v));
  if(!vals.length) return '<div style="color:var(--txt2);padding:1rem">Sin datos de señal.</div>';
  let min=Math.min(...vals), max=Math.max(...vals);
  if(max-min<4){ min-=2; max+=2; }
  const n=puntos.length;
  const x=i=>pad+(i/(n-1||1))*(W-pad*2);
  const y=v=>pad+(1-(v-min)/(max-min))*(H-pad*2);
  // Umbrales típicos de enlace inalámbrico: óptimo ≥ -65, aceptable ≥ -75, malo < -80
  const col=v=>v>=-65?'#4FD1A5':v>=-75?'#E8B04B':'#F2607A';
  let path='', pts='';
  puntos.forEach((p,i)=>{
    if(isNaN(p.rx_power)) return;
    const X=x(i).toFixed(1), Y=y(p.rx_power).toFixed(1);
    path += (path?'L':'M')+X+' '+Y+' ';
    const t = (p.fecha||'').slice(0,16) + ': ' + p.rx_power + ' dBm' + (p.obs?(' · '+p.obs):'');
    pts += `<circle cx="${X}" cy="${Y}" r="2.5" fill="${col(p.rx_power)}"><title>${t}</title></circle>`;
  });
  const umbral=(v,c,txt)=>{ if(v<min||v>max) return ''; const Y=y(v).toFixed(1);
    return `<line x1="${pad}" y1="${Y}" x2="${W-pad}" y2="${Y}" stroke="${c}" stroke-dasharray="3 3" opacity=".4"/>
            <text x="${W-pad+2}" y="${Y}" font-size="9" fill="${c}" dominant-baseline="middle">${txt}</text>`; };
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:var(--noc-up);border:1px solid var(--noc-line-soft);border-radius:6px">
    ${umbral(-65,'#4FD1A5','-65')}${umbral(-75,'#E8B04B','-75')}${umbral(-80,'#F2607A','-80')}
    <text x="4" y="${pad}" font-size="9" fill="#8FA6BF">${max.toFixed(0)}</text>
    <text x="4" y="${H-pad+4}" font-size="9" fill="#8FA6BF">${min.toFixed(0)}</text>
    <path d="${path}" fill="none" stroke="#9676F1" stroke-width="1.5"/>${pts}
  </svg>
  <div style="font-size:.72rem;color:var(--txt2);text-align:center;margin-top:.3rem">${n} lecturas · RSSI en dBm · óptimo ≥ −65</div>`;
}


// ── Red avanzada del cliente (IP pública / puertos / modo / VLAN) ──
function mcliToggleIpPublica(){
  const chk = document.getElementById('mcli-tiene-ip-publica');
  const box = document.getElementById('mcli-ip-publica-fields');
  if(box) box.style.display = (chk && chk.checked) ? 'block' : 'none';
}

/* ========================================================
   nav.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

let _modulosSistema = null;
async function cargarModulosSistema(){
  if(_modulosSistema === null){
    _modulosSistema = await api('/api/sistema/modulos') || {};
    // Ocultar del menú los módulos deshabilitados en esta instalación
    for(const [mod, hab] of Object.entries(_modulosSistema)){
      if(!hab){
        document.querySelectorAll(`.nav-links a[onclick*="'${mod}'"], .nav-drawer a[onclick*="'${mod}'"]`)
          .forEach(a=>a.style.display='none');
      }
    }
  }
  return _modulosSistema;
}

function navGo(page, el){
  // Módulo deshabilitado en esta instalación (comercialización modular)
  if(_modulosSistema && _modulosSistema[page] === 0){
    alert(`Este módulo no está habilitado en esta instalación.`);
    return;
  }
  // Verificar permisos de módulo para todos los usuarios no-admin
  const isAdmin = currentUser.rol === 'admin' || currentUser.rol === 'root';
  if(!isAdmin && typeof _modAccesible === 'function' && !_modAccesible(page)){
    alert(`⛔ No tenés permisos para acceder al módulo "${page}".\n\nSi creés que es un error, hablá con un administrador.`);
    return;
  }

  // Desactivar todos
  document.querySelectorAll('.page,.page-map').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-links a, .nav-drawer a').forEach(a=>a.classList.remove('active'));

  // Registro de uso (fire-and-forget: un fallo acá jamás afecta la navegación)
  try{
    fetch('/api/uso/registrar', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({seccion: page})}).catch(()=>{});
  }catch(e){}

  // Salir del mapa apaga el modo reubicar: su aviso es fijo en pantalla y
  // seguiría visible sobre otra sección.
  if(page!=='mapa' && typeof _modoReubicarNap !== 'undefined' && _modoReubicarNap){
    toggleReubicarNaps();
  }

  // Activar página
  const pg=document.getElementById('page-'+page);
  if(pg) pg.classList.add('active');

  // Marcar link activo — desktop y drawer
  document.querySelectorAll(`.nav-links a[onclick*="'${page}'"], .nav-drawer a[onclick*="'${page}'"]`)
    .forEach(a=>a.classList.add('active'));
  if(el) el.classList.add('active');

  // Cargar contenido de la página
  if(page==='mapa') initMapa();
  else if(page==='dashboard') loadDash();
  else if(page==='clientes') { if(typeof cli2Init==='function') cli2Init(); }
  else if(page==='naps') loadNaps();
  else if(page==='gestion-ips') { if(typeof loadGestionIPs==='function') loadGestionIPs(); }
  else if(page==='aps') { if(typeof loadAPs==='function') loadAPs(); }
  else if(page==='mikrotik') { if(typeof loadMikrotik==='function') loadMikrotik(); }
  else if(page==='enlaces-alertas') { if(typeof loadEnlacesAlertas==='function') loadEnlacesAlertas(); }
  else if(page==='onu-alertas') { if(typeof loadOnuAlertas==='function') loadOnuAlertas(); }
  else if(page==='torres-enlaces') { if(typeof loadTorresEnlaces==='function') loadTorresEnlaces(); }
  else if(page==='enlaces-snmp') { if(typeof cargarEnlaces==='function') cargarEnlaces(); }
  else if(page==='perfiles-radio') { if(typeof cargarPerfiles==='function') cargarPerfiles(); }
  else if(page==='capacidad-aps') { if(typeof cargarCapacidad==='function') cargarCapacidad(); }
  else if(page==='cobertura-mapa') { if(typeof abrirCoberturaMapa==='function') abrirCoberturaMapa(); }
  else if(page==='servicios') loadServicios();
  else if(page==='ftth') loadOlts();
  else if(page==='ftth-capacidad') { if(typeof cargarFtthCapacidad==='function') cargarFtthCapacidad(); }
  else if(page==='incidencias') loadIncidencias();
  else if(page==='stock'){ loadStockAvanzado(); if(typeof loadStock==='function') loadStock(); }
  else if(page==='bajas') loadBajas();
  else if(page==='abonos') loadAbonos();
  else if(page==='historial') loadHistorial();
  else if(page==='usuarios'){ loadUsuarios(); if(typeof loadUsoSistema==='function') loadUsoSistema(); }
  else if(page==='rrhh') loadRRHH();
  else if(page==='guardias') loadGuardias();
  else if(page==='informes') loadInformes();
  else if(page==='contabilidad') loadContabilidad();
  else if(page==='tareas') loadTareas();
  else if(page==='torres') loadTorres();
  else if(page==='monitoreo') loadMonitoreo();
  else if(page==='reclamos'){ loadReclamos(); if(typeof loadAnaliticaReclamos==='function') loadAnaliticaReclamos(); }
  else if(page==='antiguedad'){ if(typeof loadAntiguedad==='function') loadAntiguedad(); }
  else if(page==='agenda') {
    const hoy=new Date().toISOString().slice(0,10);
    const en7=new Date(Date.now()+7*86400000).toISOString().slice(0,10);
    const d=document.getElementById('ag-desde'); if(d&&!d.value) d.value=hoy;
    const h=document.getElementById('ag-hasta'); if(h&&!h.value) h.value=en7;
    loadAgenda();
    api('/api/tecnicos').then(tecs=>{
      const sel=document.getElementById('ag-tecnico');
      if(sel&&sel.options.length<=1)(tecs||[]).forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=t;sel.appendChild(o);});
    });
  }
  else if(page==='config') { loadConfig(); if(typeof renderModulosSistema==='function') renderModulosSistema();
                             if(typeof loadCatalogosReclamos==='function') loadCatalogosReclamos(); }
  else if(page==='activacion-pendiente') loadActivacionPendiente();
  else if(page==='instalacion-pendiente') loadInstalacionPendiente();
  else if(page==='stats-service') loadStatsService();
  else if(page==='sync') { if(typeof activarSyncPanel==='function') activarSyncPanel(); }
  else if(page==='finanzas') { if(typeof loadFinanzas==='function') loadFinanzas(); }
  else if(page==='ftth_plan') { if(typeof loadFtthPlanning==='function') loadFtthPlanning(); }
  else { if(typeof desactivarSyncPanel==='function') desactivarSyncPanel(); }
  // Detener timer del panel sync cuando se sale
  if(page !== 'sync' && typeof desactivarSyncPanel==='function') desactivarSyncPanel();
}

// Alias para compatibilidad con código anterior

function nav(page, el){ navGo(page, el); }

// ── DROPDOWNS de grupos (sprint v8.2: position:fixed + posicionamiento dinámico) ──
function toggleNavGroup(ev, name){
  if(ev) ev.stopPropagation();
  const g = document.querySelector(`.nav-group[data-group="${name}"]`);
  if(!g) return;
  // Acordeón: alterna este grupo (no cierra los demás)
  g.classList.toggle('open');
}

function closeNavGroups(){
  // En sidebar no cerramos al navegar (queda abierto el grupo activo)
}

function toggleDrawerSection(el){
  const section = el.parentElement;
  if(!section) return;
  section.classList.toggle('open');
}

// Sincronizar el estado activo del grupo padre cuando navGo se ejecuta:
// si la página activa es una sub de un grupo, marcar el grupo como activo
const _pageToGroup = {
  'naps':'fibra', 'ftth':'fibra', 'ftth-capacidad':'fibra', 'incidencias':'fibra',
  'onu-alertas':'fibra', 'gestion-ips':'fibra',
  'aps':'inalambrico', 'torres-enlaces':'inalambrico', 'enlaces-alertas':'inalambrico',
  'enlaces-snmp':'inalambrico', 'perfiles-radio':'inalambrico', 'capacidad-aps':'inalambrico', 'cobertura-mapa':'inalambrico',
  'servicios':'servicios', 'activacion-pendiente':'servicios',
  'instalacion-pendiente':'servicios', 'agenda':'servicios', 'stats-service':'servicios',
  'torres':'inalambrico', 'monitoreo':'inalambrico', 'mikrotik':'inalambrico',
  'bajas':'administracion', 'abonos':'administracion', 'stock':'administracion',
  'finanzas':'administracion', 'contabilidad':'administracion', 'informes':'administracion',
  'ftth_plan':'fibra',
  'sync':'configuracion', 'historial':'configuracion', 'usuarios':'configuracion',
  'rrhh':'configuracion', 'config':'configuracion',
};

function _syncNavGroupActive(page){
  document.querySelectorAll('.nav-group').forEach(g => g.classList.remove('has-active'));
  const groupName = _pageToGroup[page];
  if(groupName){
    const g = document.querySelector(`.nav-group[data-group="${groupName}"]`);
    if(g) g.classList.add('has-active');
  }
}

// Wrap navGo for syncing group active state
(function(){
  const origNavGo = window.navGo;
  window.navGo = function(page, el){
    origNavGo(page, el);
    _syncNavGroupActive(page);
  };
})();

function openDrawer(){
  document.getElementById('nav-drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
  document.body.style.overflow='hidden';
}

function closeDrawer(){
  document.getElementById('nav-drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
  document.body.style.overflow='';
}

async function loadNotifBadge(){
  const d=await api('/api/dashboard');
  if(!d) return;
  const cnt=d.notificaciones?.length||0;
  const badge=document.getElementById('notif-cnt');
  if(cnt>0){badge.textContent=cnt>9?'9+':cnt;badge.style.display='flex';}
  else badge.style.display='none';
}

async function toggleNotif(){
  await api('/api/notificaciones/leer','POST');
  document.getElementById('notif-cnt').style.display='none';
}

async function openModalServicio(id=null, clienteId=null, clienteNombre=null, tipoPresel=null){
  ['msvc-id','msvc-cli-id','msvc-tecnico','msvc-obs','msvc-desc','msvc-costo'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('msvc-cli-q').value='';
  document.getElementById('msvc-estado').value='pendiente';
  document.getElementById('msvc-prioridad').value='normal';
  document.getElementById('msvc-tipo').value=tipoPresel||'reparacion_inalambrico';
  document.getElementById('svc-costo-row').style.display='none';
  if(clienteId){
    document.getElementById('msvc-cli-id').value=clienteId;
    document.getElementById('msvc-cli-q').value=clienteNombre||`Cliente #${clienteId}`;
  }
  if(id){
    document.getElementById('msvc-title').textContent='Editar Orden';
    const d=await api(`/api/servicios`);
    const s=(d||[]).find(x=>x.id===id);
    if(s){
      document.getElementById('msvc-id').value=s.id;
      document.getElementById('msvc-cli-id').value=s.cliente_id||'';
      document.getElementById('msvc-cli-q').value=s.cliente_nombre||'';
      document.getElementById('msvc-tipo').value=s.tipo||'';
      document.getElementById('msvc-tecnico').value=s.tecnico||'';
      document.getElementById('msvc-prioridad').value=s.prioridad||'normal';
      document.getElementById('msvc-estado').value=s.estado||'pendiente';
      document.getElementById('msvc-costo').value=s.costo||0;
      document.getElementById('msvc-desc').value=s.descripcion||'';
      document.getElementById('msvc-obs').value=s.observaciones||'';
      document.getElementById('svc-costo-row').style.display=s.tiene_costo?'grid':'none';
      // precargar diagnóstico/solución después de cargar catálogos
      setTimeout(()=>{
        const d=document.getElementById('msvc-diagnostico'), so=document.getElementById('msvc-solucion');
        if(d) d.value=s.diagnostico||'';
        if(so) so.value=s.solucion_aplicada||'';
      },100);
    }
  } else {
    document.getElementById('msvc-title').textContent='Nueva Orden de Servicio';
  }
  svcTipoChange();
  await cargarCatalogosServicio(id ? null : '');
  // Materiales: solo en edición (se adjuntan a una orden existente)
  const matPanel=document.getElementById('msvc-materiales');
  if(matPanel){
    if(id){ matPanel.style.display='block'; cargarMaterialesServicio(id); }
    else { matPanel.style.display='none'; const l=document.getElementById('msvc-mat-list'); if(l) l.innerHTML=''; }
  }
  document.getElementById('modal-servicio').style.display='flex';
}

// ── Materiales consumidos en un servicio (Fase 5) ──
async function cargarMaterialesServicio(sid){
  // poblar el selector con el inventario a granel disponible
  const inv = await api('/api/stock/inventario');
  const sel = document.getElementById('msvc-mat-sel');
  if(sel && Array.isArray(inv)){
    sel.innerHTML = inv.map(i=>`<option value="${i.id}">${i.nombre} (${i.cantidad} ${i.unidad||'u'})</option>`).join('')
      || '<option value="">— Sin inventario cargado —</option>';
  }
  // listar lo ya consumido
  const mats = await api(`/api/servicios/${sid}/materiales`);
  const cont = document.getElementById('msvc-mat-list');
  if(!cont) return;
  if(!Array.isArray(mats) || !mats.length){
    cont.innerHTML = '<div style="font-size:.78rem;color:var(--txt2)">Sin materiales registrados en esta orden.</div>';
    return;
  }
  cont.innerHTML = mats.map(m=>`<div style="display:flex;align-items:center;gap:.5rem;padding:.3rem .5rem;background:var(--bg2);border-radius:6px;margin-bottom:.3rem;font-size:.82rem">
    <span style="flex:1">${m.material||m.descripcion||'material'}</span>
    <b>${m.cantidad} ${m.unidad||'u'}</b>
    <button type="button" class="btn btn-rj btn-xs" title="Devolver al stock" onclick="quitarMaterialServicio(${m.id})">✕</button>
  </div>`).join('');
}

async function agregarMaterialServicio(){
  const sid = document.getElementById('msvc-id').value;
  if(!sid){ alert('Guardá la orden antes de cargar materiales'); return; }
  const iid = document.getElementById('msvc-mat-sel').value;
  const cant = parseInt(document.getElementById('msvc-mat-cant').value)||0;
  if(!iid || cant<=0){ alert('Elegí un material y una cantidad válida'); return; }
  const r = await api(`/api/servicios/${sid}/materiales`,'POST',{items:[{inventario_id:parseInt(iid),cantidad:cant}]});
  if(r && r.ok){
    document.getElementById('msvc-mat-cant').value=1;
    cargarMaterialesServicio(sid);
    if(typeof toast==='function') toast('Material descontado del stock','ok');
  } else {
    alert(r?.error || 'No se pudo registrar el material');
  }
}

async function quitarMaterialServicio(mid){
  if(typeof confirmar==='function' && !await confirmar('¿Devolver este material al stock?')) return;
  const sid = document.getElementById('msvc-id').value;
  const r = await api(`/api/servicios/materiales/${mid}`,'DELETE');
  if(r && r.ok){ cargarMaterialesServicio(sid); }
  else alert(r?.error || 'No se pudo quitar');
}

async function cargarCatalogosServicio(preDiag, preSol){
  const [diags, sols] = await Promise.all([
    api('/api/catalogo/diagnostico'),
    api('/api/catalogo/solucion'),
  ]);
  const selD = document.getElementById('msvc-diagnostico');
  const selS = document.getElementById('msvc-solucion');
  if(selD && diags){
    selD.innerHTML = '<option value="">— Seleccionar —</option>' +
      diags.map(d=>`<option value="${d.nombre}">${d.nombre}</option>`).join('');
  }
  if(selS && sols){
    selS.innerHTML = '<option value="">— Seleccionar —</option>' +
      sols.map(s=>`<option value="${s.nombre}">${s.nombre}</option>`).join('');
  }
}

// ── Materiales consumidos en una orden de servicio (Fase 5) ──
async function cargarMaterialesServicio(sid){
  // Poblar el select con el inventario a granel disponible
  const inv = await api('/api/stock/inventario');
  const sel = document.getElementById('msvc-mat-sel');
  if(sel && inv){
    sel.innerHTML = (inv||[]).map(i=>
      `<option value="${i.id}">${i.nombre} (${i.cantidad} ${i.unidad||'u'} disp.)</option>`).join('')
      || '<option value="">Sin material en inventario</option>';
  }
  // Cargar los ya consumidos
  const mats = await api(`/api/servicios/${sid}/materiales`);
  _renderMatServicio(mats||[]);
}

function _renderMatServicio(mats){
  const cont = document.getElementById('msvc-mat-list');
  if(!cont) return;
  if(!mats.length){
    cont.innerHTML = '<div style="font-size:.75rem;color:var(--txt2)">Sin materiales cargados todavía.</div>';
    return;
  }
  cont.innerHTML = mats.map(m=>`<div style="display:flex;align-items:center;gap:.5rem;padding:.25rem .4rem;border:1px solid var(--brd);border-radius:6px;margin-bottom:.25rem;font-size:.8rem">
    <span style="flex:1">${m.material||'(material eliminado)'} — <b>${m.cantidad} ${m.unidad||'u'}</b></span>
    <span style="font-size:.68rem;color:var(--txt2)">${(m.fecha||'').slice(0,16)}</span>
    <button type="button" class="btn btn-rj btn-xs" title="Devolver al stock" onclick="quitarMaterialServicio(${m.id})">✕</button>
  </div>`).join('');
}

async function agregarMaterialServicio(){
  const sid = document.getElementById('msvc-id').value;
  if(!sid){ alert('Guardá la orden antes de cargar materiales.'); return; }
  const iid = document.getElementById('msvc-mat-sel').value;
  const cant = parseInt(document.getElementById('msvc-mat-cant').value)||0;
  if(!iid || cant<=0){ alert('Elegí un material y una cantidad válida.'); return; }
  const r = await api(`/api/servicios/${sid}/materiales`,'POST',{items:[{inventario_id:parseInt(iid),cantidad:cant}]});
  if(r && r.ok){
    document.getElementById('msvc-mat-cant').value=1;
    cargarMaterialesServicio(sid);
    if(typeof toast==='function') toast('Material descontado del stock','ok');
  } else {
    alert(r?.error || 'No se pudo descontar el material');
  }
}

async function quitarMaterialServicio(mid){
  if(typeof confirmar==='function'){ if(!await confirmar('¿Devolver este material al stock?')) return; }
  const r = await api(`/api/servicios/materiales/${mid}`,'DELETE');
  const sid = document.getElementById('msvc-id').value;
  if(r && r.ok){ cargarMaterialesServicio(sid); if(typeof toast==='function') toast('Material devuelto al stock','ok'); }
  else alert(r?.error || 'No se pudo revertir');
}

async function openModalStock(id=null){
  ['mstock-id','mstock-modelo','mstock-marca','mstock-desc'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('mstock-cant').value=0;
  document.getElementById('mstock-tipo').value='inalambrico';
  if(id){
    const d=await api('/api/stock');
    const s=(d.manual||[]).find(x=>x.id===id);
    if(s){
      document.getElementById('mstock-id').value=s.id;
      document.getElementById('mstock-modelo').value=s.modelo;
      document.getElementById('mstock-marca').value=s.marca||'';
      document.getElementById('mstock-tipo').value=s.tipo||'inalambrico';
      document.getElementById('mstock-cant').value=s.cantidad||0;
      document.getElementById('mstock-desc').value=s.descripcion||'';
    }
  }
  document.getElementById('modal-stock').style.display='flex';
}

async function openModalAbono(id=null){
  ['mabo-id','mabo-nombre','mabo-precio','mabo-bajada','mabo-subida','mabo-desc'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('mabo-tipo').value='fibra';
  document.getElementById('mabo-title').textContent=id?'Editar Plan':'Nuevo Plan';
  if(id){
    const d=await api('/api/abonos');
    const a=d.find(x=>x.id===id);
    if(a){
      document.getElementById('mabo-id').value=a.id;
      document.getElementById('mabo-nombre').value=a.nombre;
      document.getElementById('mabo-tipo').value=a.tipo;
      document.getElementById('mabo-precio').value=a.precio;
      document.getElementById('mabo-bajada').value=a.velocidad_bajada||'';
      document.getElementById('mabo-subida').value=a.velocidad_subida||'';
      document.getElementById('mabo-desc').value=a.descripcion||'';
    }
  }
  document.getElementById('modal-abono').style.display='flex';
}

function closeModal(id){
  const el = document.getElementById(id);
  if(!el) return;
  el.style.display='none';
  el.style.zIndex='';        // soltar la elevación (ver abrirModal)
}

/* Abre un modal dejándolo SIEMPRE por encima de los que ya están abiertos.
   Todos los .modal-overlay comparten z-index:2000 en el CSS, así que cuando
   hay dos abiertos manda el orden del HTML: como modal-torre se incluye
   después que modal-inv-equipo, el modal del equipo quedaba TAPADO por el de
   la torre (se abre desde adentro de él). En vez de hardcodear un z-index por
   modal, acá se calcula: el que se abre va un escalón arriba del más alto que
   esté visible. Así también funciona para el tercer nivel (equipo → perfil)
   y para cualquier modal anidado que se agregue después. */
function abrirModal(id){
  const el = document.getElementById(id);
  if(!el) return;
  let max = 2000;
  document.querySelectorAll('.modal-overlay').forEach(m=>{
    if(m !== el && m.style.display && m.style.display !== 'none'){
      const z = parseInt(window.getComputedStyle(m).zIndex) || 2000;
      if(z > max) max = z;
    }
  });
  el.style.zIndex = max + 10;
  el.style.display = 'flex';
}

const _navOrig = nav;

const navExt = nav;

const navFn = nav;

async function openModalSenal(napNombre){
  document.getElementById('msenal-nap').value=napNombre;
  document.getElementById('msenal-title').textContent=`Señal — ${napNombre}`;
  document.getElementById('msenal-dbm').value='';
  document.getElementById('msenal-obs').value='';
  await cargarHistorialSenal(napNombre);
  document.getElementById('modal-senal').style.display='flex';
}

async function openProgramarSvc(id, tecnico, fecha){
  const nf= await pedirDato(`Reprogramar servicio #${id}\nFecha (YYYY-MM-DD):`, fecha||new Date().toISOString().slice(0,10));
  if(!nf) return;
  const nt= await pedirDato('Técnico asignado:', tecnico||'');
  if(nt===null) return;
  await api(`/api/agenda/programar/${id}`,'PUT',{fecha_programada:nf,tecnico:nt});
  loadAgenda();
}

// ── CONFIGURACIÓN ──

function agregarBotonSenalEnModal(nombre) {
  setTimeout(() => {
    const body = document.getElementById('mnapd-body');
    if (body && !body.querySelector('[data-btn-senal]')) {
      const div = document.createElement('div');
      div.style.marginTop = '.6rem';
      div.setAttribute('data-btn-senal', '1');
      div.innerHTML = `<button class="btn btn-am btn-sm" onclick="closeModal('modal-nap-detail');openModalSenal('${escJs(nombre)}')">📶 Registrar/Ver Señal</button>`;
      body.appendChild(div);
    }
  }, 200);
}

// ── INPUT LISTENERS para preview PPPoE ──
document.addEventListener('DOMContentLoaded',()=>{
  ['act-pppoe-user','act-pppoe-pass','act-ip'].forEach(id=>{
    const el=document.getElementById(id);
    if(el) el.addEventListener('input',actualizarPreview);
  });
  // Botón pronóstico en carrusel
  const carr=document.getElementById('carousel');
  if(carr){
    const btn=document.createElement('button');
    btn.style.cssText='background:rgba(255,255,255,.15);border:none;color:#fff;border-radius:6px;padding:.25rem .55rem;cursor:pointer;font-size:.75rem;white-space:nowrap;flex-shrink:0';
    btn.textContent='🌤 Pronóstico';
    btn.onclick=openWeatherModal;
    carr.appendChild(btn);
  }
});

// Cerrar dropdowns al click fuera
document.addEventListener('click',e=>{
  const drops=['map-drop','msvc-cli-drop','act-nap-drop'];
  drops.forEach(id=>{
    const drop=document.getElementById(id);
    if(drop) drop.style.display='none';
  });
});

// ── INIT ──
initAuth().then(()=>{ if(typeof cargarModulosSistema==='function') cargarModulosSistema(); });

// ── Panel de módulos del sistema (Configuración) ──
const _MOD_LABELS = {
  dashboard:'📊 Dashboard', clientes:'👥 Clientes', mapa:'🗺️ Mapa', ftth:'🔵 FTTH/Red',
  naps:'📦 NAPs', torres:'🗼 Torres', servicios:'🔧 Servicios', incidencias:'🚨 Incidencias',
  monitoreo:'📡 Monitoreo', instalaciones:'🛠️ Instalaciones', agenda:'📅 Agenda',
  historial:'📜 Historial', rrhh:'🧑‍💼 RRHH', finanzas:'💰 Finanzas', stock:'📦 Stock',
  usuarios:'👤 Usuarios', permisos:'🔐 Permisos', config:'⚙️ Configuración', sync:'🔄 Sync ERP'
};

async function renderModulosSistema(){
  const cont = document.getElementById('cfg-modulos');
  if(!cont) return;
  const mods = await api('/api/sistema/modulos') || {};
  cont.innerHTML = Object.entries(mods).map(([k,v])=>`
    <label style="display:flex;align-items:center;gap:.4rem;padding:.35rem .5rem;border:1px solid var(--brd);border-radius:6px;cursor:pointer;font-size:.82rem;${v?'':'opacity:.55'}">
      <input type="checkbox" data-mod="${k}" ${v?'checked':''} ${k==='config'?'disabled checked':''}>
      ${_MOD_LABELS[k]||k}
    </label>`).join('');
}

async function guardarModulosSistema(){
  const data = {};
  document.querySelectorAll('#cfg-modulos input[data-mod]').forEach(ch=>{
    data[ch.getAttribute('data-mod')] = ch.checked ? 1 : 0;
  });
  data['config'] = 1; // nunca permitir apagar configuración
  const r = await api('/api/sistema/modulos', 'PUT', data);
  if(r && r.ok){
    alert('✓ Módulos actualizados. Recargá la página para ver los cambios en el menú.');
    _modulosSistema = null;
  }
}

// ── Toggle de tema claro/oscuro (oscuro por defecto) ──
function toggleTema(){
  const link = document.getElementById('tema-oscuro-css');
  if(!link) return;
  link.disabled = !link.disabled;
  localStorage.setItem('pucara_tema', link.disabled ? 'claro' : 'oscuro');
  _actualizarBotonTema();
}
function _actualizarBotonTema(){
  const link = document.getElementById('tema-oscuro-css');
  const btn = document.getElementById('btn-tema');
  if(link && btn){
    btn.textContent = link.disabled ? '☀️ Tema claro' : '🌙 Tema oscuro';
  }
}
// Al cargar, dejar el botón en el estado correcto
document.addEventListener('DOMContentLoaded', _actualizarBotonTema);

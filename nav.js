/* ========================================================
   nav.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

function navGo(page, el){
  // Verificar permisos de módulo para todos los usuarios no-admin
  const isAdmin = currentUser.rol === 'admin' || currentUser.rol === 'root';
  if(!isAdmin && typeof _modAccesible === 'function' && !_modAccesible(page)){
    alert(`⛔ No tenés permisos para acceder al módulo "${page}".\n\nSi creés que es un error, hablá con un administrador.`);
    return;
  }

  // Desactivar todos
  document.querySelectorAll('.page,.page-map').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-links a, .nav-drawer a').forEach(a=>a.classList.remove('active'));

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
  else if(page==='servicios') loadServicios();
  else if(page==='ftth') loadOlts();
  else if(page==='incidencias') loadIncidencias();
  else if(page==='stock') loadStock();
  else if(page==='bajas') loadBajas();
  else if(page==='abonos') loadAbonos();
  else if(page==='historial') loadHistorial();
  else if(page==='usuarios') loadUsuarios();
  else if(page==='torres') loadTorres();
  else if(page==='monitoreo') loadMonitoreo();
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
  else if(page==='config') loadConfig();
  else if(page==='activacion-pendiente') loadActivacionPendiente();
  else if(page==='instalacion-pendiente') loadInstalacionPendiente();
  else if(page==='sync') { if(typeof activarSyncPanel==='function') activarSyncPanel(); }
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
  const wasOpen = g.classList.contains('open');
  closeNavGroups();
  if(!wasOpen){
    g.classList.add('open');
    _positionNavGroupMenu(g);
  }
}

function _positionNavGroupMenu(g){
  // Posicionar el menú flotante respecto al botón disparador.
  // Usa position:fixed (definido en CSS), así que las coordenadas son del viewport.
  const trigger = g.querySelector('.nav-group-trigger');
  const menu = g.querySelector('.nav-group-menu');
  if(!trigger || !menu) return;
  const rect = trigger.getBoundingClientRect();
  // Por defecto: alinear left con el botón, justo debajo
  let left = rect.left;
  const top = rect.bottom + 4;
  // Después de mostrarlo, medir su ancho real y ajustar si se sale a la derecha
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
  menu.style.minWidth = Math.max(rect.width, 240) + 'px';
  // En el siguiente frame, ajustar si se sale del viewport
  requestAnimationFrame(() => {
    const menuRect = menu.getBoundingClientRect();
    const overflowRight = menuRect.right - window.innerWidth + 8;
    if(overflowRight > 0){
      menu.style.left = (left - overflowRight) + 'px';
    }
  });
}

function closeNavGroups(){
  document.querySelectorAll('.nav-group.open').forEach(g => g.classList.remove('open'));
}

// Click fuera → cerrar dropdowns
document.addEventListener('click', (e) => {
  if(!e.target.closest('.nav-group')) closeNavGroups();
});

// Cerrar al scroll del body o resize de ventana (sino el menú queda flotando lejos del botón)
window.addEventListener('scroll', closeNavGroups, true);
window.addEventListener('resize', closeNavGroups);

function toggleDrawerSection(el){
  const section = el.parentElement;
  if(!section) return;
  section.classList.toggle('open');
}

// Sincronizar el estado activo del grupo padre cuando navGo se ejecuta:
// si la página activa es una sub de un grupo, marcar el grupo como activo
const _pageToGroup = {
  'naps':'ftth-red', 'ftth':'ftth-red', 'incidencias':'ftth-red',
  'servicios':'servicios', 'activacion-pendiente':'servicios',
  'instalacion-pendiente':'servicios', 'agenda':'servicios',
  'torres':'infraestructura', 'monitoreo':'infraestructura',
  'bajas':'administracion', 'abonos':'administracion', 'stock':'administracion',
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
    }
  } else {
    document.getElementById('msvc-title').textContent='Nueva Orden de Servicio';
  }
  svcTipoChange();
  document.getElementById('modal-servicio').style.display='flex';
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

function closeModal(id){ document.getElementById(id).style.display='none'; }

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
  const nf=prompt(`Reprogramar servicio #${id}\nFecha (YYYY-MM-DD):`, fecha||new Date().toISOString().slice(0,10));
  if(!nf) return;
  const nt=prompt('Técnico asignado:', tecnico||'');
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
      div.innerHTML = `<button class="btn btn-am btn-sm" onclick="closeModal('modal-nap-detail');openModalSenal('${nombre.replace(/'/g,"\\'")}')">📶 Registrar/Ver Señal</button>`;
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
initAuth();

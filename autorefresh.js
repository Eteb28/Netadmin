/* ========================================================
   autorefresh.js — ERLAN NetAdmin v8
   Auto-refresh "soft" de páginas: re-ejecuta la función de carga
   sin recargar el HTML completo (preserva scroll, modales abiertos).
   ======================================================== */

// Frecuencia por página, en segundos. 0 = no auto-refresh.
const _AR_FREQ = {
  'dashboard': 60,
  'mapa': 60,
  'naps': 90,
  'incidencias': 60,
  'servicios': 120,
  'activacion-pendiente': 90,
  'instalacion-pendiente': 90,
  'monitoreo': 60,
  'ftth': 120,
  'agenda': 180,
  'clientes': 0,    // no auto-refresh (data no cambia tanto)
  'historial': 0,
  'stock': 0,
  'abonos': 0,
  'bajas': 0,
  'torres': 120,
  'usuarios': 0,
  'config': 0,
};

// Mapeo de página → función de carga (la que ya invoca navGo)
const _AR_LOAD = {
  'dashboard': () => typeof loadDash === 'function' && loadDash(),
  'mapa': () => {
    if(typeof reloadMapaClientes === 'function') reloadMapaClientes();
    if(typeof reloadMapaNaps === 'function') reloadMapaNaps();
    if(typeof loadMonitoreoBadge === 'function') loadMonitoreoBadge();
  },
  'naps': () => typeof loadNaps === 'function' && loadNaps(),
  'incidencias': () => typeof loadIncidencias === 'function' && loadIncidencias(),
  'servicios': () => typeof loadServicios === 'function' && loadServicios(),
  'activacion-pendiente': () => typeof loadActivacionPendiente === 'function' && loadActivacionPendiente(),
  'instalacion-pendiente': () => typeof loadInstalacionPendiente === 'function' && loadInstalacionPendiente(),
  'monitoreo': () => typeof loadMonitoreo === 'function' && loadMonitoreo(),
  'ftth': () => typeof loadOlts === 'function' && loadOlts(),
  'agenda': () => typeof loadAgenda === 'function' && loadAgenda(),
  'torres': () => typeof loadTorres === 'function' && loadTorres(),
};

let _arTimer = null;
let _arCurrentPage = null;
let _arEnabled = true;
let _arLastRefresh = null;
let _arUiTimer = null;

function _arGetEnabled(){
  try {
    const v = localStorage.getItem('autorefresh_enabled');
    if(v !== null) _arEnabled = v === '1';
  } catch(e){}
  return _arEnabled;
}

function _arSetEnabled(val){
  _arEnabled = !!val;
  try { localStorage.setItem('autorefresh_enabled', val ? '1' : '0'); } catch(e){}
  _arUpdateIndicator();
  if(_arEnabled) _arStart(_arCurrentPage);
  else _arStop();
}

function _arHasOpenModal(){
  return Array.from(document.querySelectorAll('.modal-overlay'))
    .some(m => m.style.display === 'flex' || m.classList.contains('open'));
}

function _arShouldRefresh(){
  if(!_arEnabled) return false;
  if(document.hidden) return false;
  if(_arHasOpenModal()) return false;
  return true;
}

function _arDoRefresh(){
  const page = _arCurrentPage;
  if(!page) return;
  const fn = _AR_LOAD[page];
  if(!fn) return;
  if(!_arShouldRefresh()){
    // Postpone: re-schedule but don't run
    return;
  }
  try {
    fn();
    _arLastRefresh = Date.now();
    _arUpdateIndicator();
  } catch(e){
    console.warn('autorefresh error:', e);
  }
}

function _arStart(page){
  _arStop();
  _arCurrentPage = page;
  if(!_arEnabled) { _arUpdateIndicator(); return; }
  const freq = _AR_FREQ[page];
  if(!freq || freq <= 0){ _arUpdateIndicator(); return; }
  _arTimer = setInterval(_arDoRefresh, freq * 1000);
  _arUpdateIndicator();
}

function _arStop(){
  if(_arTimer){ clearInterval(_arTimer); _arTimer = null; }
}

// Indicador visual
function _arUpdateIndicator(){
  let ind = document.getElementById('ar-indicator');
  if(!ind){
    ind = document.createElement('div');
    ind.id = 'ar-indicator';
    ind.style.cssText = `
      position:fixed; bottom:12px; right:12px;
      background:rgba(26,61,107,.92); color:#fff;
      padding:.4rem .7rem; border-radius:20px;
      font-size:.72rem; cursor:pointer;
      box-shadow:0 2px 8px rgba(0,0,0,.3);
      z-index:9999; user-select:none;
      display:flex; align-items:center; gap:.4rem;
      transition:opacity .3s;
    `;
    ind.onclick = () => _arSetEnabled(!_arEnabled);
    ind.title = 'Click para pausar/reanudar auto-refresh';
    document.body.appendChild(ind);
  }
  const freq = _AR_FREQ[_arCurrentPage] || 0;
  if(!_arEnabled){
    ind.innerHTML = '<span style="color:#ffab40">⏸</span> Auto-refresh pausado';
    ind.style.background = 'rgba(120,80,30,.92)';
  } else if(freq <= 0){
    ind.innerHTML = '<span style="opacity:.6">○</span> No auto-refresh';
    ind.style.background = 'rgba(60,60,60,.85)';
  } else {
    let txt = '';
    if(_arLastRefresh){
      const sec = Math.round((Date.now() - _arLastRefresh) / 1000);
      txt = ` · hace ${sec}s`;
    }
    ind.innerHTML = `<span style="color:#69f0ae">●</span> Refresh c/${freq}s${txt}`;
    ind.style.background = 'rgba(26,61,107,.92)';
  }
}

// Mantener actualizado el "hace Xs"
function _arStartUiTimer(){
  if(_arUiTimer) return;
  _arUiTimer = setInterval(_arUpdateIndicator, 5000);
}

// Hook a navGo: cuando cambia de página, reiniciar el timer
(function(){
  const orig = window.navGo;
  window.navGo = function(page, el){
    orig(page, el);
    _arStart(page);
  };
})();

// Pausa cuando se oculta la pestaña, reanuda al volver
document.addEventListener('visibilitychange', () => {
  _arUpdateIndicator();
  if(!document.hidden && _arEnabled){
    // Forzar un refresh al volver al tab si pasó tiempo suficiente
    if(_arLastRefresh){
      const elapsed = (Date.now() - _arLastRefresh) / 1000;
      const freq = _AR_FREQ[_arCurrentPage] || 0;
      if(freq > 0 && elapsed >= freq) _arDoRefresh();
    }
  }
});

// Init al cargar página
window.addEventListener('DOMContentLoaded', () => {
  _arGetEnabled();
  _arStartUiTimer();
  // Guardar página inicial (dashboard por defecto al cargar)
  setTimeout(() => {
    _arCurrentPage = _arCurrentPage || 'dashboard';
    _arStart(_arCurrentPage);
  }, 1000);
});

// API pública por si querés controlar desde otra parte
window.autorefresh = {
  pause: () => _arSetEnabled(false),
  resume: () => _arSetEnabled(true),
  toggle: () => _arSetEnabled(!_arEnabled),
  forceNow: () => _arDoRefresh(),
  isEnabled: () => _arEnabled,
};

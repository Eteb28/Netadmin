/* ========================================================
   auth.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

let currentUser={}, cliPage=1, cliTotal=0;

let userPermisos = {};

async function initAuth(){
  const d=await api('/api/me');
  if(!d||d.error){window.location.href='/login';return;}
  currentUser=d;
  try { userPermisos = typeof d.permisos === 'string' ? JSON.parse(d.permisos || '{}') : (d.permisos || {}); } catch(e){ userPermisos={}; }
  // También obtener permisos parseados del endpoint dedicado (más confiable)
  try {
    const myPerms = await api('/api/me/permisos');
    if(myPerms && !myPerms.error){
      // Normalizar: si vino objeto, sobreescribir; si vino '*' / 'root', dejar wildcard
      if(typeof myPerms === 'object') userPermisos = myPerms;
    }
  } catch(e){}
  document.getElementById('nav-nombre').textContent=d.nombre;

  const isAdmin = d.rol==='admin'||d.rol==='root';
  const mods = userPermisos.modulos || '*';

  // "Actividad Diaria" del dashboard: visible sólo si tiene módulo clientes
  const actDiaria = document.getElementById('dash-act-diaria');
  if(actDiaria) actDiaria.style.display = (isAdmin || _modAccesible('clientes')) ? 'block' : 'none';

  // Links admin-only siempre visibles para admin/root
  if(isAdmin){
    ['nav-usuarios','nav-config','nav-sync'].forEach(id=>{
      const el=document.getElementById(id); if(el) el.style.display='';
    });
    ['drawer-usuarios','drawer-config','drawer-sync'].forEach(id=>{
      const el=document.getElementById(id); if(el) el.style.display='';
    });
  }

  // Aplicar permisos de visibilidad a TODOS los usuarios no-admin
  // (sprint v8.2: antes solo aplicaba a técnicos)
  if(!isAdmin && mods !== '*'){
    _aplicarRestriccionesNav(mods);
  }

  await loadLocalidades();
  await loadTecnicos();
  await loadNapDatalist();
  await loadOltDatalist();
  await loadPlanDatalist();
  await loadRedes();

  // Ocultar botones de creación/edición según permisos en cada módulo
  if(!isAdmin){
    if(!puedeCrear('naps')){
      const btn=document.getElementById('btn-nueva-nap'); if(btn) btn.style.display='none';
    }
    if(!puedeCrear('clientes')){
      const btn=document.getElementById('btn-nuevo-cliente'); if(btn) btn.style.display='none';
    }
    if(!puedeCrear('incidencias')){
      const btn=document.getElementById('btn-nueva-incidencia'); if(btn) btn.style.display='none';
    }
    // Ocultar precio en columnas de abonos para usuarios sin flag ver_precio
    if(campoOculto('precio') || (!tieneFlag('ver_precio') && !isAdmin)){
      document.querySelectorAll('[data-admin-only]').forEach(el=>el.style.display='none');
    }
  }

  // Decidir página inicial: dashboard si puede, sino el primer módulo accesible
  if(_modAccesible('dashboard')){
    loadDash();
  } else if(Array.isArray(mods) && mods.length){
    navGo(mods[0]);
  } else {
    // Sin permisos a nada — caso raro, mostrar mensaje
    document.body.innerHTML = '<div style="padding:3rem;text-align:center"><h2>⛔ Sin acceso</h2><p>Tu usuario no tiene permisos para ningún módulo.</p><p><a href="/logout">Cerrar sesión</a></p></div>';
    return;
  }
  loadWeatherCarousel();
  setInterval(loadNotifBadge,60000);
}

// Helper: aplicar restricciones de navegación según los módulos permitidos
function _aplicarRestriccionesNav(modsPermitidos){
  const isAllowed = (modulo) => {
    if(modulo === 'dashboard') return modsPermitidos === '*' || modsPermitidos.includes('dashboard');
    return modsPermitidos === '*' || (Array.isArray(modsPermitidos) && modsPermitidos.includes(modulo));
  };
  // Links del navbar desktop
  document.querySelectorAll('#nav-links-desktop a, #nav-links-desktop .nav-group-menu a').forEach(a=>{
    const onclick = a.getAttribute('onclick')||'';
    const m = onclick.match(/navGo\('([\w-]+)'/);
    if(m){
      const modulo = m[1];
      if(!isAllowed(modulo)) a.style.display='none';
    }
  });
  // Drawer móvil
  document.querySelectorAll('#nav-drawer a').forEach(a=>{
    const onclick = a.getAttribute('onclick')||'';
    const m = onclick.match(/navGo\('([\w-]+)'/);
    if(m){
      const modulo = m[1];
      if(!isAllowed(modulo)) a.style.display='none';
    }
  });
  // Si un grupo entero quedó sin items visibles, ocultar el trigger del grupo
  document.querySelectorAll('.nav-group').forEach(g=>{
    const visibleItems = Array.from(g.querySelectorAll('.nav-group-menu a'))
      .filter(a => a.style.display !== 'none');
    if(visibleItems.length === 0){
      g.style.display = 'none';
    }
  });
  // Y secciones del drawer sin items visibles
  document.querySelectorAll('.drawer-section').forEach(s=>{
    const visibleItems = Array.from(s.querySelectorAll('.drawer-section-content a'))
      .filter(a => a.style.display !== 'none');
    if(visibleItems.length === 0){
      s.style.display = 'none';
    }
  });
}

// ── Helpers de permisos (sprint v8.2) ──
function _modAccesible(modulo){
  if(currentUser.rol==='admin'||currentUser.rol==='root') return true;
  const mods = userPermisos.modulos;
  if(mods === '*') return true;
  if(Array.isArray(mods)) return mods.includes(modulo);
  return false;
}

function puedeVer(modulo){
  return _modAccesible(modulo) && _puedeAccion(modulo, 'ver');
}

function puedeCrear(modulo){
  return _modAccesible(modulo) && _puedeAccion(modulo, 'crear');
}

function puedeEditar(modulo){
  return _modAccesible(modulo) && _puedeAccion(modulo, 'editar');
}

function puedeEliminar(modulo){
  return _modAccesible(modulo) && _puedeAccion(modulo, 'eliminar');
}

function _puedeAccion(modulo, accion){
  if(currentUser.rol==='admin'||currentUser.rol==='root') return true;
  // Acciones específicas por módulo: <modulo>_acciones tiene prioridad
  let acciones = userPermisos[modulo+'_acciones'];
  if(acciones === undefined) acciones = userPermisos.acciones;
  if(acciones === '*') return true;
  return Array.isArray(acciones) && acciones.includes(accion);
}

function tieneFlag(flag){
  if(currentUser.rol==='admin'||currentUser.rol==='root') return true;
  const flags = userPermisos.flags || [];
  return Array.isArray(flags) && flags.includes(flag);
}

function campoOculto(campo){
  const ocultar = userPermisos.ocultar_campos || [];
  return Array.isArray(ocultar) && ocultar.includes(campo);
}

async function poblarFiltroLocalidades() {
  const sel = document.getElementById('gf-localidad');
  if (!sel || sel.options.length > 1) return;
  const locs = await api('/api/localidades');
  if (locs) locs.forEach(l => {
    const o = document.createElement('option');
    o.value = l; o.textContent = l;
    sel.appendChild(o);
  });
}

async function loadUsuarios(){
  const d=await api('/api/usuarios');
  if(!d) return;
  const tbody=document.getElementById('usr-tbody');
  tbody.innerHTML=d.map(u=>`<tr>
    <td><code>${u.username}</code></td>
    <td>${u.nombre}</td>
    <td><span class="badge ${u.rol==='admin'?'b-rescision':'b-activo'}">${u.rol}</span></td>
    <td><span class="badge ${u.activo?'b-activo':'b-baja'}">${u.activo?'Activo':'Inactivo'}</span></td>
    <td><button class="btn btn-gray btn-xs" onclick="openModalUsuario(${u.id})">✏️</button></td>
  </tr>`).join('');
}

async function openModalUsuario(id=null){
  ['musr-id','musr-username','musr-nombre','musr-pass'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('musr-rol').value='operador';
  document.getElementById('musr-title').textContent=id?'Editar Usuario':'Nuevo Usuario';
  if(id){
    const d=await api('/api/usuarios');
    const u=d.find(x=>x.id===id);
    if(u){
      document.getElementById('musr-id').value=u.id;
      document.getElementById('musr-username').value=u.username;
      document.getElementById('musr-nombre').value=u.nombre;
      document.getElementById('musr-rol').value=u.rol;
    }
  }
  document.getElementById('modal-usuario').style.display='flex';
}

async function saveUsuario(){
  const id=document.getElementById('musr-id').value;
  const data={username:document.getElementById('musr-username').value,
    nombre:document.getElementById('musr-nombre').value,
    password:document.getElementById('musr-pass').value,
    rol:document.getElementById('musr-rol').value,
    activo:1};
  const r=await api(id?`/api/usuarios/${id}`:'/api/usuarios',id?'PUT':'POST',data);
  if(r?.ok){closeModal('modal-usuario');loadUsuarios();}
  else alert('Error al guardar');
}

// ── HELPERS ──

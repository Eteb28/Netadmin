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
      if(myPerms.all){
        userPermisos = {modulos:'*', acciones:'*'};
      } else if(myPerms.permisos && typeof myPerms.permisos === 'object'){
        userPermisos = myPerms.permisos;
      }
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
    ['nav-usuarios','nav-config','nav-sync','nav-rrhh','btn-exportar-clientes'].forEach(id=>{
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
  } else if(!mods || mods === '*' || (typeof mods === 'object' && !Array.isArray(mods))){
    // Sin permisos configurados → acceso básico a dashboard
    loadDash();
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
    // Módulos universales: todos los ven, sin importar permisos
    if(modulo === 'dashboard' || modulo === 'tareas') return true;
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
  // Módulos universales: todos acceden, sin importar rol ni permisos
  if(modulo === 'dashboard' || modulo === 'tareas') return true;
  if(currentUser.rol==='admin'||currentUser.rol==='root') return true;
  const mods = userPermisos.modulos;
  if(mods === '*') return true;
  if(Array.isArray(mods)) return mods.includes(modulo);
  // Si no hay permisos configurados (undefined/null/{}), permitir dashboard como mínimo
  if(mods === undefined || mods === null) return modulo === 'dashboard';
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
  loadConectados();  // panel de usuarios en línea
  const d=await api('/api/usuarios');
  if(!d) return;
  const tbody=document.getElementById('usr-tbody');
  tbody.innerHTML=d.map(u=>`<tr>
    <td><code>${escHtml(u.username)}</code></td>
    <td>${escHtml(u.nombre)}</td>
    <td><span class="badge ${u.rol==='admin'?'b-rescision':'b-activo'}">${escHtml(u.rol)}</span></td>
    <td><span class="badge ${u.activo?'b-activo':'b-baja'}">${u.activo?'Activo':'Inactivo'}</span></td>
    <td><button class="btn btn-gray btn-xs" onclick="openModalUsuario(${u.id})">✏️</button></td>
  </tr>`).join('');
}

async function loadConectados(){
  const data = await api('/api/usuarios/conectados');
  if(!data) return;
  const cnt = document.getElementById('conectados-cnt');
  if(cnt) cnt.textContent = `${data.en_linea} en línea`;
  const cont = document.getElementById('conectados-list');
  if(!cont) return;
  if(!data.usuarios.length){
    cont.innerHTML = '<div style="color:#888;padding:.5rem">Sin actividad registrada</div>';
    return;
  }
  const dot = {en_linea:'#2e7d32', inactivo:'#f9a825', desconectado:'#9aa6b3'};
  const lbl = {en_linea:'En línea', inactivo:'Inactivo', desconectado:'Desconectado'};
  const hace = s => s<60?`${s}s`:s<3600?`${Math.floor(s/60)}min`:s<86400?`${Math.floor(s/3600)}h`:`${Math.floor(s/86400)}d`;
  cont.innerHTML = `<table class="tbl"><thead><tr>
      <th></th><th>Usuario</th><th>Rol</th><th>Última actividad</th><th>IP</th><th>Sección</th>
    </tr></thead><tbody>` +
    data.usuarios.map(u=>`<tr>
      <td><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${dot[u.estado]}" title="${escAttr(lbl[u.estado])}"></span></td>
      <td><b>${escHtml(u.nombre||u.username)}</b><br><small style="color:var(--txt2)">${escHtml(u.username)}</small></td>
      <td><span class="badge">${escHtml(u.rol)||'—'}</span></td>
      <td>${u.estado==='en_linea'?'<b style="color:#2e7d32">ahora</b>':'hace '+hace(u.segundos_inactivo)}</td>
      <td><small>${escHtml(u.ip)||'—'}</small></td>
      <td><small style="color:var(--txt2)">${escHtml((u.ultima_ruta||'').replace('/api/',''))}</small></td>
    </tr>`).join('') + '</tbody></table>';
}

async function openModalUsuario(id=null){
  ['musr-id','musr-username','musr-nombre','musr-pass'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('musr-rol').value='operador';
  const chkG=document.getElementById('musr-guardias'); if(chkG) chkG.checked=false;
  document.getElementById('musr-title').textContent=id?'Editar Usuario':'Nuevo Usuario';
  if(id){
    const d=await api('/api/usuarios');
    const u=d.find(x=>x.id===id);
    if(u){
      document.getElementById('musr-id').value=u.id;
      document.getElementById('musr-username').value=u.username;
      document.getElementById('musr-nombre').value=u.nombre;
      document.getElementById('musr-rol').value=u.rol;
      if(chkG) chkG.checked=!!u.puede_editar_guardias;
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
    puede_editar_guardias:document.getElementById('musr-guardias')?.checked?1:0,
    activo:1};
  const r=await api(id?`/api/usuarios/${id}`:'/api/usuarios',id?'PUT':'POST',data);
  if(r?.ok){closeModal('modal-usuario');loadUsuarios();}
  else alert('Error al guardar');
}

// ── HELPERS ──

// ── Uso del sistema (registro de secciones) ──
const _SECCIONES_CATALOGO = {
  dashboard:'Dashboard', clientes:'Clientes', mapa:'Mapa', naps:'NAPs',
  torres:'Torres', 'torres-enlaces':'Enlaces de Torres', 'enlaces-snmp':'Enlaces SNMP', 'perfiles-radio':'Perfiles de Radio', 'capacidad-aps':'Capacidad de APs', 'cobertura-mapa':'Mapa de Cobertura', aps:'APs',
  'enlaces-alertas':'Alertas de Enlaces', monitoreo:'Monitoreo',
  incidencias:'Incidencias', servicios:'Servicios', agenda:'Agenda',
  'instalacion-pendientes':'Instalaciones', 'activacion-pendientes':'Activación',
  abonos:'Abonos', bajas:'Bajas', ftth:'FTTH', 'ftth-capacidad':'Capacidad PONs', ftth_plan:'FTTH Plan',
  stock:'Stock', finanzas:'Finanzas', 'gestion-tecnico':'Técnico Interior',
  rrhh:'RRHH', guardias:'Guardias', historial:'Historial',
  usuarios:'Usuarios', sync:'Sync ERP', config:'Config',
  'stats-service':'Estadísticas Service',
};

async function loadUsoSistema(){
  const cont = document.getElementById('uso-sistema');
  if(!cont) return;
  const d = await api('/api/uso/resumen');
  if(!d){ cont.innerHTML = '<div style="color:#888">No se pudo cargar</div>'; return; }

  const conUso = new Set((d.por_seccion||[]).map(s=>s.seccion));
  const nunca = Object.keys(_SECCIONES_CATALOGO).filter(k=>!conUso.has(k));

  const filaSec = (s)=>{
    const nombre = _SECCIONES_CATALOGO[s.seccion] || s.seccion;
    const muerto30 = s.total_30d===0 && s.total_hist>0;
    const estilo = muerto30 ? 'color:#c62828' : '';
    return `<tr style="border-bottom:1px solid var(--brd);${estilo}">
      <td style="padding:.35rem .5rem"><b>${nombre}</b></td>
      <td style="padding:.35rem .5rem;text-align:center">${s.total_30d}</td>
      <td style="padding:.35rem .5rem;text-align:center">${s.usuarios_30d}</td>
      <td style="padding:.35rem .5rem;text-align:center">${s.total_hist}</td>
      <td style="padding:.35rem .5rem;font-size:.8rem">${s.ultima_vez||'—'}${muerto30?' <b>← dejó de usarse</b>':''}</td>
    </tr>`;
  };
  const filaUsr = (u)=>`<tr style="border-bottom:1px solid var(--brd)">
      <td style="padding:.3rem .5rem"><b>${escHtml(u.username)}</b></td>
      <td style="padding:.3rem .5rem;text-align:center">${u.total_30d}</td>
      <td style="padding:.3rem .5rem;text-align:center">${u.secciones_30d}</td>
      <td style="padding:.3rem .5rem;font-size:.8rem">${escHtml(u.ultima_vez)||'—'}</td>
    </tr>`;

  cont.innerHTML = `
    <div class="tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:.85rem">
      <thead><tr style="background:var(--card)">
        <th style="text-align:left;padding:.35rem .5rem">Sección</th>
        <th style="padding:.35rem .5rem">Aperturas 30d</th>
        <th style="padding:.35rem .5rem">Usuarios 30d</th>
        <th style="padding:.35rem .5rem">Histórico</th>
        <th style="text-align:left;padding:.35rem .5rem">Última vez</th>
      </tr></thead>
      <tbody>${(d.por_seccion||[]).map(filaSec).join('') || '<tr><td colspan="5" style="padding:.6rem;color:#888">Sin datos todavía — el registro acumula desde ahora.</td></tr>'}</tbody>
    </table></div>
    ${nunca.length ? `<div style="margin-top:.6rem;padding:.5rem .7rem;background:var(--tint-ambar);border:1px solid #ffe082;border-radius:6px;font-size:.83rem">
      <b>Sin ningún registro de uso:</b> ${nunca.map(k=>_SECCIONES_CATALOGO[k]).join(', ')}
    </div>` : ''}
    <details style="margin-top:.7rem">
      <summary style="cursor:pointer;font-size:.85rem;color:var(--txt2)">Ver desglose por usuario (30 días)</summary>
      <div class="tbl-wrap" style="margin-top:.4rem"><table style="width:100%;border-collapse:collapse;font-size:.83rem">
        <thead><tr style="background:var(--card)">
          <th style="text-align:left;padding:.3rem .5rem">Usuario</th>
          <th style="padding:.3rem .5rem">Aperturas</th>
          <th style="padding:.3rem .5rem">Secciones distintas</th>
          <th style="text-align:left;padding:.3rem .5rem">Última actividad</th>
        </tr></thead>
        <tbody>${(d.por_usuario||[]).map(filaUsr).join('')}</tbody>
      </table></div>
    </details>`;
}

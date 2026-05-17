/* ========================================================
   permisos.js — ERLAN NetAdmin v8
   Panel de administración de permisos por usuario.
   ======================================================== */

let _permCatalogo = null;
let _permUsuarios = [];
let _permActual = null;  // permisos del usuario que se está editando
let _permTemplates = null;

async function loadPanelPermisos(){
  const cont = document.getElementById('permisos-panel-content');
  if(!cont) return;
  
  // Cargar catálogo si no está
  if(!_permCatalogo){
    _permCatalogo = await api('/api/permisos/catalogo');
    if(_permCatalogo) _permTemplates = _permCatalogo.roles_template;
  }
  
  // Cargar lista de usuarios
  _permUsuarios = await api('/api/usuarios');
  if(!_permUsuarios){
    cont.innerHTML = '<div style="color:#dc3545;padding:.6rem">Error al cargar usuarios</div>';
    return;
  }
  
  cont.innerHTML = `
    <div style="overflow-x:auto">
      <table class="tbl" style="font-size:.85rem">
        <thead><tr>
          <th>Usuario</th><th>Nombre</th><th>Rol</th><th>Estado</th><th>Acceso resumido</th><th>Acciones</th>
        </tr></thead>
        <tbody>
        ${_permUsuarios.map(u => {
          const p = u.permisos_obj || {};
          let resumen = '';
          if(p.modulos === '*' || u.permisos === 'root' || u.permisos === '*'){
            resumen = '<span style="color:#2e7d32;font-weight:600">✓ Acceso total</span>';
          } else if(Array.isArray(p.modulos)){
            resumen = `<span title="${p.modulos.join(', ')}">${p.modulos.length} módulos · ${(p.acciones||[]).join(', ')||'sin acciones'}</span>`;
          } else {
            resumen = '<span style="color:#888">Sin configurar</span>';
          }
          return `<tr>
            <td><b>${u.username}</b></td>
            <td>${u.nombre||'—'}</td>
            <td><span class="badge ${u.rol==='admin'?'b-fibra':u.rol==='tecnico'?'b-pendiente':'b-inalambrico'}">${u.rol}</span></td>
            <td>${u.activo?'<span class="badge b-activo">Activo</span>':'<span class="badge b-baja">Inactivo</span>'}</td>
            <td style="font-size:.78rem">${resumen}</td>
            <td><button class="btn btn-prim btn-xs" onclick="editarPermisos(${u.id})">🔐 Editar permisos</button></td>
          </tr>`;
        }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

async function editarPermisos(uid){
  const r = await api(`/api/usuarios/${uid}/permisos`);
  if(!r) return;
  _permActual = JSON.parse(JSON.stringify(r.permisos || {}));
  
  document.getElementById('mperm-uid').value = uid;
  document.getElementById('mperm-title').textContent = `🔐 Permisos: ${r.username}`;
  
  // Buscar el usuario para sacar el rol/activo
  const u = _permUsuarios.find(x => x.id === uid);
  document.getElementById('mperm-rol').value = u?.rol || 'administrativo';
  document.getElementById('mperm-activo').value = u?.activo ? '1' : '0';
  
  document.getElementById('mperm-user-info').innerHTML = `
    <div><b>${r.nombre}</b> · <code>${r.username}</code></div>
    <div style="font-size:.78rem;color:var(--txt2);margin-top:.2rem">
      ID #${r.id} · rol actual: <b>${r.rol}</b>
    </div>
  `;
  
  // Renderizar matriz y flags
  _renderPermisosMatriz();
  _renderPermisosFlags();
  
  document.getElementById('modal-permisos').style.display = 'flex';
}

function _renderPermisosMatriz(){
  const tabla = document.getElementById('mperm-matriz');
  if(!tabla || !_permCatalogo) return;
  
  const wildcard = (_permActual.modulos === '*');
  document.getElementById('mperm-wildcard').checked = wildcard;
  
  const acciones = _permCatalogo.acciones;
  
  // Header
  let html = '<thead><tr><th style="text-align:left;padding:.4rem;background:#f5f5f5">Módulo</th>';
  acciones.forEach(a => {
    html += `<th style="padding:.3rem;background:#f5f5f5;font-size:.75rem;width:60px">${a.label}</th>`;
  });
  html += '</tr></thead><tbody>';
  
  _permCatalogo.modulos.forEach(m => {
    const moduloEnabled = _moduloHabilitado(m.key);
    const moduloChecked = wildcard || moduloEnabled;
    html += `<tr ${moduloChecked?'':'style="opacity:.6"'}>`;
    html += `<td style="padding:.3rem">
      <label style="display:flex;align-items:center;gap:.3rem;cursor:pointer">
        <input type="checkbox" data-mod="${m.key}" ${moduloChecked?'checked':''} ${wildcard?'disabled':''} onchange="onModuloToggle(this)">
        ${m.label}${m.admin_only?' <small style="color:#888">(admin)</small>':''}
      </label>
    </td>`;
    acciones.forEach(a => {
      const accionChecked = wildcard || _accionHabilitada(m.key, a.key);
      html += `<td style="text-align:center;padding:.3rem">
        <input type="checkbox" data-mod="${m.key}" data-action="${a.key}" ${accionChecked?'checked':''} ${(wildcard||!moduloChecked)?'disabled':''}>
      </td>`;
    });
    html += '</tr>';
  });
  html += '</tbody>';
  tabla.innerHTML = html;
}

function _moduloHabilitado(modKey){
  const mods = _permActual.modulos;
  if(mods === '*') return true;
  if(Array.isArray(mods)) return mods.includes(modKey);
  return false;
}

function _accionHabilitada(modKey, accion){
  if(_permActual.modulos === '*') return true;
  if(_permActual.acciones === '*') return true;
  if(Array.isArray(_permActual.acciones) && _permActual.acciones.includes(accion)) return true;
  // Acciones específicas por módulo: <modulo>_acciones
  const arr = _permActual[modKey + '_acciones'];
  if(Array.isArray(arr) && arr.includes(accion)) return true;
  return false;
}

function _renderPermisosFlags(){
  const cont = document.getElementById('mperm-flags');
  if(!cont || !_permCatalogo) return;
  const flags = _permActual.flags || [];
  cont.innerHTML = _permCatalogo.flags_especiales.map(f => `
    <label style="display:flex;align-items:center;gap:.4rem;cursor:pointer;padding:.3rem;border:1px solid var(--brd);border-radius:4px">
      <input type="checkbox" data-flag="${f.key}" ${flags.includes(f.key)?'checked':''}>
      <span style="font-size:.85rem">${f.label}</span>
    </label>
  `).join('');
}

function onWildcardChange(){
  const checked = document.getElementById('mperm-wildcard').checked;
  if(checked){
    _permActual.modulos = '*';
    _permActual.acciones = '*';
  } else {
    _permActual.modulos = [];
    _permActual.acciones = ['ver'];
  }
  _renderPermisosMatriz();
}

function onModuloToggle(cb){
  const mod = cb.dataset.mod;
  if(!Array.isArray(_permActual.modulos)) _permActual.modulos = [];
  if(cb.checked){
    if(!_permActual.modulos.includes(mod)) _permActual.modulos.push(mod);
  } else {
    _permActual.modulos = _permActual.modulos.filter(m => m !== mod);
  }
  // Habilitar/deshabilitar checkboxes de acciones de esta fila
  _renderPermisosMatriz();
}

function aplicarTemplateRol(force){
  const rol = document.getElementById('mperm-rol').value;
  if(rol === 'custom') return;
  if(!force){
    // Solo aplicar si no se eligió manualmente "custom"
    // (cuando el usuario cambia el rol)
  }
  if(_permTemplates && _permTemplates[rol]){
    _permActual = JSON.parse(JSON.stringify(_permTemplates[rol]));
    _renderPermisosMatriz();
    _renderPermisosFlags();
  }
}

async function guardarPermisos(){
  const uid = document.getElementById('mperm-uid').value;
  
  // Recolectar el estado de los checkboxes
  const wildcard = document.getElementById('mperm-wildcard').checked;
  let permisos;
  if(wildcard){
    permisos = {modulos:'*', acciones:'*'};
  } else {
    const modulos = [];
    const accionesGlobales = new Set();
    document.querySelectorAll('#mperm-matriz input[data-mod][data-action]').forEach(cb => {
      if(cb.checked) accionesGlobales.add(cb.dataset.action);
    });
    document.querySelectorAll('#mperm-matriz input[data-mod]:not([data-action])').forEach(cb => {
      if(cb.checked) modulos.push(cb.dataset.mod);
    });
    permisos = {modulos, acciones: Array.from(accionesGlobales)};
  }
  
  // Flags especiales
  const flags = [];
  document.querySelectorAll('#mperm-flags input[data-flag]').forEach(cb => {
    if(cb.checked) flags.push(cb.dataset.flag);
  });
  if(flags.length) permisos.flags = flags;
  
  // Si cambió rol o estado, también actualizarlos
  const rol = document.getElementById('mperm-rol').value;
  const activo = parseInt(document.getElementById('mperm-activo').value);
  
  // Update permisos
  let r = await api(`/api/usuarios/${uid}/permisos`, 'PUT', {permisos});
  if(r?.error){
    alert('Error: ' + r.error);
    return;
  }
  
  // Update rol/activo si cambiaron — necesito el resto de campos
  const u = _permUsuarios.find(x => x.id === parseInt(uid));
  if(u && (u.rol !== rol || (u.activo?1:0) !== activo)){
    const r2 = await api(`/api/usuarios/${uid}`, 'PUT', {
      nombre: u.nombre, rol: rol, activo: activo
    });
    if(r2?.error){
      alert('Permisos guardados, pero error al actualizar rol/estado: ' + r2.error);
      return;
    }
  }
  
  closeModal('modal-permisos');
  
  // Aviso: si el usuario afectado está logueado en otra sesión, debe re-loguear
  const username = u?.username || `#${uid}`;
  const esYoMismo = parseInt(uid) === currentUser.id;
  if(esYoMismo){
    alert(`✓ Permisos guardados.\n\nComo te modificaste a vos mismo, recargá la página (Ctrl+F5) para que los cambios tomen efecto en tu sesión actual.`);
  } else {
    alert(`✓ Permisos de "${username}" guardados.\n\nIMPORTANTE: el usuario debe cerrar sesión y volver a entrar para que los cambios tomen efecto.`);
  }
  loadPanelPermisos();
}

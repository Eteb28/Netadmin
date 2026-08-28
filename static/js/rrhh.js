/* ========================================================
   rrhh.js — Módulo de Recursos Humanos (ERLAN NetAdmin v6)
   Solo accesible para rol admin.
   ======================================================== */

async function loadRRHH(){
  loadEmpleadosLista();
  loadCalendarioAusencias();
  loadSolicitudesPendientes();
  loadAniosAusencias();
  loadHistorialAusencias();
}

async function loadEmpleadosLista(){
  const q = document.getElementById('rrhh-q')?.value || '';
  const area = document.getElementById('rrhh-area')?.value || '';
  const [resumen, emps] = await Promise.all([
    api('/api/empleados/resumen'),
    api(`/api/empleados?q=${encodeURIComponent(q)}&area=${encodeURIComponent(area)}`),
  ]);

  if(resumen){
    const cont = document.getElementById('rrhh-resumen');
    if(cont){
      cont.innerHTML = `<div class="fin-card green">
          <div class="fin-val">${resumen.total_activos}</div>
          <div class="fin-lbl">Empleados activos</div>
        </div>` +
        resumen.por_area.map(a=>`<div class="fin-card">
          <div class="fin-val">${a.cantidad}</div>
          <div class="fin-lbl">${a.area}</div>
        </div>`).join('');
    }
  }

  const cont = document.getElementById('rrhh-list');
  if(!cont) return;
  if(!emps || !emps.length){
    cont.innerHTML = '<div style="color:#888;padding:1rem;text-align:center">Sin empleados cargados</div>';
    return;
  }
  cont.innerHTML = `<table class="tbl"><thead><tr>
      <th>Legajo</th><th>Nombre</th><th>Área</th><th>Puesto</th><th>Ingreso</th><th>Estado</th><th></th>
    </tr></thead><tbody>` +
    emps.map(e=>`<tr>
      <td>${escHtml(e.legajo)||'—'}</td>
      <td><b>${escHtml(e.nombre)}</b>${e.dni?`<br><small style="color:var(--txt2)">DNI ${escHtml(e.dni)}</small>`:''}</td>
      <td>${escHtml(e.area)||'—'}</td>
      <td>${escHtml(e.puesto)||'—'}</td>
      <td>${escHtml(e.fecha_ingreso)||'—'}</td>
      <td><span class="badge ${e.estado==='activo'?'b-activo':'b-baja'}">${escHtml(e.estado)}</span></td>
      <td><button class="btn btn-gray btn-xs" onclick="openModalEmpleado(${e.id})">✏️</button></td>
    </tr>`).join('') + '</tbody></table>';
}

let _empEditId = null;

async function openModalEmpleado(id=null){
  _empEditId = id;
  let emp = {};
  if(id) emp = await api(`/api/empleados/${id}`) || {};
  // Escapado para meter el valor dentro de un atributo value="..." o de un
  // textarea: sin esto, un dato con comillas (ej. una dirección) rompe el
  // HTML del formulario, y un dato hostil podría inyectar HTML/JS.
  const v = (k) => escAttr(emp[k] || '');

  const sel = (id_, opts, val) =>
    `<select id="${id_}">${opts.map(o=>`<option ${val===o?'selected':''}>${o}</option>`).join('')}</select>`;

  let body = `
    <div class="form-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
      <label>Legajo<input id="emp-legajo" value="${v('legajo')}"></label>
      <label>Nombre completo *<input id="emp-nombre" value="${v('nombre')}"></label>
      <label>DNI<input id="emp-dni" value="${v('dni')}"></label>
      <label>CUIL<input id="emp-cuil" value="${v('cuil')}"></label>
      <label>Fecha nacimiento<input id="emp-fecha_nacimiento" type="date" value="${v('fecha_nacimiento')}"></label>
      <label>Teléfono<input id="emp-telefono" value="${v('telefono')}"></label>
      <label>Email<input id="emp-email" value="${v('email')}"></label>
      <label>Dirección<input id="emp-direccion" value="${v('direccion')}"></label>
      <label>Localidad<input id="emp-localidad" value="${v('localidad')}"></label>
      <label>Contacto emergencia<input id="emp-contacto_emergencia" value="${v('contacto_emergencia')}"></label>
      <label>Tel. emergencia<input id="emp-tel_emergencia" value="${v('tel_emergencia')}"></label>
      <label>Puesto<input id="emp-puesto" value="${v('puesto')}"></label>
      <label>Área${sel('emp-area',['Técnica','Administración','Ventas','Gerencia','Depósito'],v('area'))}</label>
      <label>Fecha ingreso<input id="emp-fecha_ingreso" type="date" value="${v('fecha_ingreso')}"></label>
      <label>Tipo contrato${sel('emp-tipo_contrato',['Efectivo','Temporal','Monotributista','Pasantía'],v('tipo_contrato'))}</label>
      <label>Jornada<input id="emp-jornada" value="${v('jornada')}" placeholder="Completa / Media"></label>
      <label>Categoría<input id="emp-categoria" value="${v('categoria')}"></label>
      <label>Obra social<input id="emp-obra_social" value="${v('obra_social')}"></label>
      <label>ART<input id="emp-art" value="${v('art')}"></label>
      <label>Usuario sistema<input id="emp-username_sistema" value="${v('username_sistema')}" placeholder="login NetAdmin"></label>
      <label>Cód. técnico (ERP)<input id="emp-codtecnico" value="${v('codtecnico')}" placeholder="ej: LPEREZ"></label>
      <label>Cód. agente (ERP)<input id="emp-codagente" value="${v('codagente')}" placeholder="ej: 248"></label>
      <label>Estado${sel('emp-estado',['activo','licencia','baja'],v('estado')||'activo')}</label>
    </div>
    <div style="margin-top:.7rem;border-top:1px solid var(--brd);padding-top:.7rem">
      <b>🏖 Vacaciones</b>
      ${id && emp.vacaciones ? `
        <div style="display:flex;gap:1rem;margin:.5rem 0;flex-wrap:wrap">
          <div style="background:var(--card);border-radius:8px;padding:.5rem .8rem;text-align:center;min-width:90px">
            <div style="font-size:1.4rem;font-weight:800;color:#2e7d32">${emp.vacaciones.disponibles}</div>
            <div style="font-size:.7rem;color:var(--txt2)">Disponibles</div>
          </div>
          <div style="background:var(--card);border-radius:8px;padding:.5rem .8rem;text-align:center;min-width:80px">
            <div style="font-size:1.1rem;font-weight:700">${emp.vacaciones.tomados_este_anio}</div>
            <div style="font-size:.7rem;color:var(--txt2)">Tomados ${new Date().getFullYear()}</div>
          </div>
        </div>` : ''}
      <div class="form-grid">
        <label>Días anuales<input id="emp-dias_vacaciones_anuales" type="number" min="0" value="${v('dias_vacaciones_anuales')||0}"></label>
        <label>Días acumulados (años anteriores)<input id="emp-dias_vacaciones_acumulados" type="number" min="0" value="${v('dias_vacaciones_acumulados')||0}"></label>
      </div>
      <small style="color:var(--txt2)">Los días tomados se descuentan solos al cargar una novedad de tipo "vacaciones".</small>
    </div>
    <label style="display:block;margin-top:.5rem">Observaciones<textarea id="emp-observaciones" rows="2" style="width:100%">${v('observaciones')}</textarea></label>
  `;

  if(id && emp.novedades){
    body += `<div style="margin-top:1rem;border-top:1px solid var(--brd);padding-top:.7rem">
      <b>📋 Novedades / Licencias</b>
      <button class="btn btn-gray btn-xs" style="margin-left:.5rem" onclick="agregarNovedad(${id})">+ Agregar</button>
      <div style="margin-top:.5rem">
        ${emp.novedades.length ? emp.novedades.map(n=>`
          <div style="font-size:.8rem;border-bottom:1px solid var(--brd);padding:.3rem 0;display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem">
            <div>
              <b>${escHtml(n.tipo)||'—'}</b> · ${escHtml(n.fecha_desde)} → ${escHtml(n.fecha_hasta)} ${n.dias?(Number(n.dias)===0.5?'(medio día)':`(${escHtml(n.dias)} días)`):''}
              ${n.periodo && (n.tipo||'').toLowerCase().includes('vacacion')?`<span style="background:var(--tint-verde,#e8f5e9);color:#2e7d32;border-radius:4px;padding:0 .35rem;font-size:.68rem;font-weight:600;margin-left:.3rem">Período ${escHtml(n.periodo)}</span>`:''}
              ${n.motivo?`<br><small style="color:var(--txt2)">${escHtml(n.motivo)}</small>`:''}
            </div>
            <div style="flex-shrink:0;display:flex;gap:.25rem">
              ${(n.tipo||'').toLowerCase().includes('vacacion') && n.estado==='autorizada' ? `<button class="btn btn-gray btn-xs" title="Comprobante PDF" onclick="descargarComprobanteVacaciones(${n.id})">📄</button>` : ''}
              <button class="btn btn-gray btn-xs" onclick="editarNovedad(${id},${n.id},'${escJs(n.tipo)}','${n.fecha_desde||''}','${n.fecha_hasta||''}','${escJs(n.motivo)}',${n.periodo||'null'},${n.dias||'null'})">✏️</button>
            </div>
          </div>`).join('') : '<small style="color:var(--txt2)">Sin novedades</small>'}
      </div>
    </div>`;
  }

  // Días de vacaciones por período (asignación de RRHH)
  if(id){
    body += `<div style="margin-top:1rem;border-top:1px solid var(--brd);padding-top:.7rem">
      <b>🏖 Días de vacaciones por período</b>
      <div id="emp-vac-periodos" style="margin-top:.5rem"><small style="color:var(--txt2)">Cargando…</small></div>
      <div style="display:flex;gap:.4rem;align-items:flex-end;margin-top:.5rem;flex-wrap:wrap">
        <div><label style="display:block;font-size:.72rem;color:var(--txt2)">Período</label>
          <input type="number" id="emp-vac-nuevo-periodo" style="width:90px;padding:.4rem;border:1px solid var(--brd);border-radius:6px" placeholder="2025"></div>
        <div><label style="display:block;font-size:.72rem;color:var(--txt2)">Días</label>
          <input type="number" step="0.5" id="emp-vac-nuevo-dias" style="width:80px;padding:.4rem;border:1px solid var(--brd);border-radius:6px" placeholder="14"></div>
        <button class="btn btn-prim btn-xs" onclick="asignarPeriodoVac(${id})">Asignar / actualizar</button>
      </div>
      <small style="color:var(--txt2);display:block;margin-top:.3rem">El empleado verá estos días como disponibles, separados por período.</small>
    </div>`;
  }

  document.getElementById('emp-modal-title').textContent = id ? 'Editar empleado' : 'Nuevo empleado';
  document.getElementById('emp-modal-body').innerHTML = body;
  document.getElementById('emp-modal-save').onclick = guardarEmpleado;
  document.getElementById('modal-empleado').style.display = 'flex';
  if(id) cargarPeriodosVac(id);
}

async function cargarPeriodosVac(empId){
  const cont = document.getElementById('emp-vac-periodos');
  if(!cont) return;
  const r = await api(`/api/empleados/${empId}/vacaciones_periodos`);
  const lista = (r && r.por_periodo) || [];
  if(!lista.length){ cont.innerHTML = '<small style="color:var(--txt2)">Sin períodos asignados. Cargá el primero abajo.</small>'; return; }
  cont.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:.8rem">
    <thead><tr style="text-align:left;color:var(--txt2);border-bottom:1px solid var(--brd)">
      <th style="padding:.2rem 0">Período</th><th>Asignados</th><th>Tomados</th><th>Pend.</th><th>Disp.</th><th></th></tr></thead>
    <tbody>${lista.map(p=>`<tr style="border-bottom:1px solid var(--brd)">
      <td style="padding:.25rem 0"><b>${p.periodo}</b></td><td>${p.asignados}</td>
      <td>${p.tomados}</td><td>${p.pendientes}</td>
      <td><b style="color:${p.disponibles<0?'#c62828':'#2e7d32'}">${p.disponibles}</b></td>
      <td style="text-align:right"><button class="btn btn-gray btn-xs" title="Editar" onclick="document.getElementById('emp-vac-nuevo-periodo').value=${p.periodo};document.getElementById('emp-vac-nuevo-dias').value=${p.asignados}">✏️</button>
        <button class="btn btn-rj btn-xs" title="Quitar" onclick="quitarPeriodoVac(${empId},${p.periodo})">✕</button></td>
    </tr>`).join('')}</tbody></table>`;
}

async function asignarPeriodoVac(empId){
  const periodo = parseInt(document.getElementById('emp-vac-nuevo-periodo').value);
  const dias = parseFloat(document.getElementById('emp-vac-nuevo-dias').value);
  if(!periodo || isNaN(dias)){ alert('Indicá período y días (los días pueden ser 0,5)'); return; }
  const r = await api(`/api/empleados/${empId}/vacaciones_periodos`,'POST',{periodo, dias_asignados:dias});
  if(r && r.ok){
    document.getElementById('emp-vac-nuevo-periodo').value='';
    document.getElementById('emp-vac-nuevo-dias').value='';
    cargarPeriodosVac(empId);
  } else alert('Error: '+(r&&r.error?r.error:'no se pudo asignar'));
}

async function quitarPeriodoVac(empId, periodo){
  if(!confirm(`¿Quitar la asignación del período ${periodo}?`)) return;
  const r = await api(`/api/empleados/${empId}/vacaciones_periodos/${periodo}`,'DELETE');
  if(r && r.ok) cargarPeriodosVac(empId);
}

async function guardarEmpleado(){
  const data = {};
  ['legajo','nombre','dni','cuil','fecha_nacimiento','telefono','email','direccion',
   'localidad','contacto_emergencia','tel_emergencia','puesto','area','fecha_ingreso',
   'tipo_contrato','jornada','categoria','obra_social','art','username_sistema',
   'codtecnico','codagente','estado','observaciones',
   'dias_vacaciones_anuales','dias_vacaciones_acumulados'].forEach(k=>{
    const el = document.getElementById('emp-'+k);
    if(el) data[k] = el.value;
  });
  if(!data.nombre){ alert('El nombre es obligatorio'); return; }
  const r = _empEditId
    ? await api(`/api/empleados/${_empEditId}`, 'PUT', data)
    : await api('/api/empleados', 'POST', data);
  if(r && r.ok){ closeModal('modal-empleado'); loadRRHH(); }
  else { alert('Error al guardar'); }
}

let _novEmpId = null;  // empleado al que pertenece la novedad en edición

function _poblarPeriodoNov(sel_periodo){
  const sel = document.getElementById('nov-periodo');
  if(!sel) return;
  const y = new Date().getFullYear();
  const anios = [y+1, y, y-1, y-2, y-3];
  const val = sel_periodo || y;
  sel.innerHTML = anios.map(a=>`<option value="${a}" ${a==val?'selected':''}>Período ${a}</option>`).join('');
}
function _toggleNovPeriodo(){
  const tipo = (document.getElementById('nov-tipo').value||'').toLowerCase();
  const wrap = document.getElementById('nov-periodo-wrap');
  if(wrap) wrap.style.display = tipo.includes('vacacion') ? '' : 'none';
}

function agregarNovedad(empId){
  _novEmpId = empId;
  document.getElementById('nov-id').value = '';
  document.getElementById('nov-emp-id').value = empId;
  document.getElementById('nov-modal-title').textContent = 'Nueva novedad';
  document.getElementById('nov-tipo').value = 'vacaciones';
  document.getElementById('nov-desde').value = '';
  document.getElementById('nov-hasta').value = '';
  document.getElementById('nov-motivo').value = '';
  document.getElementById('nov-dias-lbl').textContent = '—';
  const med0 = document.getElementById('nov-medio'); if(med0) med0.checked = false;
  _poblarPeriodoNov();
  _toggleNovPeriodo();
  document.getElementById('nov-modal-del').style.display = 'none';
  document.getElementById('modal-novedad').style.display = 'flex';
}

function editarNovedad(empId, nid, tipo, desde, hasta, motivo, periodo, dias){
  _novEmpId = empId;
  document.getElementById('nov-id').value = nid;
  document.getElementById('nov-emp-id').value = empId;
  document.getElementById('nov-modal-title').textContent = 'Editar novedad';
  document.getElementById('nov-tipo').value = tipo || 'vacaciones';
  document.getElementById('nov-desde').value = desde || '';
  document.getElementById('nov-hasta').value = hasta || '';
  document.getElementById('nov-motivo').value = motivo || '';
  const med = document.getElementById('nov-medio'); if(med) med.checked = (Number(dias) === 0.5);
  _poblarPeriodoNov(periodo);
  _toggleNovPeriodo();
  document.getElementById('nov-modal-del').style.display = 'block';
  calcDiasNovedad();
  document.getElementById('modal-novedad').style.display = 'flex';
}

function calcDiasNovedad(){
  const medio = document.getElementById('nov-medio');
  const lbl = document.getElementById('nov-dias-lbl');
  const hastaWrap = document.getElementById('nov-hasta');
  if(medio && medio.checked){
    lbl.textContent = '0,5 día';
    if(hastaWrap) hastaWrap.closest('div').style.opacity = '.5';
    return;
  }
  if(hastaWrap) hastaWrap.closest('div').style.opacity = '';
  const desde = document.getElementById('nov-desde').value;
  const hasta = document.getElementById('nov-hasta').value;
  if(desde && hasta){
    const dias = Math.round((new Date(hasta) - new Date(desde))/86400000) + 1;
    lbl.textContent = dias > 0 ? `${dias} día${dias>1?'s':''}` : 'Fechas inválidas';
  } else {
    lbl.textContent = '—';
  }
}

async function guardarNovedad(){
  const nid = document.getElementById('nov-id').value;
  const empId = document.getElementById('nov-emp-id').value;
  const tipo = document.getElementById('nov-tipo').value;
  const desde = document.getElementById('nov-desde').value;
  let hasta = document.getElementById('nov-hasta').value;
  const motivo = document.getElementById('nov-motivo').value;
  const medio = !!(document.getElementById('nov-medio') && document.getElementById('nov-medio').checked);
  if(!desde){ alert('La fecha "Desde" es obligatoria'); return; }
  let dias = null;
  if(medio){ hasta = desde; dias = 0.5; }
  else if(desde && hasta) dias = Math.round((new Date(hasta) - new Date(desde))/86400000) + 1;
  const periodo = tipo.toLowerCase().includes('vacacion') ? ((document.getElementById('nov-periodo')||{}).value || null) : null;
  const data = {tipo, fecha_desde:desde, fecha_hasta:hasta, dias, motivo, periodo};
  const r = nid
    ? await api(`/api/novedades/${nid}`, 'PUT', data)
    : await api(`/api/empleados/${empId}/novedades`, 'POST', data);
  if(r && r.ok){
    closeModal('modal-novedad');
    // Si el modal de empleado estaba abierto, refrescarlo
    const modalEmp = document.getElementById('modal-empleado');
    if(modalEmp && modalEmp.style.display !== 'none'){
      openModalEmpleado(parseInt(empId));
    }
    if(typeof loadCalendarioAusencias === 'function') loadCalendarioAusencias();
  } else {
    alert('No se pudo guardar la novedad');
  }
}

async function eliminarNovedad(){
  const nid = document.getElementById('nov-id').value;
  const empId = document.getElementById('nov-emp-id').value;
  if(!nid) return;
  if(!await confirmar('¿Eliminar esta novedad?')) return;
  const r = await api(`/api/novedades/${nid}`, 'DELETE');
  if(r && r.ok){
    closeModal('modal-novedad');
    const modalEmp = document.getElementById('modal-empleado');
    if(modalEmp && modalEmp.style.display !== 'none'){
      openModalEmpleado(parseInt(empId));
    }
    if(typeof loadCalendarioAusencias === 'function') loadCalendarioAusencias();
  } else {
    alert('No se pudo eliminar');
  }
}

// ════════════════════════════════════════════════════════
// CALENDARIO DE AUSENCIAS
// ════════════════════════════════════════════════════════
let _rrhhMesActual = null;  // 'YYYY-MM'

function _mesISO(offset=0){
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + offset);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
}

async function loadCalendarioAusencias(){
  if(!_rrhhMesActual) _rrhhMesActual = _mesISO(0);
  const data = await api(`/api/empleados/ausencias?mes=${_rrhhMesActual}`);
  if(!data) return;
  renderCalendarioAusencias(data);
}

function cambiarMesAusencias(delta){
  const [y,m] = (_rrhhMesActual || _mesISO(0)).split('-').map(Number);
  const d = new Date(y, m-1+delta, 1);
  _rrhhMesActual = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
  loadCalendarioAusencias();
}

function renderCalendarioAusencias(data){
  const cont = document.getElementById('rrhh-calendario');
  const lbl = document.getElementById('rrhh-cal-mes');
  if(!cont) return;
  const [y, m] = data.mes.split('-').map(Number);
  const nombresMes = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
  if(lbl) lbl.textContent = `${nombresMes[m]} ${y}`;

  const diasMes = new Date(y, m, 0).getDate();
  const primerDia = new Date(y, m-1, 1).getDay(); // 0=domingo

  // Colores por tipo de ausencia
  const colorTipo = (t) => {
    const tl = (t||'').toLowerCase();
    if(tl.includes('vacacion')) return '#2e7d32';
    if(tl.includes('licencia')) return '#1565c0';
    if(tl.includes('ausencia')) return '#e65100';
    if(tl.includes('suspen')) return '#c62828';
    return '#6a1b9a';
  };

  // Mapa día -> lista de ausencias activas ese día
  const porDia = {};
  for(const a of data.ausencias){
    const desde = new Date(a.fecha_desde + 'T00:00:00');
    const hasta = a.fecha_hasta ? new Date(a.fecha_hasta + 'T00:00:00') : desde;
    for(let dia=1; dia<=diasMes; dia++){
      const fecha = new Date(y, m-1, dia);
      if(fecha >= desde && fecha <= hasta){
        (porDia[dia] = porDia[dia] || []).push(a);
      }
    }
  }

  // Grilla del calendario
  let celdas = '';
  const diasSemana = ['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'];
  celdas += diasSemana.map(d=>`<div style="font-weight:700;font-size:.7rem;text-align:center;color:var(--txt2);padding:4px">${d}</div>`).join('');
  // Espacios vacíos antes del día 1
  for(let i=0;i<primerDia;i++) celdas += '<div></div>';
  for(let dia=1; dia<=diasMes; dia++){
    const aus = porDia[dia] || [];
    const chips = aus.slice(0,3).map(a=>
      `<div onclick="editarNovedad(${a.empleado_id},${a.id},'${escJs(a.tipo)}','${a.fecha_desde||''}','${a.fecha_hasta||''}','${escJs(a.motivo)}')" style="font-size:.6rem;background:${colorTipo(a.tipo)};color:#fff;border-radius:3px;padding:1px 3px;margin-top:1px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;cursor:pointer" title="${escAttr(a.empleado)}: ${escAttr(a.tipo)} (clic para editar)">${escHtml((a.empleado||'').split(' ')[0])}</div>`
    ).join('');
    const mas = aus.length>3 ? `<div style="font-size:.55rem;color:var(--txt2)">+${aus.length-3} más</div>` : '';
    celdas += `<div style="border:1px solid var(--brd);border-radius:5px;min-height:62px;padding:2px;background:${aus.length?'var(--surf2)':'var(--card)'}">
      <div style="font-size:.7rem;font-weight:600;color:var(--txt2)">${dia}</div>
      ${chips}${mas}
    </div>`;
  }

  // Leyenda
  const leyenda = `<div style="display:flex;gap:.8rem;flex-wrap:wrap;margin-top:.6rem;font-size:.72rem;color:var(--txt2)">
    <span><span style="display:inline-block;width:10px;height:10px;background:#2e7d32;border-radius:2px"></span> Vacaciones</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:#1565c0;border-radius:2px"></span> Licencia</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:#e65100;border-radius:2px"></span> Ausencia</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:#c62828;border-radius:2px"></span> Suspensión</span>
  </div>`;

  if(!data.ausencias.length){
    cont.innerHTML = `<div style="color:#888;padding:1rem;text-align:center">Sin ausencias registradas en ${nombresMes[m]} ${y}</div>` +
      `<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px">${celdas}</div>` + leyenda;
  } else {
    cont.innerHTML = `<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px">${celdas}</div>` + leyenda;
  }
}

// ════════════════════════════════════════════════════════
// SOLICITUDES DE VACACIONES PENDIENTES (autorización RRHH)
// ════════════════════════════════════════════════════════
async function loadSolicitudesPendientes(){
  const data = await api('/api/novedades/pendientes');
  const card = document.getElementById('rrhh-solicitudes-card');
  const cont = document.getElementById('rrhh-solicitudes');
  if(!cont) return;
  if(!data || !data.length){
    if(card) card.style.display = 'none';
    return;
  }
  if(card) card.style.display = 'block';
  cont.innerHTML = data.map(s=>`
    <div style="display:flex;align-items:center;gap:.6rem;padding:.5rem;border:1px solid #ffe0b2;background:var(--tint-ambar);border-radius:8px;margin-bottom:.4rem">
      <div style="flex:1">
        <b>${escHtml(s.empleado)}</b> <small style="color:var(--txt2)">${escHtml(s.area)}</small><br>
        <span style="font-size:.85rem">🏖 ${escHtml(s.fecha_desde)} → ${escHtml(s.fecha_hasta)} ${s.dias?`(${escHtml(s.dias)} días)`:''}</span>
        ${s.motivo?`<br><small style="color:var(--txt2)">${s.motivo}</small>`:''}
      </div>
      <button class="btn btn-vd btn-xs" onclick="autorizarSolicitud(${s.id},'autorizar')">✓ Autorizar</button>
      <button class="btn btn-rj btn-xs" onclick="autorizarSolicitud(${s.id},'rechazar')">✕ Rechazar</button>
    </div>`).join('');
}

async function autorizarSolicitud(nid, accion){
  const txt = accion==='autorizar' ? 'autorizar' : 'rechazar';
  if(!await confirmar(`¿Seguro que querés ${txt} esta solicitud?`)) return;
  const r = await api(`/api/novedades/${nid}/autorizar`, 'POST', {accion});
  if(r && r.ok){
    loadSolicitudesPendientes();
    if(typeof loadCalendarioAusencias === 'function') loadCalendarioAusencias();
    // Si se autorizó, ofrecer el comprobante PDF de notificación
    if(accion === 'autorizar' && r.estado === 'autorizada'){
      if(await confirmar('Solicitud autorizada. ¿Generar el comprobante de notificación (PDF) para firmar?')){
        descargarComprobanteVacaciones(nid);
      }
    }
  }
}

function descargarComprobanteVacaciones(nid){
  // Abre el PDF en una pestaña nueva (se descarga por el Content-Disposition)
  window.open(`/api/novedades/${nid}/comprobante`, '_blank');
}

// ── Historial de vacaciones y ausencias ──
async function loadAniosAusencias(){
  const anios = await api('/api/rrhh/anios-ausencias');
  const sel = document.getElementById('hist-anio');
  if(!sel || !anios) return;
  const actual = sel.value;
  sel.innerHTML = '<option value="">Todos los años</option>' +
    anios.map(a=>`<option value="${a}">${a}</option>`).join('');
  sel.value = actual;
}

async function loadHistorialAusencias(){
  const cont = document.getElementById('rrhh-historial');
  if(!cont) return;
  const anio = document.getElementById('hist-anio')?.value || '';
  const tipo = document.getElementById('hist-tipo')?.value || '';
  const estado = document.getElementById('hist-estado')?.value || '';
  const params = new URLSearchParams();
  if(anio) params.set('anio', anio);
  if(tipo) params.set('tipo', tipo);
  if(estado) params.set('estado', estado);
  const d = await api('/api/rrhh/historial-ausencias?' + params.toString());
  if(!d || !d.ausencias){ cont.innerHTML = '<div style="color:#888">No se pudo cargar</div>'; return; }
  if(!d.ausencias.length){
    cont.innerHTML = '<div style="color:#888;padding:.5rem">Sin registros para los filtros elegidos</div>';
    return;
  }
  const colorEstado = e => ({autorizada:'#2e7d32', pendiente:'#e65100', rechazada:'#c62828'}[e] || '#757575');
  const filas = d.ausencias.map(a=>{
    const esVac = (a.tipo||'').toLowerCase().includes('vacacion');
    const btnPdf = (esVac && a.estado==='autorizada')
      ? `<button class="btn btn-gray btn-xs" title="Comprobante PDF" onclick="descargarComprobanteVacaciones(${a.id})">📄</button>` : '';
    return `<tr style="border-bottom:1px solid var(--brd)">
      <td style="padding:.4rem .5rem"><b>${escHtml(a.empleado_nombre)||'—'}</b>${a.empleado_legajo?` <span style="color:#999">#${escHtml(a.empleado_legajo)}</span>`:''}</td>
      <td style="padding:.4rem .5rem">${escHtml(a.tipo)||'—'}</td>
      <td style="padding:.4rem .5rem">${escHtml(a.fecha_desde)||'—'} → ${escHtml(a.fecha_hasta)||'—'}</td>
      <td style="padding:.4rem .5rem;text-align:center">${escHtml(a.dias)||'—'}</td>
      <td style="padding:.4rem .5rem"><span style="color:${colorEstado(a.estado)};font-weight:600">●</span> ${escHtml(a.estado)||'—'}</td>
      <td style="padding:.4rem .5rem;font-size:.8rem">${escHtml(a.autorizada_por_nombre)||'—'}</td>
      <td style="padding:.4rem .5rem;text-align:right">${btnPdf}</td>
    </tr>`;
  }).join('');
  cont.innerHTML = `
    <div style="font-size:.82rem;color:var(--txt2);margin-bottom:.5rem">
      ${d.total} registro(s) · <b style="color:#2e7d32">${d.total_dias_autorizados} días autorizados</b> en total
    </div>
    <div class="tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:.85rem">
      <thead><tr style="background:var(--card)">
        <th style="text-align:left;padding:.4rem .5rem">Empleado</th>
        <th style="text-align:left;padding:.4rem .5rem">Tipo</th>
        <th style="text-align:left;padding:.4rem .5rem">Período</th>
        <th style="text-align:center;padding:.4rem .5rem">Días</th>
        <th style="text-align:left;padding:.4rem .5rem">Estado</th>
        <th style="text-align:left;padding:.4rem .5rem">Autorizó</th>
        <th style="padding:.4rem .5rem"></th>
      </tr></thead>
      <tbody>${filas}</tbody>
    </table></div>`;
}

// ── Guardias de sábado ──
let _guardiaEmpleados = [];

async function loadGuardias(){
  const cont = document.getElementById('guardias-list');
  if(!cont) return;
  const areaSel = document.getElementById('guardia-area');
  const area = areaSel?.value || 'Mesa de Ayuda';
  // Selector de año: se puebla una vez (año actual y siguiente)
  const anioSel = document.getElementById('guardia-anio');
  const anioActual = new Date().getFullYear();
  if(anioSel && !anioSel.options.length){
    [anioActual, anioActual+1].forEach(a=>{
      const o=document.createElement('option'); o.value=a; o.textContent=a; anioSel.appendChild(o);
    });
  }
  const anio = parseInt(anioSel?.value || anioActual);
  // Año actual: desde hoy. Otro año: completo (enero a diciembre).
  const desde = (anio===anioActual) ? new Date().toISOString().slice(0,10) : `${anio}-01-01`;
  const hasta = `${anio}-12-31`;
  if(!_guardiaEmpleados.length){
    _guardiaEmpleados = await api('/api/empleados') || [];
  }
  const d = await api(`/api/guardias?area=${encodeURIComponent(area)}&desde=${desde}&hasta=${hasta}`);
  if(!d){ cont.innerHTML = '<div style="color:#888">No se pudo cargar</div>'; return; }

  const genWrap = document.getElementById('guardias-generar-wrap');
  // Usuario sin vínculo a empleado: aviso claro
  if(d.sin_vinculo){
    cont.innerHTML = `<div style="padding:1rem;background:var(--tint-ambar);border:1px solid #ffe082;border-radius:8px;color:#7a5c00">⚠ ${d.mensaje || 'Tu usuario no está vinculado a un empleado.'}</div>`;
    if(areaSel) areaSel.style.display = 'none';
    if(genWrap) genWrap.style.display = 'none';
    return;
  }

  const editable = !!d.editable;
  if(areaSel) areaSel.style.display = d.es_admin ? '' : 'none';
  if(genWrap) genWrap.style.display = editable ? 'block' : 'none';

  const opts = (sel) => '<option value="">— sin asignar —</option>' +
    _guardiaEmpleados.map(e=>`<option value="${e.id}" ${e.id==sel?'selected':''}>${e.nombre}</option>`).join('');

  const filas = d.guardias.map(g=>{
    const fechaTxt = _fmtFechaGuardia(g.fecha);
    const alertaTit = [
      g.conflicto ? `<span title="En ${g.conflicto} ese día" style="color:#c62828;font-weight:700">⚠</span>` : '',
      g.cumple ? `<span title="Es el CUMPLEAÑOS del asignado (la política pide no asignar ese día)" style="font-weight:700">🎂</span>` : '',
      g.consecutiva ? `<span title="Guardia CONSECUTIVA: la misma persona el sábado anterior o siguiente" style="font-weight:700">🔁</span>` : '',
    ].filter(Boolean).join(' ');
    const alertaRef = [
      g.conflicto_refuerzo ? `<span title="En ${g.conflicto_refuerzo} ese día" style="color:#c62828;font-weight:700">⚠</span>` : '',
      g.cumple_refuerzo ? `<span title="Es el CUMPLEAÑOS del refuerzo" style="font-weight:700">🎂</span>` : '',
    ].filter(Boolean).join(' ');
    const rowBg = (g.conflicto || g.cumple || g.consecutiva) ? 'background:var(--card)' : '';
    const celdaTitular = editable
      ? `<select onchange="guardarGuardia('${g.fecha}', this.value, null)" style="padding:.3rem;border:1px solid var(--brd);border-radius:5px;max-width:160px">${opts(g.empleado_id)}</select> ${alertaTit}`
      : `${g.empleado_nombre || '<span style="color:#bbb">— sin asignar —</span>'} ${alertaTit}`;
    const celdaRefuerzo = editable
      ? `<select onchange="guardarGuardia('${g.fecha}', null, this.value)" style="padding:.3rem;border:1px solid var(--brd);border-radius:5px;max-width:160px">${opts(g.refuerzo_empleado_id)}</select> ${alertaRef}`
      : `${g.refuerzo_nombre || '<span style="color:#ccc">—</span>'} ${alertaRef}`;
    return `<tr style="border-bottom:1px solid var(--brd);${rowBg}">
      <td style="padding:.4rem .5rem;white-space:nowrap"><b>${fechaTxt}</b></td>
      <td style="padding:.4rem .5rem">${celdaTitular}</td>
      <td style="padding:.4rem .5rem">${celdaRefuerzo}</td>
    </tr>`;
  }).join('');

  const tituloArea = editable ? '' : `<div style="font-size:.82rem;color:var(--txt2);margin-bottom:.4rem">Guardias de tu área: <b>${d.area}</b></div>`;

  // Panel de equidad anual (política: distribución pareja de sábados)
  let panelEquidad = '';
  if(d.equidad && d.equidad.length){
    const nums = d.equidad.map(e=>e.sabados);
    const desbalance = Math.max(...nums) - Math.min(...nums);
    const detalle = d.equidad.map(e=>`<b>${e.nombre||'?'}</b> (${e.sabados})`).join(' · ');
    const alertaEq = (d.equidad.length > 1 && desbalance > 2)
      ? ` <span style="color:#c62828;font-weight:600">⚠ desbalance de ${desbalance} sábados</span>` : '';
    panelEquidad = `<div style="font-size:.83rem;background:var(--card);border-radius:6px;padding:.45rem .7rem;margin-bottom:.5rem">
      📊 Distribución ${d.anio_equidad}: ${detalle}${alertaEq}</div>`;
  }
  let avisoNac = '';
  if(d.sin_fecha_nac && d.sin_fecha_nac.length){
    avisoNac = `<div style="font-size:.8rem;background:var(--tint-ambar);border:1px solid #ffe082;border-radius:6px;padding:.4rem .7rem;margin-bottom:.5rem">
      🎂 Sin fecha de nacimiento en la ficha (el aviso de cumpleaños NO puede chequearlos): <b>${d.sin_fecha_nac.join(', ')}</b> — cargarla en RRHH.</div>`;
  }

  cont.innerHTML = tituloArea + panelEquidad + avisoNac + `
    <div class="tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:.86rem">
      <thead><tr style="background:var(--card)">
        <th style="text-align:left;padding:.4rem .5rem">Sábado</th>
        <th style="text-align:left;padding:.4rem .5rem">Titular de guardia</th>
        <th style="text-align:left;padding:.4rem .5rem">Refuerzo</th>
      </tr></thead>
      <tbody>${filas}</tbody>
    </table></div>`;
}

function _fmtFechaGuardia(f){
  const meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  const [y,m,d] = f.split('-');
  return `${d}-${meses[parseInt(m)-1]}`;
}

async function guardarGuardia(fecha, empId, refId){
  const area = document.getElementById('guardia-area')?.value || 'Mesa de Ayuda';
  const d = await api('/api/guardias?area=' + encodeURIComponent(area) + '&desde=' + fecha + '&hasta=' + fecha);
  const actual = (d && d.guardias && d.guardias[0]) || {};
  const payload = {
    fecha, area,
    empleado_id: empId !== null ? (empId || null) : (actual.empleado_id || null),
    refuerzo_empleado_id: refId !== null ? (refId || null) : (actual.refuerzo_empleado_id || null),
  };
  const r = await api('/api/guardias', 'POST', payload);
  if(r && r.ok){
    const avisos = [];
    if(r.conflicto) avisos.push(`está de ${r.conflicto} ese día`);
    if(r.cumple) avisos.push('es su CUMPLEAÑOS (la política pide no asignar ese día)');
    if(r.consecutiva) avisos.push('queda con guardia CONSECUTIVA (sábado anterior o siguiente)');
    if(avisos.length){
      alert(`⚠ Atención con el ${_fmtFechaGuardia(fecha)}: la persona asignada ${avisos.join(' y ')}.\nLa guardia se guardó igual, pero revisá si corresponde.`);
    }
    loadGuardias();
  }
}

// ── Generador de rotación ──
let _genRotacion = [];  // lista de {id, nombre} en orden

function openModalGenerarGuardias(){
  _genRotacion = [];
  const sel = document.getElementById('gen-add-emp');
  if(sel) sel.innerHTML = _guardiaEmpleados.map(e=>`<option value="${e.id}">${e.nombre}</option>`).join('');
  _renderRotacion();
  // Rango por defecto: año que viene completo
  const proxAnio = new Date().getFullYear() + 1;
  document.getElementById('gen-desde').value = `${proxAnio}-01-01`;
  document.getElementById('gen-hasta').value = `${proxAnio}-12-31`;
  document.getElementById('gen-sobrescribir').checked = false;
  document.getElementById('modal-generar-guardias').style.display = 'flex';
}

function addRotacionEmp(){
  const sel = document.getElementById('gen-add-emp');
  const id = parseInt(sel.value);
  const emp = _guardiaEmpleados.find(e=>e.id===id);
  if(emp){ _genRotacion.push({id:emp.id, nombre:emp.nombre}); _renderRotacion(); }
}

function _renderRotacion(){
  const cont = document.getElementById('gen-rotacion-list');
  if(!cont) return;
  if(!_genRotacion.length){ cont.innerHTML = '<div style="color:#999;font-size:.82rem">Sin empleados. Agregá al menos uno.</div>'; return; }
  cont.innerHTML = _genRotacion.map((e,i)=>`<div style="display:flex;align-items:center;gap:.5rem;padding:.25rem 0">
    <span style="background:var(--card);border-radius:4px;padding:.1rem .4rem;font-size:.8rem">${i+1}</span>
    <span style="flex:1">${e.nombre}</span>
    <button class="btn btn-gray btn-xs" onclick="_quitarRotacion(${i})">✕</button>
  </div>`).join('');
}

function _quitarRotacion(i){ _genRotacion.splice(i,1); _renderRotacion(); }

async function generarGuardias(){
  const desde = document.getElementById('gen-desde').value;
  const hasta = document.getElementById('gen-hasta').value;
  const area = document.getElementById('guardia-area')?.value || 'Mesa de Ayuda';
  const sobrescribir = document.getElementById('gen-sobrescribir').checked;
  if(!_genRotacion.length){ alert('Agregá al menos un empleado a la rotación.'); return; }
  if(!desde || !hasta){ alert('Definí el rango de fechas.'); return; }
  const r = await api('/api/guardias/generar', 'POST', {
    desde, hasta, area, sobrescribir,
    rotacion: _genRotacion.map(e=>e.id),
  });
  if(r && r.ok){
    let msg = `✓ ${r.asignadas} sábados asignados`;
    if(r.saltadas) msg += `, ${r.saltadas} respetados (ya cargados)`;
    if(r.conflictos && r.conflictos.length){
      const cumples = r.conflictos.filter(c=>c.tipo==='cumpleaños').length;
      const vacas = r.conflictos.length - cumples;
      if(vacas) msg += `\n⚠ ${vacas} caen en vacaciones/licencias`;
      if(cumples) msg += `\n🎂 ${cumples} caen en cumpleaños`;
      msg += `\nRevisalos en la lista (quedan marcados).`;
    }
    if(r.aviso) msg += `\n⚠ ${r.aviso}`;
    alert(msg);
    closeModal('modal-generar-guardias');
    // Saltar la vista al año generado (para ver el resultado de inmediato)
    const anioGen = (document.getElementById('gen-desde').value || '').slice(0,4);
    const anioSel = document.getElementById('guardia-anio');
    if(anioSel && anioGen && [...anioSel.options].some(o=>o.value===anioGen)){
      anioSel.value = anioGen;
    }
    loadGuardias();
  } else {
    alert(r?.error || 'Error al generar');
  }
}

/* ========================================================
   incidencias.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadIncidencias(){
  const estado=document.getElementById('inc-estado').value;
  const tipo=document.getElementById('inc-tipo').value;
  const d=await api(`/api/incidencias?estado=${estado}&tipo=${tipo}`);
  if(!d) return;
  const list=document.getElementById('inc-list');
  if(!d.length){list.innerHTML='<div class="empty">Sin incidencias para los filtros seleccionados</div>';return;}
  list.innerHTML=d.map(i=>`<div class="inc-card ${i.prioridad}" style="margin-bottom:.5rem">
    <div style="display:flex;align-items:flex-start;gap:.4rem;flex-wrap:wrap">
      <span class="badge b-${i.prioridad}">${i.prioridad.toUpperCase()}</span>
      <b>${i.titulo}</b>
      <span class="badge b-${i.estado}" style="margin-left:auto">${estadoServLabel(i.estado)}</span>
    </div>
    <div style="font-size:.78rem;color:var(--txt2);margin:.3rem 0">${i.tipo.replace(/_/g,' ')} ${i.afectados?'| Afectados: '+i.afectados:''} ${i.tecnico?'| Técnico: '+i.tecnico:''}</div>
    ${i.descripcion?`<div style="font-size:.78rem;margin-bottom:.3rem">${i.descripcion}</div>`:''}
    ${i.resolucion?`<div style="font-size:.75rem;color:var(--vd);border-top:1px solid var(--brd);padding-top:.3rem;margin-top:.3rem">✅ ${i.resolucion}</div>`:''}
    <div style="font-size:.7rem;color:var(--txt2)">Inicio: ${i.fecha_inicio?.slice(0,16)||''} ${i.fecha_cierre?'| Cierre: '+i.fecha_cierre.slice(0,16):''}</div>
    <div style="margin-top:.4rem;display:flex;gap:.3rem">
      <button class="btn btn-gray btn-xs" onclick="openModalIncidencia(${i.id})">✏️ Editar</button>
      ${i.estado==='abierta'?`<button class="btn btn-am btn-xs" onclick="cambiarEstadoInc(${i.id},'en_proceso')">▶ Procesar</button>`:''}
      ${i.estado!=='cerrada'?`<button class="btn btn-vd btn-xs" onclick="cambiarEstadoInc(${i.id},'cerrada')">✓ Cerrar</button>`:''}
      <button class="btn btn-rj btn-xs" onclick="deleteInc(${i.id})">🗑</button>
    </div>
  </div>`).join('');
}

async function cambiarEstadoInc(id,estado){
  const incs=await api('/api/incidencias');
  const inc=incs.find(x=>x.id===id);
  if(inc) await api(`/api/incidencias/${id}`,'PUT',{...inc,estado});
  loadIncidencias();
  loadDash();
}

async function deleteInc(id){
  if(!confirm('¿Eliminar esta incidencia?')) return;
  await api(`/api/incidencias/${id}`,'DELETE');
  loadIncidencias();
}

// ── Cache de scope_options para combos dependientes ──
let _incScopeOpts = null;

async function _loadIncScopeOpts(force){
  if(_incScopeOpts && !force) return _incScopeOpts;
  _incScopeOpts = await api('/api/incidencias/scope_options');
  return _incScopeOpts;
}

async function onIncObjetoTipoChange(){
  const tipo = document.getElementById('minc-objeto-tipo').value;
  document.getElementById('minc-block-torre').style.display = tipo==='torre'?'block':'none';
  document.getElementById('minc-block-naptree').style.display = (tipo==='nap'||tipo==='cdo')?'block':'none';
  document.getElementById('minc-block-cdo').style.display = tipo==='cdo'?'block':'none';
  document.getElementById('minc-block-naps').style.display = tipo==='nap'?'block':'none';
  // FIX SPRINT 2: al elegir NAP, poblar la lista YA (sin requerir que el usuario elija red/OLT primero)
  if(tipo === 'nap'){
    await _poblarNapsFiltered();
  } else if(tipo === 'cdo'){
    await _poblarCdosFiltered();
  }
}

async function onIncRedChange(){
  // Filtrar OLTs y CDOs según red elegida (UX: re-poblar selects)
  await onIncOltChange();
}

async function onIncOltChange(){
  const tipo = document.getElementById('minc-objeto-tipo').value;
  if(tipo === 'cdo'){
    await _poblarCdosFiltered();
  } else if(tipo === 'nap'){
    await _poblarNapsFiltered();
  }
}

async function _poblarCdosFiltered(){
  const opts = await _loadIncScopeOpts();
  if(!opts) return;
  const red = document.getElementById('minc-red').value;
  const olt = document.getElementById('minc-olt').value;
  const sel = document.getElementById('minc-cdo');
  let cdos = opts.cdos.filter(c => c.cdo);
  if(red) cdos = cdos.filter(c => (c.red||'') === red);
  if(olt) cdos = cdos.filter(c => (c.olt_nombre||'') === olt);
  // Deduplicar por cdo
  const seen = new Set();
  const uniq = cdos.filter(c => {
    const k = `${c.red||''}|${c.olt_nombre||''}|${c.cdo}`;
    if(seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  sel.innerHTML = '<option value="">— Seleccionar CDO —</option>' +
    uniq.map(c => `<option value="${c.cdo}" data-red="${c.red||''}" data-olt="${c.olt_nombre||''}">${c.cdo}${c.red?` (${c.red})`:''}${c.olt_nombre?` · ${c.olt_nombre}`:''}</option>`).join('');
  document.getElementById('minc-cdo-preview').textContent = '';
}

async function _poblarNapsFiltered(){
  const red = document.getElementById('minc-red').value;
  const olt = document.getElementById('minc-olt').value;
  const naps = await api('/api/naps');
  if(!naps) return;
  let filtered = naps;
  if(red) filtered = filtered.filter(n => (n.red||'') === red);
  if(olt) filtered = filtered.filter(n => (n.olt_nombre||'') === olt);
  _napsIncCache = filtered;
  _renderNapsIncSelect();
}

let _napsIncCache = [];

function _renderNapsIncSelect(){
  const q = (document.getElementById('minc-naps-q')?.value || '').trim().toLowerCase();
  let list = _napsIncCache;
  if(q){
    list = list.filter(n =>
      (n.nombre||'').toLowerCase().includes(q) ||
      (n.localidad||'').toLowerCase().includes(q) ||
      (n.cdo||'').toLowerCase().includes(q)
    );
  }
  const sel = document.getElementById('minc-naps');
  if(!sel) return;
  // Preservar selección actual
  const selectedIds = new Set([...sel.selectedOptions].map(o => parseInt(o.value)));
  sel.innerHTML = list.map(n => {
    const sel = selectedIds.has(n.id) ? ' selected' : '';
    const estIcon = n.estado==='alerta'?'⚠️':n.estado==='mantenimiento'?'🔧':n.estado==='inactivo'?'⊘':'✓';
    return `<option value="${n.id}"${sel}>${estIcon} ${n.nombre} · ${n.localidad||'—'}</option>`;
  }).join('');
  const cnt = document.getElementById('minc-naps-count');
  if(cnt) cnt.textContent = `Mostrando ${list.length} de ${_napsIncCache.length} NAPs`;
}

function filtrarNapsIncidencia(){
  _renderNapsIncSelect();
}

async function onIncCdoChange(){
  const cdo = document.getElementById('minc-cdo').value;
  const preview = document.getElementById('minc-cdo-preview');
  if(!cdo){ preview.textContent=''; return; }
  const red = document.getElementById('minc-red').value;
  const olt = document.getElementById('minc-olt').value;
  const r = await api(`/api/incidencias/naps_por_cdo?cdo=${encodeURIComponent(cdo)}&red=${encodeURIComponent(red)}&olt_nombre=${encodeURIComponent(olt)}`);
  if(r && r.length){
    preview.innerHTML = `⚠️ <b>${r.length}</b> NAP(s) van a marcarse como <b style="color:#dc3545">alerta</b>: ${r.map(n=>n.nombre).join(', ')}`;
  } else {
    preview.innerHTML = '<span style="color:#dc3545">⚠️ No se encontraron NAPs para este CDO con la red/OLT seleccionadas</span>';
  }
}

async function openModalIncidencia(id=null){
  ['minc-id','minc-titulo','minc-afectados','minc-tecnico','minc-desc','minc-resolucion'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('minc-tipo').value='otro';
  document.getElementById('minc-prioridad').value='media';
  document.getElementById('minc-estado').value='abierta';
  document.getElementById('minc-objeto-tipo').value='general';
  document.getElementById('minc-red').value='';
  document.getElementById('minc-olt').value='';
  document.getElementById('minc-cdo').value='';
  document.getElementById('minc-cdo-preview').textContent='';
  // limpiar select multi de NAPs
  const napsSel = document.getElementById('minc-naps'); if(napsSel) napsSel.innerHTML='';
  document.getElementById('minc-title').textContent=id?'Editar Incidencia':'Nueva Incidencia';

  // Poblar selector de torres
  const torres=await api('/api/torres');
  const tSel=document.getElementById('minc-torre');
  tSel.innerHTML='<option value="">Sin torre vinculada</option>';
  if(torres) torres.forEach(t=>{
    const op=document.createElement('option'); op.value=t.id;
    op.textContent=`${t.nombre} (${t.tipo||'rep.'})`;
    tSel.appendChild(op);
  });

  // Poblar combos de scope (red, olt)
  const opts = await _loadIncScopeOpts(true);
  const redSel = document.getElementById('minc-red');
  const oltSel = document.getElementById('minc-olt');
  redSel.innerHTML = '<option value="">— Seleccionar —</option>' +
    (opts?.redes||[]).map(r=>`<option value="${r.nombre}">${r.nombre}</option>`).join('');
  oltSel.innerHTML = '<option value="">— Todas —</option>' +
    (opts?.olts||[]).map(o=>`<option value="${o}">${o}</option>`).join('');

  if(id){
    const d=await api('/api/incidencias');
    const i=d.find(x=>x.id===id);
    if(i){
      document.getElementById('minc-id').value=i.id;
      document.getElementById('minc-titulo').value=i.titulo;
      document.getElementById('minc-tipo').value=i.tipo;
      document.getElementById('minc-prioridad').value=i.prioridad;
      document.getElementById('minc-estado').value=i.estado;
      document.getElementById('minc-tecnico').value=i.tecnico||'';
      document.getElementById('minc-afectados').value=i.afectados||'';
      document.getElementById('minc-desc').value=i.descripcion||'';
      document.getElementById('minc-resolucion').value=i.resolucion||'';
      if(i.torre_id) document.getElementById('minc-torre').value=i.torre_id;
      
      // Restaurar scope
      const ot = i.objeto_tipo || (i.torre_id ? 'torre' : 'general');
      document.getElementById('minc-objeto-tipo').value = ot;
      if(i.red) document.getElementById('minc-red').value = i.red;
      if(i.olt_nombre) document.getElementById('minc-olt').value = i.olt_nombre;
      
      onIncObjetoTipoChange();
      
      if(ot === 'cdo'){
        await _poblarCdosFiltered();
        if(i.cdo) document.getElementById('minc-cdo').value = i.cdo;
        await onIncCdoChange();
      } else if(ot === 'nap'){
        await _poblarNapsFiltered();
        try {
          const ids = JSON.parse(i.objeto_ids || '[]');
          const sel = document.getElementById('minc-naps');
          [...sel.options].forEach(o => { if(ids.includes(parseInt(o.value))) o.selected = true; });
        } catch(e){}
      }
    }
  } else {
    onIncObjetoTipoChange();
  }
  document.getElementById('modal-incidencia').style.display='flex';
}

async function saveIncidencia(){
  const id=document.getElementById('minc-id').value;
  const objetoTipo = document.getElementById('minc-objeto-tipo').value;
  const data={
    titulo:document.getElementById('minc-titulo').value,
    tipo:document.getElementById('minc-tipo').value,
    prioridad:document.getElementById('minc-prioridad').value,
    estado:document.getElementById('minc-estado').value,
    tecnico:document.getElementById('minc-tecnico').value,
    afectados:document.getElementById('minc-afectados').value,
    descripcion:document.getElementById('minc-desc').value,
    resolucion:document.getElementById('minc-resolucion').value,
    objeto_tipo: objetoTipo,
    torre_id: objetoTipo==='torre' ? (document.getElementById('minc-torre').value||null) : null,
    red: (objetoTipo==='nap'||objetoTipo==='cdo') ? document.getElementById('minc-red').value : null,
    olt_nombre: (objetoTipo==='nap'||objetoTipo==='cdo') ? document.getElementById('minc-olt').value : null,
    cdo: objetoTipo==='cdo' ? document.getElementById('minc-cdo').value : null,
  };
  if(objetoTipo === 'nap'){
    const sel = document.getElementById('minc-naps');
    data.objeto_ids = [...sel.selectedOptions].map(o => parseInt(o.value));
    if(data.objeto_ids.length === 0){
      alert('Seleccioná al menos un NAP afectado.');
      return;
    }
  }
  if(objetoTipo === 'cdo' && !data.cdo){
    alert('Seleccioná un CDO.');
    return;
  }
  if(!data.titulo.trim()){alert('El título es obligatorio');return;}
  const r=await api(id?`/api/incidencias/${id}`:'/api/incidencias',id?'PUT':'POST',data);
  if(r?.ok||r?.id){
    closeModal('modal-incidencia');
    loadIncidencias();
    loadDash();
    // Refrescar mapa de NAPs si está visible (para que aparezcan los nuevos en alerta)
    if(typeof reloadMapaNaps==='function') reloadMapaNaps();
    if(typeof loadNaps==='function') loadNaps();
    if(r.naps_afectados && r.naps_afectados.length){
      // Aviso silencioso
      console.info(`Incidencia: ${r.naps_afectados.length} NAP(s) marcado(s) como alerta`);
    }
  } else {
    alert('Error al guardar' + (r?.error?': '+r.error:''));
  }
}

// ── STOCK ──

async function loadAgenda(){
  const desde=document.getElementById('ag-desde').value;
  const hasta=document.getElementById('ag-hasta').value;
  const tecnico=document.getElementById('ag-tecnico').value;
  const d=await api(`/api/agenda?desde=${desde}&hasta=${hasta}&tecnico=${encodeURIComponent(tecnico)}`);
  if(!d) return;
  renderAgenda(d, desde, hasta);
}

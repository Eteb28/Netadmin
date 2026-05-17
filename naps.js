/* ========================================================
   naps.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadNapDatalist(){
  const naps=await api('/api/naps');
  if(!naps) return;
  napData=naps;
  document.getElementById('nap-datalist').innerHTML=naps.map(n=>`<option value="${n.nombre}">`).join('');
}

function drawTopNaps(naps) {
  const wrap = document.getElementById('top-naps-list');
  if (!wrap) return;
  if (!naps.length) {wrap.innerHTML = '<div class="empty">Sin datos</div>';return;}
  wrap.innerHTML = naps.slice(0, 5).map((n, i) => {
    const rankClass = i === 0 ? 'one' : i === 1 ? 'two' : i === 2 ? 'three' : '';
    const pctClass = n.estado_visual === 'lleno' ? 'full' : n.estado_visual === 'casi' ? 'warn' : '';
    return `<div class="top-nap-row" onclick="showNapDetail('${n.nombre.replace(/'/g,"\\'")}')">
      <div class="top-nap-rank ${rankClass}">${i+1}</div>
      <div class="top-nap-info">
        <div class="top-nap-name">${n.nombre}</div>
        <div class="top-nap-stats">${n.total}/${n.capacidad} puertos · ${n.localidad||'—'}${n.libre <= 0 ? ' · 🔴 LLENO': ''}</div>
      </div>
      <div class="top-nap-pct ${pctClass}">${n.pct}%</div>
    </div>`;
  }).join('');
}

function drawNapsAgrupadas(grupos) {
  const wrap = document.getElementById('naps-grupos-list');
  if (!wrap) return;
  setText('naps-grupos-cnt', `${grupos.length} sitios · ${grupos.reduce((s,g)=>s+g.total_naps,0)} NAPs`);

  // Banner de alertas
  const llenas = [];
  const casi = [];
  grupos.forEach(g => {
    g.naps.forEach(n => {
      if (n.libre <= 0) llenas.push(n);
      else if (n.libre <= 2) casi.push(n);
    });
  });
  let alertHtml = '';
  if (llenas.length > 0) {
    alertHtml += `<div class="alert-box err">🔴 <b>${llenas.length} NAP${llenas.length>1?'s':''} LLENA${llenas.length>1?'S':''}</b></div>`;
  }
  if (casi.length > 0) {
    alertHtml += `<div class="alert-box warn">🟡 <b>${casi.length} NAP${casi.length>1?'s':''} casi llena${casi.length>1?'s':''}</b></div>`;
  }
  document.getElementById('nap-alerts-bar').innerHTML = alertHtml;

  // Mostrar solo top 10 grupos por defecto
  wrap.innerHTML = grupos.slice(0, 15).map((g, i) => {
    const fillCls = g.pct >= 90 ? 'full' : g.pct >= 75 ? 'warn' : '';
    const colorPct = g.pct >= 90 ? 'var(--rj)' : g.pct >= 75 ? 'var(--am)' : 'var(--vd)';
    const open = i < 1 ? 'open' : ''; // primero abierto

    const napsHtml = g.naps.slice(0, 12).map(n => {
      const cls = n.libre <= 0 ? 'lleno' : n.libre <= 2 ? 'casi' : '';
      return `<div class="nap-mini ${cls}" onclick="event.stopPropagation();showNapDetail('${n.nombre.replace(/'/g,"\\'")}')">
        <div class="nap-mini-name" title="${n.nombre}">${n.nombre.split(' - ').slice(1).join(' ').replace(/CDO:/g,'CDO').replace(/NAP:/g,'NAP')||n.nombre}</div>
        <div class="nap-mini-pct">${n.pct}%</div>
        <div style="font-size:.65rem;color:var(--txt2)">${n.total}/${n.capacidad}</div>
      </div>`;
    }).join('');
    const moreNaps = g.naps.length > 12
      ? `<div style="grid-column:1/-1;text-align:center;font-size:.74rem;color:var(--txt2);padding:.3rem">... y ${g.naps.length-12} NAPs más en este sitio</div>`
      : '';

    return `<div class="nap-group ${open}">
      <div class="nap-group-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="nap-group-toggle">▶</span>
        <span class="nap-group-name">📍 ${g.nombre}</span>
        <span class="nap-group-stats">${g.total_naps} NAPs · ${g.total_ocupados}/${g.total_capacidad} puertos</span>
        <div class="nap-group-bar"><div class="nap-group-bar-fill ${fillCls}" style="width:${g.pct}%"></div></div>
        <span style="font-weight:700;color:${colorPct};font-family:monospace;min-width:38px;text-align:right">${g.pct}%</span>
      </div>
      <div class="nap-group-content">
        <div class="nap-mini-grid">${napsHtml}${moreNaps}</div>
      </div>
    </div>`;
  }).join('');

  if (grupos.length > 15) {
    wrap.innerHTML += `<div style="text-align:center;font-size:.78rem;color:var(--txt2);padding:.5rem">... y ${grupos.length-15} sitios más</div>`;
  }
}

function buildNapGrid(naps) {
  // Ya no se usa — la versión nueva usa drawNapsAgrupadas
}

const NAP_WARN = 6;

async function showNapDetail(nombre){
  const naps=await api('/api/naps');
  const n=naps.find(x=>x.nombre===nombre);
  if(!n) return;
  document.getElementById('mnapd-title').textContent=`NAP: ${n.nombre}`;
  const legend=`<div style="display:flex;gap:.8rem;font-size:.73rem;margin-bottom:.6rem">
    <span><span class="nap-dot activo" style="display:inline-block"></span> Activo</span>
    <span><span class="nap-dot suspendido" style="display:inline-block"></span> Suspendido</span>
    <span><span class="nap-dot rescision" style="display:inline-block"></span> Pte.Rescisión</span>
    <span><span class="nap-dot libre" style="display:inline-block"></span> Libre</span>
  </div>`;
  const cliRows=n.clientes.map(c=>`<tr>
    <td>${c.nombre}</td>
    <td><span class="badge b-${c.tipo_servicio}">${c.tipo_servicio}</span></td>
    <td><span class="badge b-${c.estado}">${estadoLabel(c.estado)}</span></td>
    <td><button class="btn btn-gray btn-xs" onclick="closeModal('modal-nap-detail');openModalCliente(${c.id})">✏️</button></td>
  </tr>`).join('');
  document.getElementById('mnapd-body').innerHTML=`
    ${legend}
    <div style="font-size:.82rem;margin-bottom:.5rem">
      <b>Ocupación:</b> ${n.total}/${n.capacidad} — Activos: ${n.activos||0} | Suspendidos: ${n.suspendidos||0} | Rescisión: ${n.rescision||0}
    </div>
    <div class="tbl-wrap">
      <table><thead><tr><th>Cliente</th><th>Tipo</th><th>Estado</th><th></th></tr></thead>
      <tbody>${cliRows||'<tr><td colspan="4" class="empty">Sin clientes</td></tr>'}</tbody></table>
    </div>`;
  document.getElementById('modal-nap-detail').style.display='flex';
  agregarBotonSenalEnModal(nombre);
}

async function reloadMapaNaps(){
  if(!mapaInited) return;
  removeLayer('naps');
  if(!mapaChips.naps) return;
  const data=await api('/api/naps');
  if(!data) return;
  const markers=[];
  data.forEach(n=>{
    if(!n.lat||!n.lng) return;
    const full=n.libre<=0, warn=n.total>=NAP_WARN&&n.libre>0;
    // Color del icono según estado del NAP (prioritario sobre ocupación)
    let bg, border='2px solid #fff', extraClass='';
    if(n.estado === 'alerta'){
      bg = '#dc3545';
      border = '3px solid #ff0000';
      extraClass = 'pulse-alert';
    } else if(n.estado === 'mantenimiento'){
      bg = '#ff9800';
      border = '3px solid #fb8c00';
    } else if(n.estado === 'inactivo'){
      bg = '#9e9e9e';
    } else {
      // estado 'activo' (o 'operativo' legacy)
      bg = full ? '#c62828' : warn ? '#e65100' : '#1565c0';
    }
    const icon=L.divIcon({
      className:'',
      html:`<div class="${extraClass}" style="background:${bg};color:#fff;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;border:${border};box-shadow:0 2px 6px rgba(0,0,0,.3)">${n.total}/${n.capacidad}</div>`,
      iconSize:[30,30],iconAnchor:[15,15]
    });
    let dotsHtml='';
    const nc=n.clientes||[];
    nc.slice(0,30).forEach(c=>{
      const dc=c.estado==='activo'?'var(--vd2)':c.estado==='suspendido'?'var(--am2)':'var(--rj2)';
      dotsHtml+=`<span style="background:${dc};width:10px;height:10px;border-radius:50%;display:inline-block;margin:1px" title="${c.nombre} (${c.estado})"></span>`;
    });
    let estadoTag = '';
    if(n.estado === 'alerta'){
      estadoTag = `<div style="background:#dc3545;color:#fff;padding:.15rem .4rem;border-radius:4px;font-size:.72rem;font-weight:700;margin-bottom:.3rem;display:inline-block">⚠️ ALERTA — ${nc.filter(c=>c.estado==='activo').length} cliente(s) afectado(s)</div><br>`;
    } else if(n.estado === 'mantenimiento'){
      estadoTag = `<div style="background:#ff9800;color:#fff;padding:.15rem .4rem;border-radius:4px;font-size:.72rem;font-weight:700;margin-bottom:.3rem;display:inline-block">🔧 EN MANTENIMIENTO</div><br>`;
    } else if(n.estado === 'inactivo'){
      estadoTag = `<div style="background:#9e9e9e;color:#fff;padding:.15rem .4rem;border-radius:4px;font-size:.72rem;font-weight:700;margin-bottom:.3rem;display:inline-block">⊘ INACTIVO</div><br>`;
    }
    const verBtn = `<button class="btn btn-prim btn-sm" style="margin-top:.4rem;width:100%" onclick="verAfectadosNap(${n.id})">👥 Ver afectados</button>`;
    const marker=L.marker([n.lat,n.lng],{icon}).bindPopup(`
      ${estadoTag}<b>${n.nombre}</b><br>
      Ocupación: ${n.total}/${n.capacidad} <br>
      <div style="margin:.3rem 0">${dotsHtml}</div>
      ${(n.estado==='alerta'||n.estado==='mantenimiento')?verBtn:''}
    `,{maxWidth:300});
    markers.push(marker);
  });
  mapaLayers.naps=L.layerGroup(markers).addTo(map);
}

// Modal de afectados (lista de clientes de un NAP)
async function verAfectadosNap(napId){
  const r = await api(`/api/naps/${napId}/clientes_afectados`);
  if(!r) return;
  const total = r.total;
  let html = `<div class="modal-overlay" id="modal-afectados-tmp" style="display:flex" onclick="if(event.target===this)this.remove()">
    <div class="modal" style="max-width:560px">
      <div class="modal-hd" style="background:${r.nap_estado==='alerta'?'#dc3545':'#ff9800'};color:#fff">
        <span>${r.nap_estado==='alerta'?'⚠️ Clientes afectados':'🔧 Clientes en NAP'}: ${r.nap_nombre}</span>
        <button class="modal-close" style="color:#fff" onclick="document.getElementById('modal-afectados-tmp').remove()">×</button>
      </div>
      <div class="modal-bd">
        <div style="margin-bottom:.6rem;font-weight:600">Total: ${total} cliente(s) activo(s)</div>
        <div style="max-height:50vh;overflow-y:auto">
        ${r.clientes.map(c=>{
          const nro = c.nro_cliente ? `<span class="badge b-fibra" style="font-family:monospace;margin-right:.3rem">#${c.nro_cliente}</span>` : '';
          return `<div style="padding:.5rem;border-bottom:1px solid #eee;cursor:pointer" onclick="document.getElementById('modal-afectados-tmp').remove();openModalCliente(${c.id})">
            <div>${nro}<b>${c.nombre}</b></div>
            <div style="font-size:.78rem;color:#666">${c.tipo_servicio||'—'} · ${c.telefono||'—'} · ${c.direccion||'—'}</div>
          </div>`;
        }).join('') || '<div style="color:#888;padding:1rem;text-align:center">Sin clientes activos</div>'}
        </div>
      </div>
      <div class="modal-ft">
        <button class="btn btn-gray" onclick="document.getElementById('modal-afectados-tmp').remove()">Cerrar</button>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
}

// Filtro de estado para tabla NAPs
let _napsFiltroEstado = 'todos';
let _napsCacheData = [];

function setFiltroEstadoNap(estado){
  _napsFiltroEstado = estado;
  // Toggle visual de botones
  document.querySelectorAll('[data-nap-filter]').forEach(b=>{
    b.classList.toggle('btn-prim', b.dataset.napFilter === estado);
    b.classList.toggle('btn-gray', b.dataset.napFilter !== estado);
  });
  renderNapsTable();
}

function _napsFiltrar(){
  let out = _napsCacheData.slice();
  // Filtro estado
  if(_napsFiltroEstado !== 'todos'){
    out = out.filter(n => (n.estado||'activo') === _napsFiltroEstado);
  }
  // Filtro búsqueda
  const q = (document.getElementById('nap-q')?.value || '').trim().toLowerCase();
  if(q){
    out = out.filter(n =>
      (n.nombre||'').toLowerCase().includes(q) ||
      (n.localidad||'').toLowerCase().includes(q) ||
      (n.sitio||'').toLowerCase().includes(q) ||
      (n.cdo||'').toLowerCase().includes(q) ||
      (n.olt_nombre||'').toLowerCase().includes(q)
    );
  }
  // Filtro localidad
  const loc = document.getElementById('nap-fil-loc')?.value || '';
  if(loc) out = out.filter(n => (n.localidad||'') === loc);
  // Filtro OLT
  const olt = document.getElementById('nap-fil-olt')?.value || '';
  if(olt) out = out.filter(n => (n.olt_nombre||'') === olt);
  return out;
}

function renderNapsTable(){
  const tbody=document.getElementById('nap-tbody');
  if(!tbody) return;
  const filtered = _napsFiltrar();
  // Update total counter if the element exists
  const totalEl = document.getElementById('nap-total');
  if(totalEl) totalEl.textContent = filtered.length;
  if(!filtered.length){
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:#888;padding:1.5rem">Sin NAPs con estos criterios</td></tr>';
    return;
  }
  tbody.innerHTML=filtered.map(n=>{
    const est = n.estado||'activo';
    const badgeClass = est==='alerta'?'b-rescision':est==='mantenimiento'?'b-pendiente':est==='inactivo'?'b-baja':'b-activo';
    const badgeIcon = est==='alerta'?'⚠️ ':est==='mantenimiento'?'🔧 ':est==='inactivo'?'⊘ ':'✓ ';
    const afectadosBtn = (est==='alerta' || est==='mantenimiento')
      ? `<button class="btn btn-am btn-xs" onclick="verAfectadosNap(${n.id})" title="Ver clientes afectados">👥 ${n.activos||0}</button>`
      : '';
    const cap = n.capacidad || 8;
    const pct = Math.round((n.total||0)/cap*100);
    const occColor = (n.total||0) >= cap ? 'var(--rj2)' : (n.total||0) >= (cap-2) ? 'var(--am2)' : 'var(--vd2)';
    const oltBadge = n.olt_nombre
      ? `<span class="badge b-fibra">${n.olt_nombre} PON${n.olt_puerto||'?'}</span>
         <button class="btn btn-gray btn-xs" style="margin-left:.3rem" title="Asignar OLT/PON" onclick="openModalNapOlt(${n.id},${JSON.stringify(n.nombre||'').replace(/"/g,'&quot;')},${JSON.stringify(n.olt_nombre||'').replace(/"/g,'&quot;')},${JSON.stringify(n.olt_puerto||'').replace(/"/g,'&quot;')})">🔗</button>`
      : `<span style="color:var(--txt2);font-size:.75rem">Sin asignar</span>
         <button class="btn btn-gray btn-xs" style="margin-left:.3rem" title="Asignar OLT/PON" onclick="openModalNapOlt(${n.id},${JSON.stringify(n.nombre||'').replace(/"/g,'&quot;')},'','')">🔗</button>`;
    const nombreCell = `<b style="cursor:pointer;color:var(--az)" onclick="showNapDetail(${JSON.stringify(n.nombre||'').replace(/"/g,'&quot;')})">🔗 ${n.nombre}</b>`;
    const rowStyle = est==='alerta'?'style="background:#ffebee"':est==='mantenimiento'?'style="background:#fff3e0"':'';
    return `<tr ${rowStyle}>
      <td>${nombreCell}</td>
      <td>${n.localidad||'—'}</td>
      <td>${cap}</td>
      <td>
        <div style="display:flex;align-items:center;gap:.4rem">
          <div style="width:60px;height:7px;background:#ddd;border-radius:4px;overflow:hidden">
            <div style="width:${pct}%;height:100%;background:${occColor}"></div>
          </div>
          <span style="font-size:.78rem">${n.total||0}/${cap}</span>
        </div>
      </td>
      <td style="color:var(--vd);font-weight:700">${n.activos||0}</td>
      <td style="color:var(--am);font-weight:700">${n.suspendidos||0}</td>
      <td style="color:var(--rj);font-weight:700">${n.rescision||0}</td>
      <td>${oltBadge}</td>
      <td style="font-size:.72rem;color:var(--txt2);font-family:monospace">${n.nivel_senal||'—'}</td>
      <td><span class="badge ${badgeClass}">${badgeIcon}${est}</span> ${afectadosBtn}</td>
      <td>
        ${puedeEditar('naps')?`<button class="btn btn-gray btn-xs" onclick="openModalNap(${n.id})">✏️</button>`:''}
        ${puedeEliminar('naps')?`<button class="btn btn-rj btn-xs" onclick="deleteNap(${n.id})">🗑</button>`:''}
      </td>
    </tr>`;
  }).join('');
}

async function loadNaps(){
  const d=await api('/api/naps');
  if(!d) return;
  _napsCacheData = d;
  // Calcular contadores para los filtros (sobre todos los NAPs cargados)
  const counts = {todos:d.length, activo:0, alerta:0, mantenimiento:0, inactivo:0};
  d.forEach(n=>{
    const e = n.estado||'activo';
    if(counts[e] !== undefined) counts[e]++;
  });
  // Render filtros (si existe el contenedor)
  const filterBar = document.getElementById('naps-filter-bar');
  if(filterBar){
    filterBar.innerHTML = [
      ['todos','Todos','#666'],
      ['activo','Activos','#1565c0'],
      ['alerta','En Alerta','#dc3545'],
      ['mantenimiento','Mantenimiento','#ff9800'],
      ['inactivo','Inactivos','#9e9e9e'],
    ].map(([k,label,color])=>
      `<button data-nap-filter="${k}" class="btn ${_napsFiltroEstado===k?'btn-prim':'btn-gray'} btn-sm" 
        onclick="setFiltroEstadoNap('${k}')" style="border-left:3px solid ${color}">
        ${label} <span style="opacity:.7">(${counts[k]||0})</span>
      </button>`
    ).join('');
  }
  // Poblar selects de localidad y OLT
  const locs = [...new Set(d.map(n => n.localidad).filter(x=>x))].sort();
  const olts = [...new Set(d.map(n => n.olt_nombre).filter(x=>x))].sort();
  const locSel = document.getElementById('nap-fil-loc');
  const oltSel = document.getElementById('nap-fil-olt');
  if(locSel && locSel.options.length <= 1){
    locs.forEach(l => locSel.innerHTML += `<option value="${l}">${l}</option>`);
  }
  if(oltSel && oltSel.options.length <= 1){
    olts.forEach(o => oltSel.innerHTML += `<option value="${o}">${o}</option>`);
  }
  renderNapsTable();
}

// Hook para que la búsqueda en el input filtre la tabla cacheada (sin pegarle al backend)
function debouncedLoadNaps(){
  // Si ya tenemos data cacheada, sólo re-render. Si no, cargar.
  if(_napsCacheData.length){
    renderNapsTable();
  } else {
    loadNaps();
  }
}

async function openModalNap(id=null){
  ['mnap-id','mnap-nombre','mnap-loc','mnap-desc','mnap-lat','mnap-lng','mnap-cdo','mnap-senal'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('mnap-cap').value=8;
  document.getElementById('mnap-estado').value='activo';
  document.getElementById('mnap-red').value='';
  document.getElementById('mnap-nap-num').value='';
  document.getElementById('mnap-title').textContent=id?'Editar NAP':'Nueva NAP';
  document.getElementById('mnap-nombre').readOnly = !id;

  // Cargar redes
  await loadRedes();
  const redSel=document.getElementById('mnap-red');
  redSel.innerHTML='<option value="">— Seleccionar red —</option>';
  redesData.forEach(r=>{
    const o=document.createElement('option'); o.value=r.nombre; o.textContent=r.nombre; redSel.appendChild(o);
  });

  if(id){
    const naps=await api('/api/naps');
    const n=naps.find(x=>x.id===id);
    if(n){
      document.getElementById('mnap-id').value=n.id;
      document.getElementById('mnap-nombre').value=n.nombre;
      document.getElementById('mnap-nombre').readOnly=false;
      document.getElementById('mnap-loc').value=n.localidad||'';
      document.getElementById('mnap-desc').value=n.descripcion||'';
      document.getElementById('mnap-lat').value=n.lat||'';
      document.getElementById('mnap-lng').value=n.lng||'';
      document.getElementById('mnap-cap').value=n.capacidad||8;
      document.getElementById('mnap-estado').value=n.estado||'activo';
      document.getElementById('mnap-senal').value=n.nivel_senal||'';
      // Restore structured fields
      if(n.red) document.getElementById('mnap-red').value=n.red;
      if(n.cdo) document.getElementById('mnap-cdo').value=n.cdo;
      if(n.nap_numero) document.getElementById('mnap-nap-num').value=n.nap_numero;
    }
  }
  document.getElementById('modal-nap').style.display='flex';
}

function generarNombreNap(){
  const red=document.getElementById('mnap-red').value;
  const cdo=document.getElementById('mnap-cdo').value.trim();
  const nap=document.getElementById('mnap-nap-num').value;
  if(red && cdo && nap){
    document.getElementById('mnap-nombre').value=`${red} - CDO ${cdo} - NAP ${nap}`;
  } else if(red && cdo){
    document.getElementById('mnap-nombre').value=`${red} - CDO ${cdo}`;
  } else if(red){
    document.getElementById('mnap-nombre').value=red;
  }
}

async function saveNap(_force){
  const id=document.getElementById('mnap-id').value;
  const red=document.getElementById('mnap-red').value;
  const cdo=document.getElementById('mnap-cdo').value.trim();
  const napNum=document.getElementById('mnap-nap-num').value;
  const nombre=document.getElementById('mnap-nombre').value;
  const senal=(document.getElementById('mnap-senal')?.value || '').trim();

  if(!nombre.trim()){alert('Completá Red, CDO y NAP para generar el nombre');return;}
  if(!id && (!red||!cdo||!napNum)){
    if(!confirm('Los campos Red, CDO o NAP no están completos. ¿Guardar con nombre manual?')) return;
  }

  const data={
    nombre:nombre,
    localidad:document.getElementById('mnap-loc').value,
    descripcion:document.getElementById('mnap-desc').value,
    lat:parseDMS(document.getElementById('mnap-lat').value),
    lng:parseDMS(document.getElementById('mnap-lng').value),
    capacidad:parseInt(document.getElementById('mnap-cap').value)||8,
    estado:document.getElementById('mnap-estado').value,
    sitio:red, red:red, cdo:cdo,
    nap_numero:napNum?parseInt(napNum):null,
    nivel_senal: senal || null
  };
  // Sólo en alta: enviar señal con flag para que el backend timestamp-ee
  if(!id && senal) data.senal_alta = senal;
  if(_force) data.force = true;
  
  const r=await api(id?`/api/naps/${id}`:'/api/naps', id?'PUT':'POST', data);
  if(r?.ok){
    closeModal('modal-nap');
    loadNaps();
    loadNapDatalist();
    return;
  }
  if(r?.error === 'duplicado'){
    _napDuplicadoActual = r;
    const labels = {nombre:'nombre del NAP', red_cdo_numero:'combinación red/CDO/N°'};
    const campoLbl = labels[r.campo] || r.campo;
    document.getElementById('napdup-mensaje').innerHTML =
      `Ya existe un NAP con el mismo <b>${campoLbl}</b>: <code style="background:#fff3cd;padding:.1rem .35rem;border-radius:3px">${r.valor}</code>`;
    document.getElementById('napdup-conflicto-nombre').textContent = r.conflicto_nombre || '(sin nombre)';
    document.getElementById('napdup-conflicto-id').textContent = `ID #${r.conflicto_id}`;
    document.getElementById('napdup-btn-forzar').style.display = r.puede_forzar ? 'inline-block' : 'none';
    document.getElementById('modal-nap-duplicado').style.display='flex';
    return;
  }
  alert(r?.msg || r?.error || 'Error al guardar');
}

let _napDuplicadoActual = null;

function abrirFichaNapConflicto(){
  if(!_napDuplicadoActual) return;
  const id = _napDuplicadoActual.conflicto_id;
  closeModal('modal-nap-duplicado');
  closeModal('modal-nap');
  openModalNap(id);
}

async function forzarGuardadoNap(){
  if(!_napDuplicadoActual) return;
  if(!confirm(`¿Confirmás forzar el guardado a pesar del duplicado con "${_napDuplicadoActual.conflicto_nombre}"?\n\nEsta acción quedará registrada.`)) return;
  closeModal('modal-nap-duplicado');
  await saveNap(true);
}

async function deleteNap(id){
  if(!puedeEliminar('naps')){alert('No tenés permisos para eliminar NAPs');return;}
  if(!confirm('¿Eliminar esta NAP?')) return;
  const r=await api(`/api/naps/${id}`,'DELETE');
  if(r?.error) alert(r.msg||'No se pudo eliminar');
  loadNaps();
}

// ── SERVICIOS ──

let napSearchTimer=null, allNapsData=[];

// (debouncedLoadNaps y loadNaps ya definidos arriba; estos duplicados se eliminaron en sprint v7.2)

async function openModalNapOlt(napId, napNombre, oltActual, ponActual){
  document.getElementById('mnolt-nap-id').value=napId;
  document.getElementById('mnolt-title').textContent=`OLT/PON → ${napNombre}`;
  document.getElementById('mnolt-info').textContent=`NAP: ${napNombre}`;
  document.getElementById('mnolt-olt').value=oltActual||'';
  document.getElementById('mnolt-pon').value=ponActual||'';

  // Poblar OLTs
  const olts=await api('/api/olts');
  const sel=document.getElementById('mnolt-olt');
  sel.innerHTML='<option value="">Sin OLT asignada</option>';
  if(olts) olts.forEach(o=>{
    const op=document.createElement('option');
    op.value=o.nombre; op.textContent=`${o.nombre} (${o.ip_remota||'—'})`;
    if(o.nombre===oltActual) op.selected=true;
    sel.appendChild(op);
  });

  document.getElementById('modal-nap-olt').style.display='flex';
}

async function saveNapOlt(){
  const napId=document.getElementById('mnolt-nap-id').value;
  const r=await api(`/api/naps/${napId}/asignar_olt`,'PUT',{
    olt_nombre:document.getElementById('mnolt-olt').value,
    olt_puerto:document.getElementById('mnolt-pon').value
  });
  if(r?.ok){closeModal('modal-nap-olt');loadNaps();}
  else alert('Error al asignar');
}

// ── TORRES ──

async function buscarNapActivacion(){
  const q=document.getElementById('act-nap-q').value;
  const drop=document.getElementById('act-nap-drop');
  if(q.length<2){drop.style.display='none';return;}
  const naps=allNapsData.length?allNapsData:await api('/api/naps');
  const filtered=(naps||[]).filter(n=>(n.nombre||'').toLowerCase().includes(q.toLowerCase())).slice(0,8);
  if(!filtered.length){drop.style.display='none';return;}
  drop.innerHTML=filtered.map(n=>`<div onclick="selectNapActivacion('${n.nombre.replace(/'/g,"\\'")}',${n.libre||0})" style="padding:.4rem .7rem;cursor:pointer;border-bottom:1px solid var(--brd);font-size:.82rem">
    <b>${n.nombre}</b> <span style="color:${(n.libre||0)>0?'var(--vd)':'var(--rj)'}">libre: ${n.libre||0}</span>
  </div>`).join('');
  drop.style.display='block';
}

function selectNapActivacion(nombre, libre){
  document.getElementById('act-nap-q').value=nombre;
  document.getElementById('act-nap-drop').style.display='none';
}

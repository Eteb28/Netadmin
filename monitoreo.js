/* ========================================================
   monitoreo.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadOltDatalist(){
  const olts=await api('/api/olts');
  if(!olts) return;
  oltData=olts;
  document.getElementById('olt-datalist').innerHTML=olts.map(o=>`<option value="${o.nombre}">`).join('');
}

async function showOltsOnMap(){
  removeLayer('olts');
  const data=await api('/api/olts');
  if(!data) return;
  const markers=data.filter(o=>o.lat&&o.lng).map(o=>{
    const icon=L.divIcon({className:'',html:`<div style="background:#0d47a1;color:#fff;border-radius:6px;padding:2px 5px;font-size:.65rem;font-weight:700;white-space:nowrap;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3)">OLT</div>`,iconAnchor:[20,12]});
    return L.marker([o.lat,o.lng],{icon}).bindPopup(`<b>OLT: ${o.nombre}</b><br>IP: ${o.ip_remota||'—'}<br>Puertos PON: ${o.puertos_pon}<br>Clientes: ${o.total_clientes||0}`);
  });
  mapaLayers.olts=L.layerGroup(markers).addTo(map);
}

// ── BÚSQUEDA MAPA ──

async function loadOlts(){
  const d=await api('/api/olts');
  if(!d) return;
  const list=document.getElementById('olt-list');
  if(!d.length){list.innerHTML='<div class="empty">Sin OLTs cargadas. Agregá la primera.</div>';return;}
  list.innerHTML=d.map(o=>{
    // Botón "Ingresar" si tiene IP remota (link a http://<ip>)
    const ipBtn = o.ip_remota
      ? `<a href="https://${o.ip_remota}/action/login.html" target="_blank" rel="noopener" class="btn btn-am btn-xs" title="Abrir gestión web de la OLT">🔗 Ingresar</a>`
      : '';
    return `<div class="olt-card" style="margin-bottom:.8rem">
      <div class="olt-hd">
        <div>
          <div class="olt-name">🖥 ${o.nombre}</div>
          <div class="olt-ip">${o.modelo?o.modelo+' | ':''}IP Remota: ${o.ip_remota?`<a href="https://${o.ip_remota}/action/login.html" target="_blank" rel="noopener" style="font-family:monospace;color:#1976d2;text-decoration:underline">${o.ip_remota}</a>`:'—'} | IP Red: ${o.ip_red||'—'}</div>
          <div style="font-size:.72rem;color:var(--txt2)">${o.ubicacion||''} ${o.lat?`| 📍 ${o.lat},${o.lng}`:''}</div>
        </div>
        <div style="margin-left:auto;display:flex;gap:.3rem">
          <span class="badge b-fibra">${o.total_clientes||0} clientes</span>
          ${ipBtn}
          <button class="btn btn-gray btn-xs" onclick="openModalOlt(${o.id})">✏️</button>
          <button class="btn btn-rj btn-xs" onclick="deleteOlt(${o.id})">🗑</button>
        </div>
      </div>
      <div class="pon-grid">
        ${(o.puertos||[]).map(p=>{
          const cls=p.total===0?'vacio':p.total>=8?'lleno':p.total>=6?'casi':'';
          // Hacer clickeable si tiene clientes
          const clickable = p.total > 0 ? `style="cursor:pointer" onclick="verClientesPon(${o.id}, ${JSON.stringify(o.nombre).replace(/"/g,'&quot;')}, ${JSON.stringify(String(p.puerto)).replace(/"/g,'&quot;')})"` : '';
          return `<div class="pon-port ${cls}" ${clickable} title="PON ${p.puerto}: ${p.activos} activos, ${p.suspendidos} susp, ${p.rescision} rescisión${p.total>0?' — Click para ver clientes':''}">
            <div class="pon-num">PON ${p.puerto}</div>
            <div class="pon-cnt" style="color:${p.total===0?'#bdbdbd':p.activos>0?'var(--vd)':'var(--am)'}">${p.total}</div>
            <div style="font-size:.6rem;display:flex;gap:2px;justify-content:center;margin-top:2px">
              ${p.activos?`<span style="color:var(--vd)">▲${p.activos}</span>`:''}
              ${p.suspendidos?`<span style="color:var(--am)">⏸${p.suspendidos}</span>`:''}
              ${p.rescision?`<span style="color:var(--rj)">⚠${p.rescision}</span>`:''}
            </div>
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }).join('');
}

// Modal para mostrar clientes de un PON
async function verClientesPon(oltId, oltNombre, pon){
  const r = await api(`/api/olts/${oltId}/clientes_por_pon?pon=${encodeURIComponent(pon)}`);
  if(!r) return;
  const html = `<div class="modal-overlay" id="modal-pon-tmp" style="display:flex" onclick="if(event.target===this)this.remove()">
    <div class="modal" style="max-width:680px">
      <div class="modal-hd" style="background:#1976d2;color:#fff">
        <span>🔌 Clientes en ${oltNombre} · PON ${pon}</span>
        <button class="modal-close" style="color:#fff" onclick="document.getElementById('modal-pon-tmp').remove()">×</button>
      </div>
      <div class="modal-bd">
        <div style="margin-bottom:.6rem;font-weight:600">Total: ${r.total} cliente(s) en este PON</div>
        <div style="max-height:55vh;overflow-y:auto">
        ${(r.clientes||[]).map(c=>{
          const nro = c.nro_cliente?`<span class="badge b-fibra" style="font-family:monospace;margin-right:.3rem">#${c.nro_cliente}</span>`:'';
          const estCls = c.estado==='activo'?'b-activo':c.estado==='suspendido'?'b-pendiente':'b-baja';
          return `<div style="padding:.5rem;border-bottom:1px solid #eee;cursor:pointer" onclick="document.getElementById('modal-pon-tmp').remove();openModalCliente(${c.id})">
            <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
              ${nro}<b>${c.nombre}</b>
              <span class="badge ${estCls}" style="margin-left:auto">${c.estado||'—'}</span>
            </div>
            <div style="font-size:.78rem;color:#666;margin-top:.15rem">
              ${c.plan||'—'} · ${c.ip_asignada||'—'} · ${c.telefono||'—'}<br>
              ${c.direccion||'—'} ${c.nap?`· NAP: ${c.nap}`:''}
            </div>
          </div>`;
        }).join('') || '<div style="color:#888;padding:1rem;text-align:center">Sin clientes en este PON</div>'}
        </div>
      </div>
      <div class="modal-ft">
        <button class="btn btn-gray" onclick="document.getElementById('modal-pon-tmp').remove()">Cerrar</button>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
}

async function openModalOlt(id=null){
  ['molt-id','molt-nombre','molt-modelo','molt-ip-remota','molt-ip-red','molt-ubicacion','molt-lat','molt-lng'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('molt-puertos').value=4;
  document.getElementById('molt-title').textContent=id?'Editar OLT':'Nueva OLT';
  if(id){
    const olts=await api('/api/olts');
    const o=olts.find(x=>x.id===id);
    if(o){
      document.getElementById('molt-id').value=o.id;
      document.getElementById('molt-nombre').value=o.nombre;
      document.getElementById('molt-modelo').value=o.modelo||'';
      document.getElementById('molt-ip-remota').value=o.ip_remota||'';
      document.getElementById('molt-ip-red').value=o.ip_red||'';
      document.getElementById('molt-puertos').value=o.puertos_pon||4;
      document.getElementById('molt-ubicacion').value=o.ubicacion||'';
      document.getElementById('molt-lat').value=o.lat||'';
      document.getElementById('molt-lng').value=o.lng||'';
    }
  }
  document.getElementById('modal-olt').style.display='flex';
}

async function saveOlt(){
  const id=document.getElementById('molt-id').value;
  const data={nombre:document.getElementById('molt-nombre').value,
    modelo:document.getElementById('molt-modelo').value,
    ip_remota:document.getElementById('molt-ip-remota').value,
    ip_red:document.getElementById('molt-ip-red').value,
    puertos_pon:parseInt(document.getElementById('molt-puertos').value)||4,
    ubicacion:document.getElementById('molt-ubicacion').value,
    lat:parseFloat(document.getElementById('molt-lat').value)||null,
    lng:parseFloat(document.getElementById('molt-lng').value)||null};
  if(!data.nombre.trim()){alert('El nombre es obligatorio');return;}
  const r=await api(id?`/api/olts/${id}`:'/api/olts',id?'PUT':'POST',data);
  if(r?.ok){closeModal('modal-olt');loadOlts();loadOltDatalist();}
  else alert('Error al guardar');
}

async function deleteOlt(id){
  if(!confirm('¿Eliminar esta OLT?')) return;
  await api(`/api/olts/${id}`,'DELETE');
  loadOlts();
}

// ── INCIDENCIAS ──

async function loadDashMonitoreo(){
  const d=await api('/api/monitoreo/resumen');
  if(!d) return;
  const badge=document.getElementById('mon-resumen-badge');
  if(badge){
    badge.textContent=`${d.online}/${d.total} online`;
    badge.style.background=d.offline>0?'var(--rj)':'var(--vd)';
    badge.style.color='#fff';
  }
  const list=document.getElementById('dash-mon-list');
  if(!list) return;
  if(d.offline_list&&d.offline_list.length){
    list.innerHTML=d.offline_list.map(m=>`<div style="background:#f5d0d0;border-radius:8px;padding:.5rem .6rem;border-left:3px solid var(--rj)">
      <div style="font-weight:700;font-size:.78rem;color:var(--rj)">🔴 ${m.nombre}</div>
      <div style="font-size:.7rem;font-family:monospace;color:var(--txt2)">${m.ip}</div>
      <div style="font-size:.68rem;color:var(--txt2)">Fallos: ${m.consecutivos_offline}</div>
    </div>`).join('');
  } else {
    list.innerHTML=`<div style="background:#d4edda;border-radius:8px;padding:.5rem .8rem;border-left:3px solid var(--vd2);grid-column:1/-1">
      <span style="color:var(--vd);font-weight:700">✅ Todos los dispositivos monitoreados están en línea (${d.online}/${d.total})</span>
    </div>`;
  }
}

async function loadMonitoreo(){
  const d=await api('/api/monitoreo');
  if(!d) return;
  const resumen=await api('/api/monitoreo/resumen');
  if(resumen){
    document.getElementById('mon-stats').innerHTML=`
      <div class="stat"><div class="stat-val">${resumen.total}</div><div class="stat-lbl">Total</div></div>
      <div class="stat green"><div class="stat-val">${resumen.online}</div><div class="stat-lbl">Online</div></div>
      <div class="stat red"><div class="stat-val">${resumen.offline}</div><div class="stat-lbl">Offline</div></div>
      <div class="stat"><div class="stat-val">${resumen.total-resumen.online-resumen.offline}</div><div class="stat-lbl">Desconocido</div></div>`;
  }
  const tbody=document.getElementById('mon-tbody');
  tbody.innerHTML=d.map(m=>{
    const color={online:'var(--vd)',offline:'var(--rj)',degradado:'var(--am)',desconocido:'var(--gris)'}[m.estado]||'var(--gris)';
    const icn={online:'🟢',offline:'🔴',degradado:'🟡',desconocido:'⚪'}[m.estado]||'⚪';
    return `<tr>
      <td><b>${m.nombre}</b></td>
      <td><span class="badge b-normal">${m.tipo}</span></td>
      <td style="font-family:monospace;font-size:.8rem">${m.ip}</td>
      <td><span style="color:${color};font-weight:700">${icn} ${m.estado||'desconocido'}</span></td>
      <td>${m.latencia_ms?m.latencia_ms+'ms':'—'}</td>
      <td style="font-size:.75rem">${m.ultimo_check?.slice(0,16)||'Nunca'}</td>
      <td>
        <button class="btn btn-am btn-xs" onclick="pingManual(${m.id})">📡 Ping</button>
        <button class="btn btn-rj btn-xs" onclick="deleteMonitoreo(${m.id})">🗑</button>
      </td>
    </tr>`;
  }).join('');
}

async function pingManual(id){
  const btn=event.target; btn.textContent='...'; btn.disabled=true;
  const r=await api(`/api/monitoreo/ping/${id}`,'POST');
  btn.textContent='📡 Ping'; btn.disabled=false;
  if(r) loadMonitoreo();
}

async function pingTodos(){
  const d=await api('/api/monitoreo');
  if(!d) return;
  for(const m of d){
    await api(`/api/monitoreo/ping/${m.id}`,'POST');
  }
  loadMonitoreo();
  loadDashMonitoreo();
}

function openModalMonitoreo(){
  ['mmon-nombre','mmon-ip'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('mmon-tipo').value='torre';
  document.getElementById('modal-monitoreo').style.display='flex';
}

async function saveMonitoreo(){
  const r=await api('/api/monitoreo','POST',{
    nombre:document.getElementById('mmon-nombre').value,
    tipo:document.getElementById('mmon-tipo').value,
    ip:document.getElementById('mmon-ip').value
  });
  if(r?.ok){closeModal('modal-monitoreo');loadMonitoreo();}
  else alert('Error al agregar');
}

async function deleteMonitoreo(id){
  if(!confirm('¿Quitar este dispositivo del monitoreo?')) return;
  await api(`/api/monitoreo/${id}`,'DELETE');
  loadMonitoreo();
}

// ── HISTORIAL DE SEÑAL NAP ──

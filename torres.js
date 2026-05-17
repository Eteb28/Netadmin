/* ========================================================
   torres.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function showTorresOnMap(){
  if(!mapaInited) return;
  removeLayer('torres');
  const data=await api('/api/torres/mapa_red');
  if(!data) return;
  const layers=[];
  // Colores por proveedor
  const PROV_COLORS={ARSAT:'#0066cc',Gigared:'#e6007e',Telecom:'#00a651',Support:'#ff6600',ENERSA:'#00730d',LEVEL3:'#edff61',ERLAN:'#ed7c02'};
  data.forEach(t=>{
    if(!t.lat||!t.lng) return;
    const isPrincipal = t.tipo==='principal';
    const baseColor={activa:'#2a6632',inactiva:'#8b1f1f',mantenimiento:'#bac90c'}[t.estado]||'#4a5c6a';
    const monColor={online:'#2a6632',offline:'#8b1f1f',desconocido:'#8c4a12'}[t.mon_estado]||baseColor;
    const provColor = isPrincipal && t.proveedor ? (PROV_COLORS[t.proveedor]||'#4a5c6a') : monColor;
    const hasIncidencia = t.incidencia_activa || t.afectada_por_incidencia;
    const incBorder = hasIncidencia ? 'border:6px solid #ff0000;animation:pulse-inc 1.5s infinite;' : 'border:2px solid #fff;';
    const incIcon = hasIncidencia ? '⚠️' : '🗼';
    const size = isPrincipal ? 26 : 18;
    const fontSize = isPrincipal ? '13px' : '10px';
    const labelText=t.nombre.split(' - ').pop().slice(0,20);
    const provBadge = isPrincipal && t.proveedor ? `<div style="background:${provColor};color:#fff;padding:0 4px;border-radius:3px;font-size:.55rem;font-weight:700;white-space:nowrap">${t.proveedor}</div>` : '';
    const icon=L.divIcon({
      className:'',
      html:`<div style="display:flex;align-items:center;gap:3px;flex-direction:column">
        <div style="width:${size}px;height:${size}px;background:${provColor};${incBorder}border-radius:${isPrincipal?'50%':'3px'};box-shadow:0 2px 6px rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;color:#fff;font-size:${fontSize}">${incIcon}</div>
        <div style="display:flex;align-items:center;gap:2px">
          <div style="background:rgba(255,255,255,.95);padding:1px 5px;border-radius:3px;font-size:.65rem;color:#1a3d6b;font-weight:700;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.2)${hasIncidencia?';border:1px solid #ff0000':''}">${labelText}</div>
          ${provBadge}
        </div>
      </div>`,
      iconAnchor:[size/2,size/2]
    });
    const incInfo = t.incidencias && t.incidencias.length ? `<br><span style="color:#c00;font-weight:700">⚠ Incidencias: ${t.incidencias.map(i=>i.titulo).join(', ')}</span>` : '';
    const cascadeInfo = t.afectada_por_incidencia && !t.incidencia_activa ? `<br><span style="color:#e65100">⚠ Afectada por incidencia en torre padre</span>` : '';
    const popup=`<b>${incIcon} ${t.nombre}</b><br>
      ${t.localidad?'📍 '+t.localidad+'<br>':''}
      Tipo: <b>${t.tipo||'—'}</b>${isPrincipal&&t.proveedor?' | Proveedor: <b>'+t.proveedor+'</b>':''}
      <br>Estado: <b>${t.estado||'—'}</b><br>
      ${t.mon_estado&&t.mon_estado!=='desconocido'?'Monitoreo: <b>'+t.mon_estado+'</b><br>':''}
      ${t.ip_equipos?'🌐 '+t.ip_equipos+'<br>':''}
      ${t.altura_mts?'📏 '+t.altura_mts+' m<br>':''}
      ${t.hijos>0?'<b>'+t.hijos+' torres dependen de esta</b><br>':''}
      ${incInfo}${cascadeInfo}
      ${t.requiere_revision?'<span style="color:#bf6d1e">⚠ Requiere revisión</span>':''}`;
    layers.push(L.marker([t.lat,t.lng],{icon,zIndexOffset:isPrincipal?1000:0}).bindPopup(popup));
    if(t.torre_padre_id&&t.padre_lat&&t.padre_lng){
      const lineColor= hasIncidencia ? '#ff0000' : t.mon_estado==='offline'?'#8b1f1f':baseColor;
      const lineWeight = hasIncidencia ? 3 : 2;
      layers.push(L.polyline([[t.lat,t.lng],[t.padre_lat,t.padre_lng]],{
        color:lineColor,weight:lineWeight,
        dashArray:t.estado!=='activa'?'6,4':(hasIncidencia?'8,4':null),opacity:hasIncidencia?.9:.7
      }));
    }
  });
  mapaLayers.torres=L.layerGroup(layers).addTo(map);
}

let torresTimer=null;

function debouncedLoadTorres(){
  clearTimeout(torresTimer);
  torresTimer=setTimeout(loadTorres,300);
}

async function loadTorres(){
  const d=await api('/api/torres');
  if(!d) return;
  const q=(document.getElementById('torre-q')||{value:''}).value.toLowerCase();
  const est=(document.getElementById('torre-estado-fil')||{value:''}).value;
  let filtered=d;
  if(q) filtered=filtered.filter(t=>(t.nombre||'').toLowerCase().includes(q)||(t.localidad||'').toLowerCase().includes(q));
  if(est) filtered=filtered.filter(t=>t.estado===est);

  const list=document.getElementById('torres-list');
  if(!filtered.length){list.innerHTML='<div class="empty">Sin torres registradas</div>';return;}

  list.innerHTML=filtered.map(t=>{
    const colorEst={activa:'var(--vd)',inactiva:'var(--rj)',mantenimiento:'var(--am)'}[t.estado]||'var(--gris)';
    const ips=(t.ip_equipos||'').split(',').filter(Boolean);
    const provColors={ARSAT:'#0066cc',Gigared:'#e6007e',Telecom:'#00a651',Support:'#ff6600',ENERSA:'#9c27b0',LEVEL3:'#0288d1',ERLAN:'#ed7c02'};
    const provBadge = t.tipo==='principal'&&t.proveedor
      ? `<span class="badge" style="background:${provColors[t.proveedor]||'#666'};color:#fff">${t.proveedor}</span>`
      : '';
    return `<div class="card" style="margin-bottom:.6rem;border-left:4px solid ${colorEst}">
      <div style="display:flex;align-items:flex-start;gap:.6rem;flex-wrap:wrap">
        <div style="flex:1">
          <div style="display:flex;align-items:center;gap:.4rem;margin-bottom:.3rem;flex-wrap:wrap">
            <b style="font-size:.92rem">🗼 ${t.nombre}</b>
            <span class="badge ${t.estado==='activa'?'b-activo':t.estado==='inactiva'?'b-rescision':'b-pendiente'}">${t.estado}</span>
            <span class="badge b-normal">${t.tipo||'repetidora'}</span>
            ${provBadge}
            ${t.padre_nombre?`<span class="badge b-fibra">Depende de: ${t.padre_nombre}</span>`:''}
            ${t.dependientes>0?`<span class="badge b-pendiente">${t.dependientes} torres dependen de esta</span>`:''}
          </div>
          <div style="font-size:.8rem;color:var(--txt2);display:flex;gap:1rem;flex-wrap:wrap">
            ${t.localidad?`<span>📍 ${t.localidad}${t.direccion?' — '+t.direccion:''}</span>`:''}
            ${t.altura_mts?`<span>📏 ${t.altura_mts} mts</span>`:''}
            ${t.lat?`<span>🌐 ${t.lat?.toFixed(5)}, ${t.lng?.toFixed(5)}</span>`:''}
          </div>
          ${ips.length?`<div style="font-size:.75rem;font-family:monospace;margin-top:.3rem;color:var(--az)">
            IPs: ${ips.map(ip=>`<span style="background:var(--fondo);padding:.1rem .4rem;border-radius:4px;margin:.1rem">${ip.trim()}</span>`).join('')}
          </div>`:''}
          ${t.orientaciones?`<div style="font-size:.75rem;color:var(--txt2);margin-top:.2rem">🧭 ${t.orientaciones}</div>`:''}
          ${t.observaciones?`<div style="font-size:.75rem;color:var(--txt2);margin-top:.2rem;font-style:italic">${t.observaciones}</div>`:''}
        </div>
        <div style="display:flex;gap:.3rem;flex-shrink:0">
          <button class="btn btn-gray btn-xs" onclick="openModalTorre(${t.id})">✏️</button>
          <button class="btn btn-rj btn-xs" onclick="deleteTorre(${t.id})">🗑</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

let torresCache=[];

async function openModalTorre(id=null){
  ['mtorre-id','mtorre-nombre','mtorre-localidad','mtorre-direccion','mtorre-lat','mtorre-lng',
   'mtorre-ips','mtorre-orient','mtorre-obs','mtorre-altura'].forEach(x=>{const e=document.getElementById(x);if(e)e.value='';});
  document.getElementById('mtorre-tipo').value='repetidora';
  document.getElementById('mtorre-estado').value='activa';
  document.getElementById('mtorre-proveedor').value='';
  document.getElementById('mtorre-title').textContent=id?'Editar Torre':'Nueva Torre';
  torreTypoChange();

  // Poblar select padre
  const torres=await api('/api/torres');
  torresCache=torres||[];
  const sel=document.getElementById('mtorre-padre');
  sel.innerHTML='<option value="">Ninguna (torre principal)</option>';
  torres.forEach(t=>{
    if(t.id===id) return;
    const op=document.createElement('option'); op.value=t.id; op.textContent=t.nombre; sel.appendChild(op);
  });

  if(id){
    const t=torres.find(x=>x.id===id);
    if(t){
      document.getElementById('mtorre-id').value=t.id;
      document.getElementById('mtorre-nombre').value=t.nombre||'';
      document.getElementById('mtorre-localidad').value=t.localidad||'';
      document.getElementById('mtorre-direccion').value=t.direccion||'';
      document.getElementById('mtorre-lat').value=t.lat||'';
      document.getElementById('mtorre-lng').value=t.lng||'';
      document.getElementById('mtorre-tipo').value=t.tipo||'repetidora';
      document.getElementById('mtorre-estado').value=t.estado||'activa';
      document.getElementById('mtorre-altura').value=t.altura_mts||'';
      document.getElementById('mtorre-ips').value=t.ip_equipos||'';
      document.getElementById('mtorre-orient').value=t.orientaciones||'';
      document.getElementById('mtorre-obs').value=t.observaciones||'';
      document.getElementById('mtorre-proveedor').value=t.proveedor||'';
      if(t.torre_padre_id) document.getElementById('mtorre-padre').value=t.torre_padre_id;
      torreTypoChange();
    }
  }
  document.getElementById('modal-torre').style.display='flex';
}

function torreTypoChange(){
  const tipo=document.getElementById('mtorre-tipo').value;
  const provRow=document.getElementById('mtorre-prov-row');
  provRow.style.display=(tipo==='principal')?'grid':'none';
  if(tipo!=='principal') document.getElementById('mtorre-proveedor').value='';
}

async function saveTorre(){
  const id=document.getElementById('mtorre-id').value;
  const data={
    nombre:document.getElementById('mtorre-nombre').value,
    localidad:document.getElementById('mtorre-localidad').value,
    direccion:document.getElementById('mtorre-direccion').value,
    lat:parseDMS(document.getElementById('mtorre-lat').value),
    lng:parseDMS(document.getElementById('mtorre-lng').value),
    tipo:document.getElementById('mtorre-tipo').value,
    estado:document.getElementById('mtorre-estado').value,
    altura_mts:parseFloat(document.getElementById('mtorre-altura').value)||null,
    ip_equipos:document.getElementById('mtorre-ips').value,
    orientaciones:document.getElementById('mtorre-orient').value,
    observaciones:document.getElementById('mtorre-obs').value,
    torre_padre_id:document.getElementById('mtorre-padre').value||null,
    proveedor:document.getElementById('mtorre-proveedor').value||''
  };
  if(!data.nombre.trim()){alert('El nombre es obligatorio');return;}
  const r=await api(id?`/api/torres/${id}`:'/api/torres',id?'PUT':'POST',data);
  if(r?.ok||r?.id){closeModal('modal-torre');loadTorres();}
  else alert(r?.msg||'Error al guardar');
}

async function deleteTorre(id){
  if(!confirm('¿Eliminar esta torre?')) return;
  await api(`/api/torres/${id}`,'DELETE');
  loadTorres();
}

// ── ACTIVACIÓN ──

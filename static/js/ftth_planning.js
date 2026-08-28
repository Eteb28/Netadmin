/*
 * Pucará — Sistema de gestión para ISP
 * Copyright (C) 2026 Esteban Aguiar
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

/* ========================================================
   ftth_planning.js — ERLAN NetAdmin
   Planificación FTTH: rutas de fibra, zonas de expansión
   ======================================================== */

let _ftthRutas = [];
let _ftthZonas = [];
let _ftthDrawing = false;
let _ftthCurrentCoords = [];
let _ftthTempLine = null;
let _ftthTempMarkers = [];
let _ftthDensityLayer = null;

async function loadFtthPlanning(){
  const [rutas, zonas] = await Promise.all([
    api('/api/ftth/rutas'),
    api('/api/ftth/zonas'),
  ]);
  _ftthRutas = rutas || [];
  _ftthZonas = zonas || [];
  renderFtthPanel();
}

function renderFtthPanel(){
  const el = document.getElementById('ftth-panel');
  if(!el) return;
  el.innerHTML = `
    <div style="padding:.5rem">
      <div style="display:flex;gap:.5rem;margin-bottom:.8rem;flex-wrap:wrap">
        <button class="btn btn-prim btn-xs" onclick="startDrawRoute()">✏️ Trazar ruta</button>
        <button class="btn btn-xs" style="background:#ff9800;color:#fff" onclick="toggleDensityMap()">🔥 Densidad inalámbrico</button>
        <button class="btn btn-xs" style="background:#9c27b0;color:#fff" onclick="startDrawZone()">📐 Zona expansión</button>
      </div>
      <h4 style="margin:.5rem 0 .3rem">Rutas trazadas (${_ftthRutas.length})</h4>
      ${_ftthRutas.length ? _ftthRutas.map(r=>`
        <div style="padding:.4rem;border:1px solid #e0e0e0;border-radius:6px;margin-bottom:.3rem;display:flex;justify-content:space-between;align-items:center">
          <div>
            <b style="color:${r.color||'#1565c0'}">${escHtml(r.nombre)}</b>
            <span style="font-size:.75rem;color:var(--txt2)">${Math.round(r.distancia_m)}m · ${escHtml(r.estado)}</span>
          </div>
          <div style="display:flex;gap:.3rem">
            <button class="btn btn-gray btn-xs" onclick="showRuta(${r.id})" title="Ver en mapa">👁</button>
            <button class="btn btn-gray btn-xs" onclick="deleteRuta(${r.id})" title="Eliminar">🗑</button>
          </div>
        </div>
      `).join('') : '<p style="color:var(--txt2);font-size:.8rem">Sin rutas trazadas</p>'}
      <h4 style="margin:.8rem 0 .3rem">Zonas de expansión (${_ftthZonas.length})</h4>
      ${_ftthZonas.length ? _ftthZonas.map(z=>`
        <div style="padding:.4rem;border:1px solid #e0e0e0;border-radius:6px;margin-bottom:.3rem;display:flex;justify-content:space-between;align-items:center">
          <div>
            <b>${escHtml(z.nombre)}</b>
            <span style="font-size:.75rem;color:var(--txt2)">${z.clientes_potenciales} potenciales · ${escHtml(z.prioridad)}</span>
          </div>
          <div style="display:flex;gap:.3rem">
            <button class="btn btn-gray btn-xs" onclick="showZona(${z.id})" title="Ver">👁</button>
            <button class="btn btn-gray btn-xs" onclick="deleteZona(${z.id})" title="Eliminar">🗑</button>
          </div>
        </div>
      `).join('') : '<p style="color:var(--txt2);font-size:.8rem">Sin zonas definidas</p>'}
    </div>`;
}

// ── Dibujar ruta de fibra ──
function startDrawRoute(){
  if(_ftthDrawing) return;
  _ftthDrawing = 'ruta';
  _ftthCurrentCoords = [];
  _ftthTempMarkers = [];
  _clearFtthTemp();
  alert('Click en el mapa para agregar puntos de la ruta. Doble click para terminar.');
  map.on('click', _onDrawClick);
  map.on('dblclick', _onDrawDblClick);
  map.getContainer().style.cursor = 'crosshair';
}

function _onDrawClick(e){
  if(!_ftthDrawing) return;
  const p = [e.latlng.lat, e.latlng.lng];
  _ftthCurrentCoords.push(p);
  // Marcador del punto
  const m = L.circleMarker(e.latlng, {radius:5, fillColor:'#1565c0', color:'#fff', weight:2, fillOpacity:1}).addTo(map);
  _ftthTempMarkers.push(m);
  // Línea temporal
  if(_ftthTempLine) map.removeLayer(_ftthTempLine);
  if(_ftthCurrentCoords.length > 1){
    _ftthTempLine = L.polyline(_ftthCurrentCoords, {color:'#1565c0', weight:3, dashArray:'8,6'}).addTo(map);
  }
}

function _onDrawDblClick(e){
  map.off('click', _onDrawClick);
  map.off('dblclick', _onDrawDblClick);
  map.getContainer().style.cursor = '';
  _ftthDrawing = false;
  if(_ftthCurrentCoords.length < 2) {
    _clearFtthTemp();
    return;
  }
  // Calcular distancia
  let dist = 0;
  for(let i = 1; i < _ftthCurrentCoords.length; i++){
    const [lat1,lng1] = _ftthCurrentCoords[i-1];
    const [lat2,lng2] = _ftthCurrentCoords[i];
    dist += _haversine(lat1,lng1,lat2,lng2);
  }
  const nombre = prompt(`Nombre de la ruta (${Math.round(dist)}m):`);
  if(!nombre) { _clearFtthTemp(); return; }
  _saveRuta(nombre, _ftthCurrentCoords, dist);
}

async function _saveRuta(nombre, coords, dist){
  const r = await api('/api/ftth/rutas', 'POST', {nombre, coords, descripcion:'', color:'#1565c0'});
  if(r?.ok){
    _clearFtthTemp();
    await loadFtthPlanning();
    showAllRutas();
  }
}

function _clearFtthTemp(){
  if(_ftthTempLine) { map.removeLayer(_ftthTempLine); _ftthTempLine = null; }
  _ftthTempMarkers.forEach(m => map.removeLayer(m));
  _ftthTempMarkers = [];
  _ftthCurrentCoords = [];
}

function _haversine(lat1,lng1,lat2,lng2){
  const R=6371000, dlat=_rad(lat2-lat1), dlng=_rad(lng2-lng1);
  const a=Math.sin(dlat/2)**2+Math.cos(_rad(lat1))*Math.cos(_rad(lat2))*Math.sin(dlng/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}
function _rad(d){return d*Math.PI/180;}

// ── Mostrar rutas en mapa ──
function showRuta(id){
  removeLayer('ftth_rutas');
  const r = _ftthRutas.find(x=>x.id===id);
  if(!r || !r.coords.length) return;
  const line = L.polyline(r.coords, {color:r.color||'#1565c0', weight:4, opacity:.9});
  const grupo = L.layerGroup([line]);
  // Marcadores en los puntos
  r.coords.forEach((p,i) => {
    const m = L.circleMarker(p, {radius:4, fillColor:r.color||'#1565c0', color:'#fff', weight:2, fillOpacity:1});
    if(i===0) m.bindPopup(`<b>${r.nombre}</b><br>Inicio · ${Math.round(r.distancia_m)}m total`);
    if(i===r.coords.length-1) m.bindPopup(`<b>${r.nombre}</b><br>Fin · ${Math.round(r.distancia_m)}m total`);
    grupo.addLayer(m);
  });
  mapaLayers.ftth_rutas = grupo.addTo(map);
  map.fitBounds(line.getBounds(), {padding:[30,30]});
}

function showAllRutas(){
  removeLayer('ftth_rutas');
  const grupo = L.layerGroup();
  _ftthRutas.forEach(r => {
    if(!r.coords.length) return;
    const line = L.polyline(r.coords, {color:r.color||'#1565c0', weight:3, opacity:.8})
      .bindPopup(`<b>${r.nombre}</b><br>${Math.round(r.distancia_m)}m · ${r.estado}`);
    grupo.addLayer(line);
  });
  mapaLayers.ftth_rutas = grupo.addTo(map);
}

async function deleteRuta(id){
  if(!confirm('¿Eliminar esta ruta?')) return;
  await api(`/api/ftth/rutas/${id}`, 'DELETE');
  removeLayer('ftth_rutas');
  await loadFtthPlanning();
}

// ── Mapa de densidad de inalámbricos ──
async function toggleDensityMap(){
  if(_ftthDensityLayer){ map.removeLayer(_ftthDensityLayer); _ftthDensityLayer = null; return; }
  const data = await api('/api/ftth/densidad');
  if(!data || !data.length) return;
  const points = data.map(d=>[d.lat, d.lng, 1]);
  if(typeof L.heatLayer === 'function'){
    _ftthDensityLayer = L.heatLayer(points, {radius:25, blur:15, maxZoom:17, gradient:{0.2:'blue',0.4:'cyan',0.6:'lime',0.8:'yellow',1:'red'}}).addTo(map);
  } else {
    // Fallback: círculos
    const g = L.layerGroup();
    data.forEach(d => {
      L.circleMarker([d.lat,d.lng], {radius:4, fillColor:'#ff5722', color:'transparent', fillOpacity:.4}).addTo(g);
    });
    _ftthDensityLayer = g.addTo(map);
  }
}

// ── Zonas de expansión ──
function startDrawZone(){
  if(_ftthDrawing) return;
  _ftthDrawing = 'zona';
  _ftthCurrentCoords = [];
  _clearFtthTemp();
  alert('Click en el mapa para marcar los vértices de la zona. Doble click para cerrar.');
  map.on('click', _onDrawClick);
  map.on('dblclick', _onDrawZoneDblClick);
  map.getContainer().style.cursor = 'crosshair';
}

function _onDrawZoneDblClick(e){
  map.off('click', _onDrawClick);
  map.off('dblclick', _onDrawZoneDblClick);
  map.getContainer().style.cursor = '';
  _ftthDrawing = false;
  if(_ftthCurrentCoords.length < 3) { _clearFtthTemp(); return; }
  // Cerrar polígono
  _ftthCurrentCoords.push(_ftthCurrentCoords[0]);
  const nombre = prompt('Nombre de la zona de expansión:');
  if(!nombre) { _clearFtthTemp(); return; }
  const prioridad = prompt('Prioridad (alta/media/baja):', 'media') || 'media';
  _saveZona(nombre, _ftthCurrentCoords, prioridad);
}

async function _saveZona(nombre, coords, prioridad){
  const r = await api('/api/ftth/zonas', 'POST', {nombre, coords, prioridad});
  if(r?.ok){
    _clearFtthTemp();
    alert(`Zona creada: ${r.clientes_potenciales} clientes inalámbricos potenciales detectados`);
    await loadFtthPlanning();
    showAllZonas();
  }
}

function showZona(id){
  removeLayer('ftth_zonas');
  const z = _ftthZonas.find(x=>x.id===id);
  if(!z || !z.coords.length) return;
  const colores = {alta:'#c62828', media:'#ff9800', baja:'#4caf50'};
  const poly = L.polygon(z.coords, {color:colores[z.prioridad]||'#9c27b0', weight:2, fillOpacity:.2})
    .bindPopup(`<b>${z.nombre}</b><br>Prioridad: ${z.prioridad}<br>Clientes potenciales: ${z.clientes_potenciales}`);
  mapaLayers.ftth_zonas = L.layerGroup([poly]).addTo(map);
  map.fitBounds(poly.getBounds(), {padding:[30,30]});
}

function showAllZonas(){
  removeLayer('ftth_zonas');
  const g = L.layerGroup();
  const colores = {alta:'#c62828', media:'#ff9800', baja:'#4caf50'};
  _ftthZonas.forEach(z => {
    if(!z.coords.length) return;
    L.polygon(z.coords, {color:colores[z.prioridad]||'#9c27b0', weight:2, fillOpacity:.15})
      .bindPopup(`<b>${z.nombre}</b><br>${z.clientes_potenciales} potenciales · ${z.prioridad}`).addTo(g);
  });
  mapaLayers.ftth_zonas = g.addTo(map);
}

async function deleteZona(id){
  if(!confirm('¿Eliminar esta zona?')) return;
  await api(`/api/ftth/zonas/${id}`, 'DELETE');
  removeLayer('ftth_zonas');
  await loadFtthPlanning();
}

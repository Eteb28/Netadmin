/* ========================================================
   dashboard.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

let dashboardLastLoad = 0;

function getFiltrosDashboard() {
  return {
    localidad: (document.getElementById('gf-localidad')||{value:''}).value,
    tipo: (document.getElementById('gf-tipo')||{value:''}).value,
    periodo: (document.getElementById('gf-periodo')||{value:'30'}).value
  };
}

async function reloadDashboard() {
  await loadDash();
  if(typeof loadDashVacaciones === 'function') loadDashVacaciones();
  if(typeof mostrarCardAuditoria === 'function') mostrarCardAuditoria();
}

async function loadDash(){
  _gateDashboardSecciones();
  _cargarBannerTareas();
  _cargarBannerOnuCriticas();
  _cargarServiciosEstado();
  const f = getFiltrosDashboard();
  const qs = `localidad=${encodeURIComponent(f.localidad)}&tipo=${f.tipo}&periodo=${f.periodo}`;

  // Carga en paralelo (solo lo que se muestra)
  const [d, kpiData, distrib, evolucion] = await Promise.all([
    api('/api/dashboard'),
    api(`/api/dashboard/kpis?${qs}`),
    api('/api/dashboard/distribucion'),
    api('/api/dashboard/evolucion_mensual'),
  ]);

  if (!d || !kpiData) return;

  // KPIs principales
  const k = kpiData.kpis;
  setText('kpi-activos', (k.activo||0).toLocaleString());
  setText('kpi-suspendidos', (k.suspendido||0).toLocaleString());
  setText('kpi-rescision', ((k.pte_rescision||0)+(k.rescision||0)).toLocaleString());
  setText('kpi-total', (k.total||0).toLocaleString());

  // Sparklines
  drawSparkline('spark-activos', kpiData.sparkline_activos, '#2a6632');
  drawSparkline('spark-susp', generateFlatSparkline(kpiData.sparkline_activos.length, k.suspendido), '#bf6d1e');
  drawSparkline('spark-resc', generateFlatSparkline(kpiData.sparkline_activos.length, k.rescision), '#8b1f1f');
  drawSparkline('spark-total', kpiData.sparkline_total, '#2d5a8e');

  // Tendencias
  const altasDelta = kpiData.altas_periodo - kpiData.altas_periodo_anterior;
  const trendAltas = document.getElementById('kpi-trend-altas');
  trendAltas.className = 'kpi-trend ' + (altasDelta > 0 ? 'up' : altasDelta < 0 ? 'down' : 'flat');
  trendAltas.textContent = altasDelta >= 0
    ? `▲ +${kpiData.altas_periodo} altas (${kpiData.periodo_dias}d)`
    : `▼ ${kpiData.altas_periodo} altas (${kpiData.periodo_dias}d)`;

  setText('kpi-trend-bajas', `▼ ${kpiData.bajas_periodo} bajas (${kpiData.periodo_dias}d)`);

  const trendTotal = document.getElementById('kpi-trend-total');
  if (kpiData.crecimiento_neto >= 0) {
    trendTotal.className = 'kpi-trend up';
    trendTotal.textContent = `▲ +${kpiData.crecimiento_neto} neto`;
  } else {
    trendTotal.className = 'kpi-trend down';
    trendTotal.textContent = `▼ ${kpiData.crecimiento_neto} neto`;
  }

  // KPIs secundarios
  setText('ds-fibra', (k.activos_fibra||0).toLocaleString());
  setText('ds-inalambrico', (k.activos_inalambrico||0).toLocaleString());
  setText('ds-svc-pend', d.servicios_pendientes||0);
  setText('ds-inc', (d.incidencias||[]).filter(i => i.estado === 'abierta').length);
  setText('ds-pte-inst', (k.pte_instalacion||0).toLocaleString());
  setText('ds-pte-calc', (k.pte_calculo||0).toLocaleString());
  setText('ds-borrador', (k.borrador||0).toLocaleString());

  // Filtro global: poblar localidades si hace falta
  poblarFiltroLocalidades();

  // Carrusel
  buildCarousel(d.incidencias||[]);

  // Donut estados
  if (distrib) {
    drawDonutEstados(distrib.estados, distrib.total);
    drawDonutTipos(distrib.tipos, distrib.total, distrib.potencial_migracion_ftth);
    drawBarLocalidades(distrib.localidades);
  }

  // Evolución mensual (altas vs bajas)
  if (evolucion) drawEvolucion(evolucion);

  // Incidencias compactas
  buildDashIncCompact(d.incidencias||[]);

  // Monitoreo
  loadDashMonitoreo();

  // Actualizar timestamp
  setText('gf-update', `actualizado ${new Date().toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'})}`);
  dashboardLastLoad = Date.now();
}

function drawSparkline(id, data, color) {
  const svg = document.getElementById(id);
  if (!svg || !data || !data.length) return;
  const w = 80, h = 50, pad = 5;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const step = (w - pad*2) / (data.length - 1 || 1);
  const points = data.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v - min) / range) * (h - pad*2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const pointsArea = `${pad},${h} ${points} ${(w-pad).toFixed(1)},${h}`;
  svg.innerHTML = `
    <polyline fill="${color}33" stroke="none" points="${pointsArea}"/>
    <polyline fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="${points}"/>
  `;
}

function drawDonutEstados(estados, total) {
  const wrap = document.getElementById('donut-estados');
  if (!wrap) return;

  const colorMap = {
    activo: '#439952', suspendido: '#bf6d1e',
    rescision: '#b03030', baja: '#5d6970'
  };

  // Donut SVG
  let svg = `<svg class="donut" viewBox="0 0 42 42">
    <circle cx="21" cy="21" r="15.91" fill="none" stroke="var(--card)" stroke-width="6"/>`;
  let offset = 25;
  estados.forEach(e => {
    const len = e.pct;
    svg += `<circle cx="21" cy="21" r="15.91" fill="none" stroke="${colorMap[e.estado]||'#9aa6b3'}" stroke-width="6"
      stroke-dasharray="${len} ${100-len}" stroke-dashoffset="${offset}" transform="rotate(-90 21 21)"/>`;
    offset -= len;
  });
  svg += `<text x="21" y="20" text-anchor="middle" font-size="5" font-weight="700" fill="#1a3d6b">${total.toLocaleString()}</text>`;
  svg += `<text x="21" y="25" text-anchor="middle" font-size="2.5" fill="#4a5c6a">total</text></svg>`;

  let legend = '<div class="donut-legend">';
  estados.forEach(e => {
    legend += `<div class="donut-legend-item">
      <span class="donut-legend-color" style="background:${colorMap[e.estado]||'#9aa6b3'}"></span>
      ${estadoLabel(e.estado)}
      <span class="donut-legend-pct">${e.pct}% · ${e.cantidad.toLocaleString()}</span>
    </div>`;
  });
  legend += '</div>';

  wrap.innerHTML = svg + legend;
}

function drawDonutTipos(tipos, total, potencialFtth) {
  const wrap = document.getElementById('donut-tipos');
  if (!wrap) return;

  const colorMap = {fibra: '#2d5a8e', inalambrico: '#7a4514'};

  let svg = `<svg class="donut" viewBox="0 0 42 42">
    <circle cx="21" cy="21" r="15.91" fill="none" stroke="var(--card)" stroke-width="6"/>`;
  let offset = 25;
  tipos.forEach(t => {
    svg += `<circle cx="21" cy="21" r="15.91" fill="none" stroke="${colorMap[t.tipo]||'#9aa6b3'}" stroke-width="6"
      stroke-dasharray="${t.pct} ${100-t.pct}" stroke-dashoffset="${offset}" transform="rotate(-90 21 21)"/>`;
    offset -= t.pct;
  });
  svg += `<text x="21" y="20" text-anchor="middle" font-size="5" font-weight="700" fill="#1a3d6b">${total.toLocaleString()}</text>`;
  svg += `<text x="21" y="25" text-anchor="middle" font-size="2.5" fill="#4a5c6a">total</text></svg>`;

  let legend = '<div class="donut-legend">';
  tipos.forEach(t => {
    const label = t.tipo === 'fibra' ? 'Fibra óptica' : t.tipo === 'inalambrico' ? 'Inalámbrico' : t.tipo;
    legend += `<div class="donut-legend-item">
      <span class="donut-legend-color" style="background:${colorMap[t.tipo]||'#9aa6b3'}"></span>
      ${label}
      <span class="donut-legend-pct">${t.pct}% · ${t.cantidad.toLocaleString()}</span>
    </div>`;
  });
  legend += '</div>';

  wrap.innerHTML = svg + legend;

  const ftthMsg = document.getElementById('ftth-potencial-msg');
  if (ftthMsg && potencialFtth > 0) {
    ftthMsg.innerHTML = `💡 <b>Oportunidad:</b> ${potencialFtth.toLocaleString()} clientes inalámbricos con vecinos de fibra a &lt;300m — <b>candidatos a migrar a FTTH</b>.`;
  }
}

function drawEvolucion(d) {
  const svg = document.getElementById('svg-evolucion');
  if (!svg) return;
  const w = 500, h = 200, pad = 30;
  const allValues = [...d.altas, ...d.bajas];
  const max = Math.max(...allValues, 5);
  const step = (w - pad*2) / Math.max(d.labels.length - 1, 1);

  // Grilla
  let html = '';
  [50, 100, 150].forEach(y => {
    html += `<line x1="${pad}" y1="${y}" x2="${w-pad}" y2="${y}" stroke="var(--surf2)" stroke-width="1"/>`;
  });

  // Línea altas
  const altasPoints = d.altas.map((v, i) => `${pad + i*step},${h - pad - (v/max)*(h-pad*2)}`).join(' ');
  const altasArea = `${pad},${h-pad} ${altasPoints} ${pad + (d.altas.length-1)*step},${h-pad}`;
  html += `<polyline fill="rgba(67,153,82,.2)" stroke="none" points="${altasArea}"/>`;
  html += `<polyline fill="none" stroke="#2a6632" stroke-width="2.5" points="${altasPoints}"/>`;

  // Línea bajas
  const bajasPoints = d.bajas.map((v, i) => `${pad + i*step},${h - pad - (v/max)*(h-pad*2)}`).join(' ');
  const bajasArea = `${pad},${h-pad} ${bajasPoints} ${pad + (d.bajas.length-1)*step},${h-pad}`;
  html += `<polyline fill="rgba(176,48,48,.15)" stroke="none" points="${bajasArea}"/>`;
  html += `<polyline fill="none" stroke="#8b1f1f" stroke-width="2.5" points="${bajasPoints}"/>`;

  // Labels
  d.labels.forEach((lbl, i) => {
    html += `<text x="${pad + i*step}" y="${h-5}" font-size="9" fill="#4a5c6a" text-anchor="middle">${lbl}</text>`;
  });

  svg.innerHTML = html;

  // Leyenda
  const leg = document.getElementById('evol-legend');
  leg.innerHTML = `
    <span><span style="display:inline-block;width:14px;height:3px;background:#2a6632;vertical-align:middle"></span> Altas (+${d.total_altas})</span>
    <span><span style="display:inline-block;width:14px;height:3px;background:#8b1f1f;vertical-align:middle"></span> Bajas (-${d.total_bajas})</span>
    <span style="margin-left:auto;font-weight:700;color:${d.crecimiento_neto>=0?'var(--vd)':'var(--rj)'}">Crecimiento neto: ${d.crecimiento_neto>=0?'+':''}${d.crecimiento_neto}</span>
  `;
}

async function loadCalendario(metric) {
  document.querySelectorAll('.cal-btn').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`.cal-btn[data-metric="${metric}"]`);
  if (btn) btn.classList.add('active');

  const d = await api(`/api/dashboard/calendario?metric=${metric}`);
  if (!d) return;
  const wrap = document.getElementById('heatmap-cal');
  // Agrupar por semana (52 columnas)
  const cellsHtml = d.data.map(c =>
    `<div class="heat-cal-cell ${c.nivel>0?'l'+c.nivel:''}" title="${c.fecha}: ${c.valor} ${metric}"></div>`
  ).join('');
  wrap.innerHTML = cellsHtml;
  setText('cal-stats', `Total ${metric}: ${d.total} · Promedio: ${d.promedio}/día`);
}

function filtroRiesgo(tipo) {
  // Navega a clientes con filtro pre-aplicado
  navGo('clientes');
  // Aplicar filtros según tipo
  setTimeout(() => {
    const estado = document.getElementById('cli-estado');
    if (tipo === 'suspendidos_30') {
      if (estado) { estado.value = 'suspendido'; loadClientes(); }
    } else if (tipo === 'rescision_60') {
      if (estado) { estado.value = 'rescision'; loadClientes(); }
    }
  }, 100);
}

async function loadBajas(){
  const loc=document.getElementById('baja-loc').value;
  const tipo=document.getElementById('baja-tipo').value;
  const orden=document.getElementById('baja-orden').value;
  const d=await api(`/api/bajas?localidad=${encodeURIComponent(loc)}&tipo=${tipo}&orden=${orden}`);
  if(!d) return;
  document.getElementById('baja-total').textContent=d.length;
  const tbody=document.getElementById('baja-tbody');
  tbody.innerHTML=d.map(c=>`<tr class="baja-row">
    <td><b>${escHtml(c.nombre)}</b></td>
    <td>${escHtml(c.telefono)||'—'}</td>
    <td>${escHtml(c.localidad)||'—'}</td>
    <td><span class="badge b-${escHtml(c.tipo_servicio)}">${escHtml(c.tipo_servicio)}</span></td>
    <td>${escHtml(c.equipo_modelo)||'—'}<br><small style="color:var(--txt2);font-family:monospace">${escHtml(c.equipo_serie)}</small></td>
    <td>${escHtml(c.nap)||'—'}</td>
    <td>${escHtml(c.fecha_rescision)||'—'}</td>
    <td class="${c.dias_pendiente>60?'dias-high':c.dias_pendiente>30?'dias-med':''}">${escHtml(c.dias_pendiente)} días</td>
    <td><span class="badge b-${escHtml(c.estado)}">${escHtml(estadoLabel(c.estado))}</span></td>
    <td><button class="btn btn-gray btn-xs" onclick="openModalCliente(${c.id})">✏️</button></td>
  </tr>`).join('');
}

function exportBajas(){
  const loc=document.getElementById('baja-loc').value;
  const tipo=document.getElementById('baja-tipo').value;
  window.location.href=`/api/bajas/export?localidad=${encodeURIComponent(loc)}&tipo=${tipo}`;
}

// ── ABONOS ──

// ════════════════════════════════════════════════════════
// AUDITORÍA DE DATOS (solo admin)
// ════════════════════════════════════════════════════════
function mostrarCardAuditoria(){
  const card = document.getElementById('dash-auditoria-card');
  if(card && typeof currentUser !== 'undefined' &&
     (currentUser.rol === 'admin' || currentUser.rol === 'root')){
    card.style.display = 'block';
  }
}

async function correrAuditoria(){
  const cont = document.getElementById('dash-auditoria');
  cont.innerHTML = '<div style="padding:.5rem;color:var(--txt2)">Ejecutando validaciones...</div>';
  const d = await api('/api/auditoria/datos');
  if(!d){ cont.innerHTML = '<div style="color:#c62828">Error al ejecutar la auditoría</div>'; return; }
  if(!d.checks.length){
    cont.innerHTML = '<div style="padding:.6rem;background:var(--card);border-radius:8px;color:#2e7d32;font-weight:600">✓ Sin problemas detectados. Los datos están consistentes.</div>';
    return;
  }
  const sevColor = {alta:'#c62828', media:'#e65100', baja:'#757575'};
  const sevLabel = {alta:'ALTA', media:'MEDIA', baja:'BAJA'};
  let html = `<div style="margin-bottom:.6rem;font-weight:700">Se detectaron ${d.total_problemas} problema(s) en ${d.checks.length} categoría(s):</div>`;
  html += d.checks.map((c,i)=>`
    <details style="border:1px solid var(--brd);border-left:4px solid ${sevColor[c.severidad]};border-radius:6px;margin-bottom:.4rem;background:var(--card)">
      <summary style="padding:.5rem .7rem;cursor:pointer;font-weight:600;display:flex;align-items:center;gap:.5rem">
        <span class="badge" style="background:${sevColor[c.severidad]};color:#fff;font-size:.62rem">${sevLabel[c.severidad]}</span>
        ${c.titulo}
        <span style="margin-left:auto;font-weight:800;color:${sevColor[c.severidad]}">${c.cantidad}</span>
      </summary>
      <div style="padding:.4rem .9rem .7rem;font-size:.8rem;max-height:260px;overflow-y:auto">
        ${c.items.map(it=>{
          const texto = typeof it === 'string' ? it : it.texto;
          const clientes = (typeof it === 'object' && it.clientes) ? it.clientes : [];
          const links = clientes.filter(cl=>cl.id).map(cl=>
            `<a href="javascript:void(0)" onclick="openModalCliente(${cl.id})" style="color:#1565c0;text-decoration:underline;margin-right:.6rem" title="Abrir y corregir">✏️ ${escHtml(cl.nombre)}</a>`
          ).join('');
          return `<div style="padding:.25rem 0;border-bottom:1px solid var(--brd)">${texto}${links?`<div style="margin-top:.15rem">${links}</div>`:''}</div>`;
        }).join('')}
        ${c.cantidad > c.items.length ? `<div style="padding:.3rem 0;color:var(--txt2)">… y ${c.cantidad - c.items.length} más</div>` : ''}
      </div>
    </details>`).join('');
  cont.innerHTML = html;
}

// ── Dashboard por rol: mostrar/ocultar secciones según permiso de módulo ──
function _gateDashboardSecciones(){
  const isAdmin = currentUser && (currentUser.rol === 'admin' || currentUser.rol === 'root');
  document.querySelectorAll('#page-dashboard [data-req-modulo]').forEach(el => {
    const modulo = el.getAttribute('data-req-modulo');
    // admin ve todo; el resto según _modAccesible (usa los permisos ya cargados)
    const permitido = isAdmin || (typeof _modAccesible === 'function' && _modAccesible(modulo));
    el.style.display = permitido ? '' : 'none';
  });
  // Cargar planes si la tarjeta quedó visible (perfil comercial)
  const planesCard = document.getElementById('dash-planes-card');
  if(planesCard && planesCard.style.display !== 'none'){
    _cargarPlanesDashboard();
  }
}

async function _cargarPlanesDashboard(){
  const cont = document.getElementById('dash-planes-list');
  if(!cont || cont.dataset.cargado) return;
  const planes = await api('/api/abonos');
  if(!planes || !planes.length){ cont.innerHTML = '<span style="color:var(--txt2)">Sin planes cargados.</span>'; return; }
  cont.dataset.cargado = '1';
  // Agrupar por tipo, mostrar nombre + velocidad + precio
  const porTipo = {};
  planes.forEach(p => { (porTipo[p.tipo] = porTipo[p.tipo] || []).push(p); });
  cont.innerHTML = Object.entries(porTipo).map(([tipo, arr]) => `
    <div style="margin-bottom:.7rem">
      <div style="font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;color:var(--txt2);margin-bottom:.3rem">${tipo}</div>
      <div style="display:flex;flex-wrap:wrap;gap:.5rem">
        ${arr.map(p => `<div style="background:var(--card);border:1px solid var(--brd);border-radius:8px;padding:.5rem .7rem;min-width:140px">
          <div style="font-weight:600">${p.nombre}</div>
          ${p.velocidad_bajada ? `<div style="font-size:.75rem;color:var(--txt2)">${p.velocidad_bajada}↓ / ${p.velocidad_subida||0}↑ Mbps</div>` : ''}
          <div style="font-family:'IBM Plex Mono',monospace;font-size:.9rem;color:var(--vd2,#4FB88A);margin-top:.2rem">$${(p.precio||0).toLocaleString('es-AR')}</div>
        </div>`).join('')}
      </div>
    </div>`).join('');
}

// ── Banner de tareas pendientes en el dashboard ──
async function _cargarBannerTareas(){
  const banner = document.getElementById('dash-tareas-banner');
  if(!banner) return;
  try {
    const r = await api('/api/tareas/pendientes');
    const n = r && typeof r.pendientes === 'number' ? r.pendientes : 0;
    if(n > 0){
      document.getElementById('dash-tareas-num').textContent = n;
      document.getElementById('dash-tareas-lbl').textContent = n === 1 ? 'tarea pendiente' : 'tareas pendientes';
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  } catch(e){
    banner.style.display = 'none';
  }
}

// ── Banner de señal óptica crítica en el dashboard ──
async function _cargarBannerOnuCriticas(){
  const banner = document.getElementById('dash-onu-banner');
  if(!banner) return;
  try {
    const r = await api('/api/onus/alertas-count');
    const n = r && typeof r.criticas === 'number' ? r.criticas : 0;
    if(n > 0){
      document.getElementById('dash-onu-num').textContent = n;
      document.getElementById('dash-onu-lbl').textContent = n === 1
        ? 'cliente con señal óptica crítica' : 'clientes con señal óptica crítica';
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  } catch(e){ banner.style.display = 'none'; }
}

// ── Estado de servicios grandes (desplegable en el dashboard) ──
function _toggleServicios(){
  const body = document.getElementById('dash-serv-body');
  const flecha = document.getElementById('dash-serv-flecha');
  if(!body) return;
  if(body.style.display === 'none'){ body.style.display='block'; if(flecha) flecha.textContent='▲'; }
  else { body.style.display='none'; if(flecha) flecha.textContent='▼'; }
}

function _servicioColor(e){
  return ({none:'#4FB3AA',minor:'#E0A838',major:'#E08063',critical:'#E0605F',unknown:'#566B84',sin_datos:'#566B84'})[e] || '#566B84';
}
function _servicioTxt(e){
  return ({none:'Operativo',minor:'Problemas menores',major:'Caída parcial',critical:'Caída total',unknown:'?',sin_datos:'sin datos'})[e] || e;
}
function _servicioFila(s){
  const c = _servicioColor(s.estado);
  return `<div style="display:flex;align-items:center;gap:.6rem;padding:.4rem .2rem;border-bottom:1px solid var(--brd)">
    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c};flex-shrink:0"></span>
    <b style="min-width:110px">${s.nombre}</b>
    <span style="color:${c};font-size:.82rem;white-space:nowrap">${_servicioTxt(s.estado)}</span>
    ${s.incidente?`<span style="font-size:.75rem;color:var(--txt2);margin-left:.4rem;overflow:hidden;text-overflow:ellipsis">— ${s.incidente}</span>`:''}
  </div>`;
}

async function _cargarServiciosEstado(){
  const resumen = document.getElementById('dash-serv-resumen');
  const body = document.getElementById('dash-serv-body');
  if(!resumen || !body) return;
  let servicios = null;
  try { servicios = await api('/api/servicios-estado'); } catch(e){ resumen.textContent='no disponible'; return; }
  if(!servicios || !servicios.length){ resumen.textContent='no disponible'; return; }
  const conProblemas = servicios.filter(s=>['critical','major','minor'].includes(s.estado));
  if(conProblemas.length === 0){
    resumen.innerHTML = '<span style="color:#4FB3AA">✅ Todos operativos</span>';
  } else {
    resumen.innerHTML = `<span style="color:#E0605F;font-weight:600">⚠ ${conProblemas.length} con problemas: ${conProblemas.map(s=>s.nombre).join(', ')}</span>`;
    // Auto-desplegar cuando hay caídas
    body.style.display = 'block';
    const flecha = document.getElementById('dash-serv-flecha');
    if(flecha) flecha.textContent = '▲';
  }
  body.innerHTML = servicios.map(_servicioFila).join('') +
    '<div style="font-size:.68rem;color:var(--txt2);margin-top:.5rem">Fuente: páginas de estado oficiales · se actualiza cada pocos minutos</div>';
}

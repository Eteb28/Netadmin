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
}

async function loadDash(){
  const f = getFiltrosDashboard();
  const qs = `localidad=${encodeURIComponent(f.localidad)}&tipo=${f.tipo}&periodo=${f.periodo}`;

  // Carga en paralelo
  const [d, kpiData, riesgos, distrib, topNaps, evolucion, heatHorarios, napsAgrup] = await Promise.all([
    api('/api/dashboard'),
    api(`/api/dashboard/kpis?${qs}`),
    api('/api/dashboard/riesgos'),
    api('/api/dashboard/distribucion'),
    api('/api/dashboard/top_naps_crecimiento'),
    api('/api/dashboard/evolucion_mensual'),
    api('/api/dashboard/heatmap_horarios'),
    api('/api/dashboard/naps_agrupadas')
  ]);

  if (!d || !kpiData) return;

  // KPIs principales
  const k = kpiData.kpis;
  setText('kpi-activos', (k.activo||0).toLocaleString());
  setText('kpi-suspendidos', (k.suspendido||0).toLocaleString());
  setText('kpi-rescision', (k.rescision||0).toLocaleString());
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

  // Riesgos
  if (riesgos) {
    setText('rg-sus-30', riesgos.suspendidos_30dias.toLocaleString());
    setText('rg-pago-15', riesgos.pago_vencido_15dias.toLocaleString());
    setText('rg-deuda', `$${(riesgos.deuda_total||0).toLocaleString('es-AR',{maximumFractionDigits:0})} en deuda`);
    setText('rg-resc-60', riesgos.rescision_60dias_equipo.toLocaleString());
    setText('rg-svc-48', riesgos.servicios_sin_tecnico_48h.toLocaleString());

    if (riesgos.requieren_revision > 0) {
      document.getElementById('rg-revision-alert').style.display = 'block';
      setText('rg-revision-count', riesgos.requieren_revision.toLocaleString());
    }
  }

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

  // Top NAPs
  if (topNaps) drawTopNaps(topNaps);

  // Evolución mensual
  if (evolucion) drawEvolucion(evolucion);

  // Heatmap horarios
  if (heatHorarios) drawHeatmapHorarios(heatHorarios);

  // NAPs agrupadas
  if (napsAgrup) drawNapsAgrupadas(napsAgrup);

  // Calendario (default: altas)
  loadCalendario('altas');

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
    <circle cx="21" cy="21" r="15.91" fill="none" stroke="#e8edf2" stroke-width="6"/>`;
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
    <circle cx="21" cy="21" r="15.91" fill="none" stroke="#e8edf2" stroke-width="6"/>`;
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
    html += `<line x1="${pad}" y1="${y}" x2="${w-pad}" y2="${y}" stroke="#e0e6ee" stroke-width="1"/>`;
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
    <td><b>${c.nombre}</b></td>
    <td>${c.telefono||'—'}</td>
    <td>${c.localidad||'—'}</td>
    <td><span class="badge b-${c.tipo_servicio}">${c.tipo_servicio}</span></td>
    <td>${c.equipo_modelo||'—'}<br><small style="color:var(--txt2);font-family:monospace">${c.equipo_serie||''}</small></td>
    <td>${c.nap||'—'}</td>
    <td>${c.fecha_rescision||'—'}</td>
    <td class="${c.dias_pendiente>60?'dias-high':c.dias_pendiente>30?'dias-med':''}">${c.dias_pendiente} días</td>
    <td><span class="badge b-${c.estado}">${estadoLabel(c.estado)}</span></td>
    <td><button class="btn btn-gray btn-xs" onclick="openModalCliente(${c.id})">✏️</button></td>
  </tr>`).join('');
}

function exportBajas(){
  const loc=document.getElementById('baja-loc').value;
  const tipo=document.getElementById('baja-tipo').value;
  window.location.href=`/api/bajas/export?localidad=${encodeURIComponent(loc)}&tipo=${tipo}`;
}

// ── ABONOS ──

/* ========================================================
   finanzas.js — ERLAN NetAdmin
   Módulo financiero: facturación, morosidad, proyección
   ======================================================== */

async function loadFinanzas(){
  const [resumen, morosidad, evolucion, planes, torres, olts, naps, funnel, salud, instMetricas] = await Promise.all([
    api('/api/finanzas/resumen'),
    api('/api/finanzas/morosidad?agrupar=localidad'),
    api('/api/finanzas/evolucion'),
    api('/api/finanzas/top_planes'),
    api('/api/finanzas/ingreso_por_torre'),
    api('/api/finanzas/ingreso_por_olt'),
    api('/api/finanzas/ingreso_por_nap'),
    api('/api/finanzas/funnel_instalacion'),
    api('/api/finanzas/salud_base'),
    api('/api/finanzas/instalaciones_metricas'),
  ]);
  if(resumen) renderFinResumen(resumen);
  if(salud) renderFinSalud(salud);
  if(instMetricas) renderFinInstalaciones(instMetricas);
  if(funnel) renderFinFunnel(funnel);
  if(morosidad) renderFinMorosidad(morosidad);
  if(evolucion) renderFinEvolucion(evolucion);
  if(torres) renderFinTorres(torres);
  if(olts) renderFinOlts(olts);
  if(naps) renderFinNaps(naps);
  if(planes) renderFinPlanes(planes);
}

function fmtMoney(n){ return '$' + (n||0).toLocaleString('es-AR', {minimumFractionDigits:0, maximumFractionDigits:0}); }

function renderFinResumen(r){
  const el = document.getElementById('fin-resumen');
  if(!el) return;
  el.innerHTML = `
    <div class="fin-grid">
      <div class="fin-card green">
        <div class="fin-val">${fmtMoney(r.ingreso_mensual)}</div>
        <div class="fin-lbl">Ingreso mensual proyectado</div>
        <div class="fin-sub">
          <span>Fibra: ${fmtMoney(r.ingreso_fibra)}</span> · 
          <span>Inalámbrico: ${fmtMoney(r.ingreso_inalambrico)}</span>
        </div>
      </div>
      <div class="fin-card blue">
        <div class="fin-val">${fmtMoney(r.ticket_promedio)}</div>
        <div class="fin-lbl">Ticket promedio</div>
        <div class="fin-sub">${r.activos_con_precio} clientes activos con precio</div>
      </div>
      <div class="fin-card orange">
        <div class="fin-val">${r.morosos}</div>
        <div class="fin-lbl">Clientes morosos (+35 días)</div>
        <div class="fin-sub">Monto en riesgo: ${fmtMoney(r.morosos_monto)}</div>
      </div>
      <div class="fin-card red">
        <div class="fin-val">${fmtMoney(r.deuda_suspendidos)}</div>
        <div class="fin-lbl">Deuda suspendidos (${r.suspendidos})</div>
        <div class="fin-sub">Ingreso perdido rescisión: ${fmtMoney(r.ingreso_perdido_rescision)}</div>
      </div>
    </div>`;
}

function renderFinMorosidad(data){
  const el = document.getElementById('fin-morosidad');
  if(!el || !data.length) return;
  const maxMorosos = Math.max(...data.map(d=>d.morosos)) || 1;
  el.innerHTML = `
    <div class="fin-section">
      <div class="fin-section-header">
        <h3>📊 Morosidad por localidad</h3>
        <select id="fin-agrupar" onchange="changeFinAgrupacion()" style="font-size:.8rem;padding:.2rem .4rem">
          <option value="localidad">Por localidad</option>
          <option value="plan">Por plan</option>
          <option value="tipo_servicio">Por tipo</option>
        </select>
      </div>
      <table class="fin-table">
        <thead><tr><th>Grupo</th><th>Total</th><th>Morosos</th><th>Tasa</th><th>Monto moroso</th><th></th></tr></thead>
        <tbody>${data.slice(0,15).map(d=>`
          <tr>
            <td><b>${d.grupo}</b></td>
            <td>${d.total}</td>
            <td style="color:#c62828;font-weight:700">${d.morosos}</td>
            <td>
              <div style="display:flex;align-items:center;gap:.3rem">
                <div style="background:var(--card);border-radius:3px;height:14px;width:80px;overflow:hidden">
                  <div style="background:#c62828;height:100%;width:${Math.min(d.tasa,100)}%"></div>
                </div>
                <span style="font-size:.75rem">${d.tasa}%</span>
              </div>
            </td>
            <td style="font-weight:600">${fmtMoney(d.monto_moroso)}</td>
            <td style="font-size:.75rem;color:var(--txt2)">${fmtMoney(d.ingreso_total)}</td>
          </tr>
        `).join('')}</tbody>
      </table>
    </div>`;
}

async function changeFinAgrupacion(){
  const a = document.getElementById('fin-agrupar').value;
  const data = await api(`/api/finanzas/morosidad?agrupar=${a}`);
  if(data) renderFinMorosidad(data);
  // Restore selection
  setTimeout(()=>{const s=document.getElementById('fin-agrupar');if(s)s.value=a;},50);
}

function renderFinEvolucion(data){
  const el = document.getElementById('fin-evolucion');
  if(!el) return;
  // Nuevo formato: { ingresos:{mes_anterior,mes_actual,proyeccion_siguiente}, bajas:{...}, meses:[] }
  const ing = data.ingresos || {};
  const baj = data.bajas || {};
  const meses = data.meses || [];
  const maxAltas = Math.max(...meses.map(d=>Math.max(d.altas,d.bajas)), 1);

  const nombreMes = (m) => {
    if(!m) return '';
    const [y,mm] = m.split('-');
    const nombres = ['','Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
    return `${nombres[parseInt(mm)]} ${y}`;
  };

  el.innerHTML = `
    <div class="fin-section">
      <h3>💰 Ingresos mensuales</h3>
      <div class="fin-grid" style="margin-bottom:.5rem">
        <div class="fin-card">
          <div class="fin-val">${fmtMoney(ing.mes_anterior?.monto||0)}</div>
          <div class="fin-lbl">Mes anterior · ${nombreMes(ing.mes_anterior?.mes)}</div>
          <div class="fin-sub">${ing.mes_anterior?.tipo==='real'?'facturación real':'estimado'}</div>
        </div>
        <div class="fin-card green">
          <div class="fin-val">${fmtMoney(ing.mes_actual?.monto||0)}</div>
          <div class="fin-lbl">Mes en curso · ${nombreMes(ing.mes_actual?.mes)}</div>
          <div class="fin-sub">${ing.mes_actual?.tipo==='real'?'facturación real':'estimado'}</div>
        </div>
        <div class="fin-card" style="border-left:4px solid #7b1fa2">
          <div class="fin-val">${fmtMoney(ing.proyeccion_siguiente?.monto||0)}</div>
          <div class="fin-lbl">Proyección · ${nombreMes(ing.proyeccion_siguiente?.mes)}</div>
          <div class="fin-sub">promedio últimos 3 meses</div>
        </div>
      </div>

      <h3 style="margin-top:1rem">📉 Bajas (rescisiones)</h3>
      <div class="fin-grid" style="margin-bottom:1rem">
        <div class="fin-card" style="border-left:4px solid #c62828">
          <div class="fin-val">${baj.mes_anterior?.cantidad||0}</div>
          <div class="fin-lbl">Bajas mes anterior · ${nombreMes(baj.mes_anterior?.mes)}</div>
          <div class="fin-sub">−${fmtMoney(baj.mes_anterior?.perdida_ingreso||0)} / mes</div>
        </div>
        <div class="fin-card" style="border-left:4px solid #e53935">
          <div class="fin-val">${baj.mes_actual?.cantidad||0}</div>
          <div class="fin-lbl">Bajas mes en curso · ${nombreMes(baj.mes_actual?.mes)}</div>
          <div class="fin-sub">−${fmtMoney(baj.mes_actual?.perdida_ingreso||0)} / mes</div>
        </div>
      </div>

      <h3>📈 Altas vs bajas mensuales (12 meses)</h3>
      <div style="display:flex;align-items:flex-end;gap:6px;height:200px;padding:1rem 0;border-bottom:1px solid var(--brd)">
        ${meses.map(d=>{
          const hAlta = Math.round((d.altas/maxAltas)*140);
          const hBaja = Math.round((d.bajas/maxAltas)*140);
          const mesLabel = d.mes.split('-')[1] + '/' + d.mes.split('-')[0].slice(2);
          const netoColor = d.neto >= 0 ? '#2e7d32' : '#c62828';
          return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;justify-content:flex-end;height:100%">
            <div style="font-size:.6rem;color:var(--txt2)">${d.altas}</div>
            <div style="display:flex;gap:2px;align-items:flex-end">
              <div style="background:#2e7d32;width:12px;height:${hAlta}px;border-radius:2px 2px 0 0" title="Altas: ${d.altas}"></div>
              <div style="background:#c62828;width:12px;height:${hBaja}px;border-radius:2px 2px 0 0" title="Bajas: ${d.bajas}"></div>
            </div>
            <div style="font-size:.6rem;margin-top:3px;color:var(--txt2)">${mesLabel}</div>
            <div style="font-size:.6rem;font-weight:700;color:${netoColor}">${d.neto>=0?'+':''}${d.neto}</div>
          </div>`;
        }).join('')}
      </div>
      <div style="display:flex;gap:1rem;font-size:.72rem;margin-top:.5rem;color:var(--txt2)">
        <span><span style="display:inline-block;width:10px;height:10px;background:#2e7d32;border-radius:2px"></span> Altas (instalaciones)</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#c62828;border-radius:2px"></span> Bajas (rescisiones)</span>
        <span>Número inferior = crecimiento neto</span>
      </div>
    </div>`;
}

function renderFinInstalaciones(data){
  const el = document.getElementById('fin-instalaciones');
  if(!el) return;
  const demoras = data.demora_por_medio || [];
  const porMes = data.por_mes || [];
  const vendedores = data.ranking_vendedores || [];
  const maxMes = Math.max(...porMes.map(d=>d.total), 1);

  // Tarjetas de demora por medio
  const demoraCards = demoras.map(d => {
    const color = d.medio.toLowerCase().includes('fibra') ? '#1565c0' : '#e65100';
    return `<div class="fin-card" style="border-left:4px solid ${color}">
      <div class="fin-val" style="font-size:1.4rem">${d.demora_promedio_dias ?? '—'} días</div>
      <div class="fin-lbl">Demora promedio · ${d.medio}</div>
      <div class="fin-sub"><span>${d.cantidad} instal.</span> · <span>mín ${d.demora_min_dias}d / máx ${d.demora_max_dias}d</span></div>
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="fin-section">
      <h3>🛠️ Instalaciones</h3>
      <div class="fin-grid" style="margin-bottom:1rem">
        <div class="fin-card green">
          <div class="fin-val">${data.total_realizadas}</div>
          <div class="fin-lbl">Instalaciones realizadas</div>
        </div>
        <div class="fin-card" style="border-left:4px solid #f9a825">
          <div class="fin-val">${data.pendientes}</div>
          <div class="fin-lbl">Pendientes</div>
        </div>
        ${demoraCards}
      </div>

      <h3 style="margin-top:1rem">📊 Instalaciones por mes</h3>
      <div style="display:flex;align-items:flex-end;gap:6px;height:180px;padding:1rem 0;border-bottom:1px solid var(--brd)">
        ${porMes.map(d=>{
          const hF = Math.round((d.fibra/maxMes)*130);
          const hI = Math.round((d.inalambrico/maxMes)*130);
          const mesLabel = d.mes.split('-')[1] + '/' + d.mes.split('-')[0].slice(2);
          return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;justify-content:flex-end;height:100%">
            <div style="font-size:.6rem;color:var(--txt2)">${d.total}</div>
            <div style="display:flex;flex-direction:column;justify-content:flex-end;width:60%;min-width:14px">
              <div style="background:#1565c0;height:${hF}px;border-radius:2px 2px 0 0" title="Fibra: ${d.fibra}"></div>
              <div style="background:#e65100;height:${hI}px" title="Inalámbrico: ${d.inalambrico}"></div>
            </div>
            <div style="font-size:.6rem;margin-top:3px;color:var(--txt2)">${mesLabel}</div>
          </div>`;
        }).join('')}
      </div>
      <div style="display:flex;gap:1rem;font-size:.72rem;margin-top:.5rem;color:var(--txt2)">
        <span><span style="display:inline-block;width:10px;height:10px;background:#1565c0;border-radius:2px"></span> Fibra</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#e65100;border-radius:2px"></span> Inalámbrico</span>
      </div>

      <h3 style="margin-top:1rem">🏅 Ranking de vendedores</h3>
      <table class="tbl" style="margin-top:.5rem">
        <thead><tr><th>Vendedor</th><th style="text-align:right">Instalaciones</th></tr></thead>
        <tbody>
          ${vendedores.map(v=>`<tr><td>${v.vendedor}</td><td style="text-align:right"><b>${v.instalaciones}</b></td></tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function renderFinPlanes(data){
  const el = document.getElementById('fin-planes');
  if(!el || !data.length) return;
  el.innerHTML = `
    <div class="fin-section">
      <h3>🏆 Top planes por ingreso</h3>
      <table class="fin-table">
        <thead><tr><th>Plan</th><th>Clientes</th><th>Precio prom.</th><th>Ingreso total</th></tr></thead>
        <tbody>${data.map(d=>`
          <tr>
            <td><b>${d.plan}</b></td>
            <td>${d.clientes}</td>
            <td>${fmtMoney(d.precio_prom)}</td>
            <td style="font-weight:700;color:#2e7d32">${fmtMoney(d.ingreso)}</td>
          </tr>
        `).join('')}</tbody>
      </table>
    </div>`;
}

async function loadMorososDetalle(){
  const data = await api('/api/finanzas/detalle_morosos');
  if(!data) return;
  const el = document.getElementById('fin-morosos-detalle');
  if(!el) return;
  el.innerHTML = `
    <div class="fin-section">
      <h3>⚠️ Detalle de clientes morosos (${data.length})</h3>
      <table class="fin-table">
        <thead><tr><th>Cliente</th><th>Localidad</th><th>Plan</th><th>Precio</th><th>Último pago</th><th>Días mora</th><th></th></tr></thead>
        <tbody>${data.map(d=>`
          <tr>
            <td><b>${d.nombre}</b><br><small>${d.nro_cliente||''}</small></td>
            <td>${d.localidad||'—'}</td>
            <td>${d.plan||'—'}</td>
            <td>${fmtMoney(d.precio)}</td>
            <td>${d.ultimo_pago||'—'}</td>
            <td style="color:#c62828;font-weight:700">${d.dias_mora} días</td>
            <td><button class="btn btn-gray btn-xs" onclick="openModalCliente(${d.id})">Ver</button></td>
          </tr>
        `).join('')}</tbody>
      </table>
    </div>`;
}

async function exportMorososCSV(){
  const data = await api('/api/finanzas/detalle_morosos');
  if(!data || !data.length) return;
  let csv = 'Nombre,Nro Cliente,Telefono,Localidad,Plan,Precio,Ultimo Pago,Dias Mora\n';
  data.forEach(d=>{
    csv += `"${d.nombre}","${d.nro_cliente||''}","${d.telefono||''}","${d.localidad||''}","${d.plan||''}",${d.precio||0},"${d.ultimo_pago||''}",${d.dias_mora}\n`;
  });
  const blob = new Blob([csv], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `morosos_${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
}

// ── SALUD DE LA BASE ──
function renderFinSalud(s){
  const el = document.getElementById('fin-salud');
  if(!el) return;
  const saludColor = s.salud_pct > 70 ? '#2e7d32' : s.salud_pct > 50 ? '#e65100' : '#c62828';
  el.innerHTML = `
    <div class="fin-section">
      <h3>🏥 Salud de la base</h3>
      <div style="display:flex;gap:.8rem;flex-wrap:wrap;margin-bottom:.6rem">
        <div style="text-align:center;min-width:100px">
          <div style="position:relative;width:80px;height:80px;margin:0 auto">
            <svg viewBox="0 0 36 36" style="width:80px;height:80px;transform:rotate(-90deg)">
              <circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--surf2)" stroke-width="3"/>
              <circle cx="18" cy="18" r="15.9" fill="none" stroke="${saludColor}" stroke-width="3"
                stroke-dasharray="${s.salud_pct} ${100-s.salud_pct}" stroke-linecap="round"/>
            </svg>
            <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:1.1rem;font-weight:800;color:${saludColor}">${s.salud_pct}%</div>
          </div>
          <div style="font-size:.7rem;color:#666;margin-top:.2rem">Activos / Total</div>
        </div>
        <div style="flex:1;font-size:.8rem;display:grid;gap:.2rem">
          <div>✅ Activos: <b>${s.activos}</b></div>
          <div>⏸ Suspendidos: <b>${s.suspendidos}</b></div>
          <div>⚠ Pte. Rescisión: <b style="color:#c62828">${s.pte_rescision}</b></div>
          <div>❌ Rescindidos: <b>${s.rescindidos}</b></div>
        </div>
        <div style="flex:1;font-size:.8rem;display:grid;gap:.2rem">
          <div>🔵 Fibra: <b>${s.fibra}</b> (${s.ratio_fibra}%) — ARPU ${fmtMoney(s.arpu_fibra)}</div>
          <div>📡 Inalámbrico: <b>${s.inalambrico}</b> — ARPU ${fmtMoney(s.arpu_inalambrico)}</div>
          <hr style="margin:.2rem 0">
          <div style="color:#888">⚠ Sin coords: ${s.sin_coords} · Sin email: ${s.sin_email} · Sin tel: ${s.sin_telefono}</div>
        </div>
      </div>
      ${s.localidades?.length ? `
      <details><summary style="cursor:pointer;font-size:.82rem;font-weight:600">📍 Top localidades</summary>
      <table class="fin-table" style="margin-top:.3rem">
        <thead><tr><th>Localidad</th><th>Activos</th><th>Susp.</th><th>Perdidos</th><th>Ingreso</th></tr></thead>
        <tbody>${s.localidades.map(l=>`<tr>
          <td><b>${l.localidad}</b></td><td>${l.activos}</td><td>${l.suspendidos}</td>
          <td style="color:#c62828">${l.perdidos}</td><td style="color:#2e7d32">${fmtMoney(l.ingreso)}</td>
        </tr>`).join('')}</tbody>
      </table></details>` : ''}
    </div>`;
}

// ── CHURN RATE ──
function renderFinChurn(data){
  const el = document.getElementById('fin-churn');
  if(!el || !data.length) return;
  const maxChurn = Math.max(...data.map(d=>d.churn_pct), 1);
  el.innerHTML = `
    <div class="fin-section">
      <h3>📉 Churn Rate mensual</h3>
      <div style="display:flex;align-items:flex-end;gap:3px;height:160px;padding:.5rem 0;border-bottom:1px solid var(--brd)">
        ${data.map(d=>{
          const h = Math.max(Math.round(d.churn_pct / maxChurn * 130), 4);
          const color = d.churn_pct > 5 ? '#c62828' : d.churn_pct > 3 ? '#e65100' : '#2e7d32';
          const mesLbl = d.mes.split('-')[1]+'/'+d.mes.split('-')[0].slice(2);
          return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;min-width:0">
            <div style="font-size:.55rem;color:${color};font-weight:700">${d.churn_pct}%</div>
            <div style="background:${color};width:70%;min-width:14px;height:${h}px;border-radius:3px 3px 0 0"></div>
            <div style="font-size:.55rem;margin-top:2px;color:var(--txt2)">${mesLbl}</div>
            <div style="font-size:.5rem;color:#888">+${d.altas} -${d.bajas}</div>
          </div>`;
        }).join('')}
      </div>
      <div style="margin-top:.4rem;font-size:.75rem;display:flex;gap:1rem;color:#666">
        <span>Último mes: <b style="color:${data[data.length-1]?.churn_pct > 3 ? '#c62828' : '#2e7d32'}">${data[data.length-1]?.churn_pct}%</b></span>
        <span>Promedio: <b>${(data.reduce((a,d)=>a+d.churn_pct,0)/data.length).toFixed(1)}%</b></span>
        <span>Crecimiento neto último mes: <b style="color:${data[data.length-1]?.crecimiento_neto >= 0 ? '#2e7d32' : '#c62828'}">${data[data.length-1]?.crecimiento_neto >= 0 ? '+' : ''}${data[data.length-1]?.crecimiento_neto}</b></span>
      </div>
    </div>`;
}

// ── FUNNEL DE INSTALACIÓN ──
function renderFinFunnel(d){
  const el = document.getElementById('fin-funnel');
  if(!el) return;
  const f = d.funnel;
  const total = d.total_pipeline;
  const steps = [
    {key:'borrador', label:'📝 Borrador', val:f.borrador, color:'#78909c'},
    {key:'pte_calculo', label:'📐 Pte. Cálculo', val:f.pte_calculo, color:'#f9a825'},
    {key:'pte_instalacion', label:'🔧 Pte. Instalación', val:f.pte_instalacion, color:'#1565c0'},
    {key:'pte_cambio', label:'🔄 Pte. Cambio', val:f.pte_cambio, color:'#00897b'},
    {key:'convertidos', label:'✅ Convertidos (90d)', val:f.convertidos_90d, color:'#2e7d32'},
  ];
  const maxVal = Math.max(...steps.map(s=>s.val), 1);
  el.innerHTML = `
    <div class="fin-section">
      <h3>🔀 Pipeline de instalaciones</h3>
      <div style="display:flex;gap:.3rem;margin-bottom:.5rem;flex-wrap:wrap">
        ${steps.map(s=>`
          <div style="flex:1;min-width:80px;text-align:center;padding:.4rem;border-radius:8px;background:${s.color}11;border:1px solid ${s.color}33">
            <div style="font-size:1.2rem;font-weight:800;color:${s.color}">${s.val}</div>
            <div style="font-size:.65rem;color:#666">${s.label}</div>
          </div>
        `).join('→')}
      </div>
      <div style="font-size:.78rem;color:#666">
        Total en pipeline: <b>${total}</b> · 
        Equipos pendientes de retiro: <b style="color:#c62828">${d.equipos_pendientes_retiro}</b>
      </div>
    </div>`;
}

// ── INGRESO POR TORRE ──
function renderFinTorres(data){
  const el = document.getElementById('fin-torres');
  if(!el) return;
  const top = data.filter(t=>t.clientes > 0).slice(0, 15);
  if(!top.length){ el.innerHTML=''; return; }
  const maxIng = Math.max(...top.map(t=>t.ingreso), 1);
  el.innerHTML = `
    <div class="fin-section">
      <h3>🗼 Ingreso por torre (inalámbrico)</h3>
      <table class="fin-table">
        <thead><tr><th>Torre</th><th>Clientes</th><th>Ingreso</th><th>$/Cliente</th><th></th></tr></thead>
        <tbody>${top.map(t=>`
          <tr>
            <td><b>${escHtml(t.nombre)}</b><br><small style="color:#888">${escHtml(t.localidad)}</small></td>
            <td>${t.activos} <small style="color:#888">(${t.suspendidos} susp)</small></td>
            <td style="font-weight:700;color:#2e7d32">${fmtMoney(t.ingreso)}</td>
            <td>${fmtMoney(t.ingreso_por_cliente)}</td>
            <td style="width:100px">
              <div style="background:var(--card);border-radius:3px;height:12px;overflow:hidden">
                <div style="background:#2e7d32;height:100%;width:${Math.round(t.ingreso/maxIng*100)}%"></div>
              </div>
            </td>
          </tr>
        `).join('')}</tbody>
      </table>
      ${data.filter(t=>t.clientes===0).length ? `<div style="margin-top:.5rem;font-size:.75rem;color:#c62828">⚠ ${data.filter(t=>t.clientes===0).length} torres sin clientes asignados</div>` : ''}
    </div>`;
}

// ── INGRESO POR OLT ──
function renderFinOlts(data){
  const el = document.getElementById('fin-olts');
  if(!el) return;
  const top = data.filter(o=>o.clientes > 0);
  if(!top.length){ el.innerHTML=''; return; }
  const maxIng = Math.max(...top.map(o=>o.ingreso), 1);
  el.innerHTML = `
    <div class="fin-section">
      <h3>🔆 Ingreso por OLT (fibra)</h3>
      <table class="fin-table">
        <thead><tr><th>OLT</th><th>Clientes</th><th>Ingreso</th><th>$/Cliente</th><th></th></tr></thead>
        <tbody>${top.map(o=>`
          <tr>
            <td><b>${escHtml(o.olt)}</b></td>
            <td>${o.activos} <small style="color:#888">(${o.suspendidos} susp)</small></td>
            <td style="font-weight:700;color:#1565c0">${fmtMoney(o.ingreso)}</td>
            <td>${fmtMoney(o.ingreso_por_cliente)}</td>
            <td style="width:100px">
              <div style="background:var(--tint-azul);border-radius:3px;height:12px;overflow:hidden">
                <div style="background:#1565c0;height:100%;width:${Math.round(o.ingreso/maxIng*100)}%"></div>
              </div>
            </td>
          </tr>
        `).join('')}</tbody>
      </table>
    </div>`;
}

// ── INGRESO POR NAP ──
function renderFinNaps(data){
  const el = document.getElementById('fin-naps');
  if(!el) return;
  const top = data.filter(n=>n.ocupacion > 0).slice(0, 15);
  if(!top.length){ el.innerHTML=''; return; }
  el.innerHTML = `
    <div class="fin-section">
      <h3>📦 Ingreso por NAP (fibra)</h3>
      <table class="fin-table">
        <thead><tr><th>NAP</th><th>Ocupación</th><th>Ingreso</th><th>$/Puerto</th><th>Red</th></tr></thead>
        <tbody>${top.map(n=>{
          const occColor = n.pct_ocupacion > 90 ? '#c62828' : n.pct_ocupacion > 70 ? '#e65100' : '#2e7d32';
          return `<tr>
            <td><b>${escHtml(n.nombre)}</b></td>
            <td>
              <span style="color:${occColor};font-weight:600">${n.ocupacion}/${n.capacidad}</span>
              <small>(${n.libre} libre)</small>
            </td>
            <td style="font-weight:700;color:#2e7d32">${fmtMoney(n.ingreso)}</td>
            <td>${fmtMoney(n.ingreso_por_puerto)}</td>
            <td style="font-size:.75rem;color:#888">${escHtml(n.red)||'—'}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>
    </div>`;
}

// ════════════════════════════════════════════════════════
// ESTADÍSTICAS DE SERVICE: FTTH vs INALÁMBRICO
// ════════════════════════════════════════════════════════
async function loadStatsService(){
  const periodo = document.getElementById('stats-periodo')?.value || '12';
  const data = await api(`/api/estadisticas/reclamos_por_medio?periodo=${periodo}`);
  if(!data) return;

  // Tarjetas comparativas
  const cards = document.getElementById('stats-service-cards');
  if(cards){
    cards.innerHTML = data.comparativa.map(c=>{
      const color = c.medio.toLowerCase().includes('fibra') ? '#1565c0' : '#e65100';
      const icon = c.medio.toLowerCase().includes('fibra') ? '📡' : '📶';
      return `<div class="fin-card" style="border-left:4px solid ${color}">
        <div class="fin-val" style="font-size:1.6rem">${c.tasa_por_100_clientes}</div>
        <div class="fin-lbl">${icon} ${escHtml(c.medio)} · reclamos por 100 clientes</div>
        <div class="fin-sub">
          <span>${c.servicios_tecnicos} servicios</span> ·
          <span>${c.clientes_activos} clientes activos</span>
        </div>
      </div>`;
    }).join('');

    // Veredicto: cuál genera más proporcionalmente
    const comp = data.comparativa;
    if(comp.length===2 && comp[0].tasa_por_100_clientes && comp[1].tasa_por_100_clientes){
      const peor = comp[0].tasa_por_100_clientes > comp[1].tasa_por_100_clientes ? comp[0] : comp[1];
      const mejor = peor===comp[0] ? comp[1] : comp[0];
      const ratio = (peor.tasa_por_100_clientes / (mejor.tasa_por_100_clientes||1)).toFixed(1);
      cards.innerHTML += `<div class="fin-card" style="border-left:4px solid #b03030;grid-column:1/-1">
        <div class="fin-lbl"><b>${escHtml(peor.medio)}</b> genera <b>${ratio}×</b> más visitas técnicas por cliente que ${escHtml(mejor.medio)}.</div>
      </div>`;
    }
  }

  // Evolución mensual (barras agrupadas)
  const evol = document.getElementById('stats-service-evol');
  if(evol && data.evolucion?.length){
    const max = Math.max(...data.evolucion.map(d=>Math.max(d.fibra,d.inalambrico)),1);
    evol.innerHTML = `
      <h3 style="font-size:.95rem;margin-bottom:.5rem">Evolución mensual de servicios técnicos</h3>
      <div style="display:flex;align-items:flex-end;gap:6px;height:180px;padding:1rem 0;border-bottom:1px solid var(--brd)">
        ${data.evolucion.map(d=>{
          const hF = Math.round(d.fibra/max*140);
          const hI = Math.round(d.inalambrico/max*140);
          const ml = d.mes.split('-')[1]+'/'+d.mes.split('-')[0].slice(2);
          return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;justify-content:flex-end;height:100%">
            <div style="display:flex;gap:2px;align-items:flex-end">
              <div style="background:#1565c0;width:11px;height:${hF}px;border-radius:2px 2px 0 0" title="Fibra: ${d.fibra}"></div>
              <div style="background:#e65100;width:11px;height:${hI}px;border-radius:2px 2px 0 0" title="Inalámbrico: ${d.inalambrico}"></div>
            </div>
            <div style="font-size:.6rem;margin-top:3px;color:var(--txt2)">${ml}</div>
          </div>`;
        }).join('')}
      </div>
      <div style="display:flex;gap:1rem;font-size:.72rem;margin-top:.5rem;color:var(--txt2)">
        <span><span style="display:inline-block;width:10px;height:10px;background:#1565c0;border-radius:2px"></span> Fibra</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#e65100;border-radius:2px"></span> Inalámbrico</span>
      </div>`;
  }
}

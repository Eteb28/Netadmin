/* ════════════════════════════════════════════════════════
   antiguedad.js — Permanencia y churn de clientes (fase 5).
   Consume /api/v2/antiguedad.
   ════════════════════════════════════════════════════════ */

async function loadAntiguedad(){
  const cont = document.getElementById('ant-cont');
  if(!cont) return;
  const tipo = document.getElementById('ant-tipo')?.value || 'fibra';
  cont.innerHTML = '<div style="color:var(--txt2);padding:.6rem">Calculando…</div>';

  const d = await api(`/api/v2/antiguedad?tipo_servicio=${encodeURIComponent(tipo)}`);
  if(!d){ cont.innerHTML = '<div class="alert-box warn">No se pudieron calcular las estadísticas.</div>'; return; }

  const base = (d.total_activos || 0) + (d.total_bajas || 0);
  if(!base){
    cont.innerHTML = `<div class="alert-box info">No hay clientes con tipo de servicio "${escHtml(tipo)}" y fecha de alta cargada.</div>`;
    return;
  }

  cont.innerHTML =
    v2KpiGrid([
      v2Kpi(d.total_activos, 'Activos', '#4FB3AA'),
      v2Kpi(d.total_bajas, 'Bajas históricas', '#E08063'),
      v2Kpi(d.permanencia_media_meses != null ? d.permanencia_media_meses + ' m' : '—',
            'Permanencia media (activos)', '#5B9BD5',
            'Meses desde el alta hasta hoy, promediados sobre los clientes activos'),
      v2Kpi(d.permanencia_media_bajas_meses != null ? d.permanencia_media_bajas_meses + ' m' : '—',
            'Permanencia media (bajas)', '#9676F1',
            'Cuánto duró en promedio un cliente que se fue: del alta a la baja'),
      v2Kpi(d.churn_anual != null ? d.churn_anual + ' %' : '—', 'Churn acumulado', '#E0A838',
            'Bajas sobre el total histórico de clientes de este servicio')
    ]) +

    `<div class="grid-2" style="gap:.9rem;align-items:start;margin-top:.9rem">
      <div>${v2Seccion('📊 Activos por antigüedad', v2Barras(d.distribucion_activos, {color:'#4FB3AA', anchoEtiqueta:120}))}</div>
      <div>${v2Seccion('📉 Bajas por antigüedad',
              v2Barras(d.distribucion_bajas, {color:'#E08063', anchoEtiqueta:120,
                       vacio:'Sin bajas registradas'}))}</div>
     </div>` +

    v2Seccion('🔁 Churn mensual (%)', _antTendencia(d.churn_mensual, '#E0A838', ' %')) +
    v2Seccion('📈 Altas y bajas por mes', _antAltasBajas(d.altas_por_mes, d.bajas_por_mes)) +

    `<div style="font-size:.72rem;color:var(--txt2);margin-top:.6rem;padding-top:.5rem;border-top:1px dashed var(--brd)">
      El churn de cada mes se calcula sobre la base activa <b>al comenzar ese mes</b>, no sobre el total
      histórico: dividir por el total daría siempre un número chico y sin sentido comparativo.
     </div>`;
}

/* Serie temporal como columnas. Suficiente para leer la tendencia y no
   obliga a cargar una librería de gráficos. */
function _antTendencia(serie, color, sufijo){
  serie = serie || [];
  if(!serie.length) return '<div style="color:var(--txt2);font-size:.8rem">Sin bajas en el período: no hay churn que calcular.</div>';
  const max = Math.max(...serie.map(s => Number(s[1]) || 0), 0.1);
  return `<div style="display:flex;align-items:flex-end;gap:3px;height:110px;overflow-x:auto;padding-bottom:2px">${
    serie.map(([mes, val]) => {
      const h = Math.max(2, Math.round((Number(val) || 0) / max * 92));
      return `<div style="display:flex;flex-direction:column;align-items:center;min-width:34px"
                   title="${escHtml(mes)}: ${escHtml(val)}${escHtml(sufijo)}">
        <div style="font-size:.62rem;color:var(--txt2)">${escHtml(val)}</div>
        <div style="width:20px;height:${h}px;background:${color};border-radius:3px 3px 0 0"></div>
        <div style="font-size:.58rem;color:var(--txt2);margin-top:2px;white-space:nowrap">${escHtml(String(mes).slice(2))}</div>
      </div>`;
    }).join('')}</div>`;
}

/* Altas contra bajas, mes a mes: la comparativa que pide el enunciado. */
function _antAltasBajas(altas, bajas){
  const porMes = {};
  (altas || []).forEach(([m, v]) => { porMes[m] = porMes[m] || [0, 0]; porMes[m][0] = v; });
  (bajas || []).forEach(([m, v]) => { porMes[m] = porMes[m] || [0, 0]; porMes[m][1] = v; });
  const meses = Object.keys(porMes).sort().slice(-24);   // últimos dos años
  if(!meses.length) return '<div style="color:var(--txt2);font-size:.8rem">Sin datos</div>';
  const max = Math.max(...meses.map(m => Math.max(porMes[m][0], porMes[m][1])), 1);

  return `<div style="display:flex;align-items:flex-end;gap:4px;height:120px;overflow-x:auto;padding-bottom:2px">${
    meses.map(m => {
      const [a, b] = porMes[m];
      const h = v => Math.max(v ? 2 : 0, Math.round(v / max * 88));
      return `<div style="display:flex;flex-direction:column;align-items:center;min-width:38px"
                   title="${escHtml(m)} — altas: ${escHtml(a)}, bajas: ${escHtml(b)}">
        <div style="display:flex;align-items:flex-end;gap:2px;height:92px">
          <div style="width:11px;height:${h(a)}px;background:#4FB3AA;border-radius:2px 2px 0 0"></div>
          <div style="width:11px;height:${h(b)}px;background:#E08063;border-radius:2px 2px 0 0"></div>
        </div>
        <div style="font-size:.58rem;color:var(--txt2);margin-top:2px;white-space:nowrap">${escHtml(m.slice(2))}</div>
      </div>`;
    }).join('')}</div>
    <div style="font-size:.7rem;color:var(--txt2);margin-top:.3rem">
      <span style="color:#4FB3AA">■</span> Altas &nbsp; <span style="color:#E08063">■</span> Bajas</div>`;
}

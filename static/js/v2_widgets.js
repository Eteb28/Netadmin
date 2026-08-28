/* ════════════════════════════════════════════════════════
   v2_widgets.js — Piezas visuales compartidas por los módulos
   de la arquitectura nueva (/api/v2).

   Existe para no repetir el mismo bloque de barras y KPIs en
   cuatro archivos: es el mismo criterio de "no duplicar lógica"
   que el backend aplica con los servicios.

   Todo lo que entra acá se escapa con escHtml(): estas funciones
   pintan datos que vienen de la base y nunca deben poder inyectar
   HTML.
   ════════════════════════════════════════════════════════ */

const V2_PALETA = ['#5B9BD5','#4FB3AA','#E0A838','#E08063','#9676F1','#7FB069','#C56B8E','#566B84'];

/* Tarjeta de indicador. `color` opcional; si no viene, azul. */
function v2Kpi(valor, etiqueta, color, ayuda){
  const c = color || '#5B9BD5';
  const title = ayuda ? ` title="${escHtml(ayuda)}"` : '';
  return `<div${title} style="background:var(--surf2);border-radius:10px;padding:.8rem;text-align:center;border-top:3px solid ${c}">
    <div style="font-size:1.55rem;font-weight:700;color:${c};line-height:1.1">${escHtml(valor ?? '—')}</div>
    <div style="font-size:.7rem;color:var(--txt2);text-transform:uppercase;margin-top:.2rem">${escHtml(etiqueta)}</div>
  </div>`;
}

function v2KpiGrid(tarjetas){
  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.5rem">${tarjetas.join('')}</div>`;
}

/* Barras horizontales. `datos` = [[etiqueta, valor], ...] o [{etiqueta, valor}]. */
function v2Barras(datos, opciones){
  const o = opciones || {};
  const filas = (datos || []).map(d => Array.isArray(d) ? d : [d.etiqueta, d.valor]);
  if(!filas.length) return `<div style="color:var(--txt2);font-size:.8rem;padding:.4rem">${escHtml(o.vacio || 'Sin datos')}</div>`;
  const max = Math.max(...filas.map(f => Number(f[1]) || 0), 1);
  return filas.slice(0, o.limite || 12).map(([et, val], i) => {
    const color = o.color || V2_PALETA[i % V2_PALETA.length];
    const ancho = Math.round((Number(val) || 0) / max * 100);
    return `<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.3rem;font-size:.78rem">
      <span style="min-width:${o.anchoEtiqueta || 130}px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            title="${escHtml(et)}">${escHtml(et || '(sin dato)')}</span>
      <div style="flex:1;background:var(--card);border-radius:3px;height:13px;min-width:40px">
        <div style="background:${color};height:100%;border-radius:3px;width:${ancho}%"></div></div>
      <b style="min-width:44px;text-align:right">${escHtml(val)}${escHtml(o.sufijo || '')}</b>
    </div>`;
  }).join('');
}

function v2Seccion(titulo, contenido){
  return `<div style="margin-bottom:.9rem">
    <div style="font-weight:600;font-size:.86rem;margin-bottom:.45rem">${escHtml(titulo)}</div>
    ${contenido}</div>`;
}

/* Duraciones: la base devuelve minutos, la pantalla necesita algo legible. */
function v2Duracion(minutos){
  if(minutos === null || minutos === undefined) return '—';
  const m = Math.round(Number(minutos));
  if(m < 60) return m + ' min';
  if(m < 1440) return (m / 60).toFixed(1) + ' h';
  return (m / 1440).toFixed(1) + ' días';
}

/* Fechas ISO con zona (así las devuelve la API v2) → dd/mm/aa hh:mm local. */
function v2Fecha(iso, conHora){
  if(!iso) return '—';
  const d = new Date(iso);
  if(isNaN(d)) return String(iso).slice(0, 16);
  const f = d.toLocaleDateString('es-AR', {day:'2-digit', month:'2-digit', year:'2-digit'});
  return conHora === false ? f : f + ' ' + d.toLocaleTimeString('es-AR', {hour:'2-digit', minute:'2-digit'});
}

/* Envoltorio de tabla con scroll horizontal propio: en pantallas chicas
   la tabla se desplaza sola en vez de romper el ancho de la página. */
function v2Tabla(encabezados, filasHtml, vacio){
  if(!filasHtml) return `<div style="color:var(--txt2);font-size:.82rem;padding:.6rem">${escHtml(vacio || 'Sin registros')}</div>`;
  return `<div class="tbl-wrap" style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.8rem">
    <thead><tr style="background:var(--card)">${
      encabezados.map(h => {
        const der = typeof h === 'object' && h.derecha;
        const txt = typeof h === 'object' ? h.txt : h;
        return `<th style="text-align:${der?'right':'left'};padding:.4rem;white-space:nowrap">${escHtml(txt)}</th>`;
      }).join('')
    }</tr></thead><tbody>${filasHtml}</tbody></table></div>`;
}

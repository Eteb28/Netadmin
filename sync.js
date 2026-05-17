/* ─── SINCRONIZACIÓN ERP ─────────────────────────────────────────
   Panel de control de la sincronización ERP (PG) → NetAdmin (SQLite).
   ─────────────────────────────────────────────────────────────── */

let SYNC_STATUS_TIMER = null;
let SYNC_CORRIENDO = false;

async function cargarSyncStatus() {
  try {
    const r = await fetch('/api/sync/status');
    if (!r.ok) return;
    const data = await r.json();
    renderSyncStatus(data);
  } catch (e) {
    console.error('cargarSyncStatus', e);
  }
}

function fmtFecha(s) {
  if (!s) return '—';
  return s.replace('T', ' ').substring(0, 19);
}

function fmtDuracion(s) {
  if (s == null) return '—';
  if (s < 60) return s.toFixed(1) + 's';
  const m = Math.floor(s / 60);
  const sec = Math.round(s - m * 60);
  return `${m}m ${sec}s`;
}

function fmtEstadoBadge(estado) {
  const map = {
    ok: ['#16a34a', '✓ OK'],
    error: ['#dc2626', '✗ ERROR'],
    parcial: ['#d97706', '⚠ PARCIAL'],
    corriendo: ['#2563eb', '⟳ corriendo'],
  };
  const [color, label] = map[estado] || ['#6b7280', estado || '?'];
  return `<span style="background:${color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">${label}</span>`;
}

function fmtRelativo(fechaStr) {
  if (!fechaStr) return '—';
  const f = new Date(fechaStr.replace(' ', 'T'));
  const ahora = new Date();
  const seg = Math.floor((ahora - f) / 1000);
  if (seg < 60) return `hace ${seg}s`;
  if (seg < 3600) return `hace ${Math.floor(seg/60)} min`;
  if (seg < 86400) return `hace ${Math.floor(seg/3600)} h`;
  return `hace ${Math.floor(seg/86400)} días`;
}

function renderSyncStatus(data) {
  const cont = document.getElementById('sync-panel-content');
  if (!cont) return;
  
  const last = data.last;
  let resumenHtml = '';
  if (last && last.resumen) {
    try {
      const resumen = JSON.parse(last.resumen);
      const items = [];
      for (const [mod, m] of Object.entries(resumen)) {
        if (m.error) {
          items.push(`<div class="sync-mod-line err">✗ <b>${mod}</b>: ${m.error}</div>`);
        } else {
          const detalle = Object.entries(m)
            .filter(([k]) => !['modulo','duracion_seg','detalle_errores'].includes(k))
            .map(([k,v]) => `${k}=${v}`).join(', ');
          items.push(`<div class="sync-mod-line">✓ <b>${mod}</b> (${m.duracion_seg||0}s): ${detalle}</div>`);
        }
      }
      resumenHtml = items.join('');
    } catch (e) {
      resumenHtml = '<div class="muted">(no pude parsear resumen)</div>';
    }
  }
  
  cont.innerHTML = `
    <div class="sync-row">
      <div class="sync-card">
        <h3>Última sincronización</h3>
        ${last ? `
          <div class="sync-line">${fmtEstadoBadge(last.estado)} ${fmtRelativo(last.fecha_inicio)}</div>
          <div class="sync-line muted">Inicio: ${fmtFecha(last.fecha_inicio)}</div>
          <div class="sync-line muted">Duración: ${fmtDuracion(last.duracion_seg)}</div>
          <div class="sync-line muted">Iniciado por: ${last.iniciado_por || '?'}</div>
          ${last.errores ? `<div class="sync-errores"><b>Errores:</b><pre>${last.errores}</pre></div>` : ''}
        ` : '<div class="muted">Todavía no hubo ninguna sincronización.</div>'}
      </div>
      <div class="sync-card">
        <h3>Acciones</h3>
        <button id="btn-sync-now" class="btn btn-primary" ${SYNC_CORRIENDO ? 'disabled' : ''}>
          ${SYNC_CORRIENDO ? '⟳ Sincronizando…' : '🔄 Sincronizar ahora'}
        </button>
        <button id="btn-sync-dry" class="btn btn-secondary" style="margin-left:6px" ${SYNC_CORRIENDO ? 'disabled' : ''}>
          Dry-run (solo simular)
        </button>
        <button id="btn-test-pg" class="btn btn-secondary" style="margin-left:6px">
          Test conexión PG
        </button>
        <div id="sync-test-result" style="margin-top:8px"></div>
      </div>
    </div>

    ${resumenHtml ? `
      <div class="sync-card">
        <h3>Cambios último ciclo</h3>
        ${resumenHtml}
      </div>
    ` : ''}

    <div class="sync-card">
      <h3>Clientes pendientes de cargar al ERP</h3>
      <div class="muted" style="margin-bottom:8px">
        Estos clientes fueron creados en NetAdmin pero todavía no están en el ERP.
        Cargalos manualmente desde la interfaz del ERP y después marcalos acá.
      </div>
      <div id="sync-pte-erp-list">Cargando…</div>
    </div>

    <div class="sync-card">
      <h3>Historial (últimas 20)</h3>
      <table class="tabla-historial">
        <thead><tr>
          <th>Fecha</th><th>Estado</th><th>Duración</th><th>Por</th>
        </tr></thead>
        <tbody>
          ${data.history.map(h => `
            <tr>
              <td>${fmtFecha(h.fecha_inicio)}</td>
              <td>${fmtEstadoBadge(h.estado)}</td>
              <td>${fmtDuracion(h.duracion_seg)}</td>
              <td>${h.iniciado_por || '?'}</td>
            </tr>
          `).join('')}
          ${data.history.length === 0 ? '<tr><td colspan="4" class="muted">Sin historial</td></tr>' : ''}
        </tbody>
      </table>
    </div>
  `;
  
  // Listeners
  document.getElementById('btn-sync-now')?.addEventListener('click', () => dispararSync(false));
  document.getElementById('btn-sync-dry')?.addEventListener('click', () => dispararSync(true));
  document.getElementById('btn-test-pg')?.addEventListener('click', testPG);
  cargarPteErp();
}

async function dispararSync(dryRun) {
  if (SYNC_CORRIENDO) return;
  if (!dryRun && !confirm('¿Disparar sincronización completa con el ERP?\n\nEsto puede tardar de 30s a 3 minutos según volumen.')) return;
  SYNC_CORRIENDO = true;
  cargarSyncStatus();  // re-render con botón disabled
  try {
    const r = await fetch('/api/sync/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dry_run: dryRun })
    });
    const data = await r.json();
    if (data.error) {
      alert('Error: ' + data.error);
    } else if (data.estado === 'error') {
      alert('Sync terminó con error:\n' + (data.errores || []).join('\n'));
    } else {
      const total = Object.values(data.modulos || {}).reduce((acc,m) =>
        acc + (m.actualizados || 0) + (m.nuevos || 0) + (m.insertados || 0) + (m.agregados || 0), 0);
      alert(`Sync ${data.estado.toUpperCase()}: ${total} cambios en ${data.duracion_seg}s${dryRun ? ' (dry-run)' : ''}`);
    }
  } catch (e) {
    alert('Error de red: ' + e.message);
  } finally {
    SYNC_CORRIENDO = false;
    cargarSyncStatus();
  }
}

async function testPG() {
  const el = document.getElementById('sync-test-result');
  el.innerHTML = '<span class="muted">Probando conexión…</span>';
  try {
    const r = await fetch('/api/sync/test_pg');
    const data = await r.json();
    if (data.ok) {
      el.innerHTML = '<span style="color:#16a34a">✓ Conexión PG OK</span>';
    } else {
      el.innerHTML = `<span style="color:#dc2626">✗ Error: ${data.error || 'desconocido'}</span>`;
    }
  } catch (e) {
    el.innerHTML = `<span style="color:#dc2626">✗ ${e.message}</span>`;
  }
}

async function cargarPteErp() {
  const el = document.getElementById('sync-pte-erp-list');
  if (!el) return;
  try {
    const r = await fetch('/api/sync/clientes_pte_erp');
    const rows = await r.json();
    if (!rows.length) {
      el.innerHTML = '<div class="muted">No hay clientes pendientes.</div>';
      return;
    }
    el.innerHTML = `
      <table class="tabla-historial">
        <thead><tr>
          <th>#</th><th>Nombre</th><th>DNI</th><th>Fecha alta</th><th>Estado</th><th></th>
        </tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td>${r.id}</td>
              <td>${r.nombre || '—'}</td>
              <td>${r.dni || '—'}</td>
              <td>${r.fecha_alta || '—'}</td>
              <td>${r.estado || '—'}</td>
              <td><button class="btn btn-small" onclick="marcarCargadoErp(${r.id})">✓ Cargado al ERP</button></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div class="muted" style="margin-top:6px">${rows.length} cliente(s) pendiente(s)</div>
    `;
  } catch (e) {
    el.innerHTML = `<div style="color:#dc2626">Error: ${e.message}</div>`;
  }
}

async function marcarCargadoErp(clienteId) {
  if (!confirm('Marcar este cliente como ya cargado al ERP?')) return;
  try {
    const r = await fetch(`/api/sync/clientes_pte_erp/${clienteId}/marcar_cargado`, {method: 'POST'});
    const data = await r.json();
    if (data.ok) {
      cargarPteErp();
    } else {
      alert('Error: ' + (data.error || 'desconocido'));
    }
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

function activarSyncPanel() {
  // Iniciar refresh automático cada 30s
  cargarSyncStatus();
  if (SYNC_STATUS_TIMER) clearInterval(SYNC_STATUS_TIMER);
  SYNC_STATUS_TIMER = setInterval(cargarSyncStatus, 30000);
}

function desactivarSyncPanel() {
  if (SYNC_STATUS_TIMER) {
    clearInterval(SYNC_STATUS_TIMER);
    SYNC_STATUS_TIMER = null;
  }
}

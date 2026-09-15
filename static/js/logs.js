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
   logs.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadHistorial(){
  const d=await api('/api/historial');
  if(!d) return;
  const tbody=document.getElementById('hist-tbody');
  tbody.innerHTML=d.map(h=>`<tr>
    <td style="white-space:nowrap;font-size:.75rem">${escHtml(h.fecha?.slice(0,16))||'—'}</td>
    <td>${escHtml(h.usuario)||'—'}</td>
    <td><span class="badge b-activo">${escHtml(h.tipo)}</span></td>
    <td>${escHtml(h.titulo)}</td>
    <td style="font-size:.75rem;color:var(--txt2)">${escHtml(h.detalle)}</td>
  </tr>`).join('');
}

// ── USUARIOS ──

async function cargarHistorialSenal(nap){
  const d=await api(`/api/historial_senal?nap=${encodeURIComponent(nap)}&limit=20`);
  const div=document.getElementById('msenal-history');
  if(!d||!d.length){div.innerHTML='<div class="empty">Sin mediciones registradas</div>';return;}
  div.innerHTML=`<div class="tbl-wrap"><table>
    <thead><tr><th>Fecha</th><th>Nivel</th><th>Observaciones</th><th>Usuario</th></tr></thead>
    <tbody>${d.map(h=>`<tr>
      <td style="font-size:.77rem">${escHtml(h.fecha?.slice(0,16))||'—'}</td>
      <td style="font-family:monospace;font-weight:700;color:${(h.nivel_dbm||0)>-20?'var(--vd)':(h.nivel_dbm||0)>-25?'var(--am)':'var(--rj)'}">${h.nivel_dbm} dBm</td>
      <td style="font-size:.77rem">${escHtml(h.observaciones)||'—'}</td>
      <td style="font-size:.75rem">${escHtml(h.usuario)||'—'}</td>
    </tr>`).join('')}</tbody>
  </table></div>`;
}

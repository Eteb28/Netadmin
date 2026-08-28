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

/* tema.js — toggle claro/oscuro por navegador (temporal).
   No toca tema-oscuro.css: solo agrega/quita el <link>. */

function toggleTema(){
  const link = document.getElementById('tema-oscuro-link');
  if(link){
    link.remove();
    try{ localStorage.setItem('erlan_tema','claro'); }catch(e){}
  } else {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.id = 'tema-oscuro-link';
    l.href = window.TEMA_OSCURO_HREF;
    document.head.appendChild(l);
    try{ localStorage.setItem('erlan_tema','oscuro'); }catch(e){}
  }
  _actualizarBotonTema();
}

function _actualizarBotonTema(){
  const btn = document.getElementById('btn-tema');
  if(!btn) return;
  const oscuro = !!document.getElementById('tema-oscuro-link');
  btn.textContent = oscuro ? '☀️' : '🌙';
  btn.title = oscuro ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro';
}

document.addEventListener('DOMContentLoaded', _actualizarBotonTema);

/* ═══════════════════════════════════════════════════════════════
   pucara-noc.js — Barra lateral colapsable
   ───────────────────────────────────────────────────────────────
   Instalar:  <script src="/static/js/pucara-noc.js"></script>  (al final)
   Revertir:  comentar esa línea. NO modifica el HTML del menú:
              reemplaza los emojis por iconos SVG en tiempo de ejecución,
              así los onclick y la lógica de navegación quedan intactos.
   ═══════════════════════════════════════════════════════════════ */
(function(){
'use strict';

/* ── Iconos (trazo de 1.6, caja 24×24) ── */
var P = {
  panel:   '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  pin:     '<path d="M12 17v5"/><path d="M9 10.8V4h6v6.8l2 3.2H7l2-3.2z"/>',
  users:   '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/>',
  user:    '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  mapa:    '<path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4z"/><path d="M8 2v16M16 6v16"/>',
  fibra:   '<circle cx="12" cy="12" r="2.5"/><path d="M12 2v7M12 15v7M2 12h7M15 12h7"/><circle cx="12" cy="2.5" r="1.3"/><circle cx="12" cy="21.5" r="1.3"/><circle cx="2.5" cy="12" r="1.3"/><circle cx="21.5" cy="12" r="1.3"/>',
  nap:     '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 6V3M17 6V3M7 18v3M17 18v3"/><circle cx="12" cy="12" r="1.6"/>',
  globo:   '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 010 18 14 14 0 010-18z"/>',
  antena:  '<path d="M5 12.5a9 9 0 0114 0M8 16a5 5 0 018 0"/><circle cx="12" cy="19.5" r="1.5"/><path d="M2 9a13 13 0 0120 0"/>',
  alerta:  '<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  senal:   '<circle cx="12" cy="12" r="8.5"/><path d="M12 8v4.5M12 16h.01"/>',
  torre:   '<path d="M12 3v18"/><path d="M7 21l5-13 5 13"/><path d="M4.5 7a10 10 0 0115 0"/><path d="M7 10.5a6.5 6.5 0 0110 0"/>',
  olt:     '<rect x="2" y="4" width="20" height="7" rx="1.5"/><rect x="2" y="13" width="20" height="7" rx="1.5"/><path d="M6 7.5h.01M6 16.5h.01"/><path d="M10 7.5h6M10 16.5h6"/>',
  llave:   '<path d="M14.7 6.3a4 4 0 01-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 015.4-5.4l-2.6 2.6-2-2 2.6-2.6z"/>',
  engrane: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-1.8-.3 1.6 1.6 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.6 1.6 0 008 19.4a1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 00-1.5-1H2a2 2 0 110-4h.1A1.6 1.6 0 004.6 8a1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H9a1.6 1.6 0 001-1.5V2a2 2 0 114 0v.1a1.6 1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V9a1.6 1.6 0 001.5 1H22a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"/>',
  agenda:  '<rect x="3" y="4.5" width="18" height="17" rx="2"/><path d="M16 2.5v4M8 2.5v4M3 10h18"/>',
  historia:'<path d="M3 12a9 9 0 109-9 9 9 0 00-6.4 2.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  lista:   '<path d="M9 3h6a1 1 0 011 1v1H8V4a1 1 0 011-1z"/><path d="M16 5h2a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V7a2 2 0 012-2h2"/><path d="M8 11h8M8 15h5"/>',
  libro:   '<path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>',
  grafico: '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
  plata:   '<path d="M12 1v22"/><path d="M17 5.5C17 3.6 14.8 2 12 2S7 3.6 7 5.5 9.2 9 12 9s5 1.6 5 3.5-2.2 3.5-5 3.5-5-1.6-5-3.5"/>',
  recibo:  '<path d="M4 2v20l2.5-1.6L9 22l2.5-1.6L14 22l2.5-1.6L19 22V2l-2.5 1.6L14 2l-2.5 1.6L9 2 6.5 3.6z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  regla:   '<path d="M3 21L21 3"/><path d="M6 15l2 2M9 12l2 2M12 9l2 2M15 6l2 2"/><rect x="1.5" y="14.5" width="21" height="7" rx="1.5" transform="rotate(-45 12 12)"/>',
  escudo:  '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  sync:    '<path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0115-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 01-15 6.7L3 16"/>',
  maletin: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2"/><path d="M2 13h20"/>',
  salir:   '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
  campana: '<path d="M18 8A6 6 0 106 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>',
  luna:    '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>',
  celular: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
  punto:   '<circle cx="12" cy="12" r="3.2"/>'
};

/* emoji → icono */
var MAPA = {
  '📊':'grafico','📈':'grafico','📉':'grafico',
  '📌':'pin','📍':'pin',
  '👥':'users','👤':'user','🚹':'user','🧑':'user',
  '🗺':'mapa','🗺️':'mapa',
  '💡':'fibra',
  '🔌':'nap',
  '🌐':'globo',
  '📡':'antena',
  '🚨':'alerta','⚠':'alerta','⚠️':'alerta',
  '🔴':'senal','🟢':'senal','🟡':'senal',
  '🗼':'torre',
  '🖥':'olt','🖥️':'olt','🗄':'olt','🗄️':'olt',
  '🔧':'llave','🛠':'llave','🛠️':'llave',
  '⚙':'engrane','⚙️':'engrane',
  '📅':'agenda','🗓':'agenda','🗓️':'agenda',
  '📜':'historia','🕐':'historia','🕒':'historia',
  '📋':'lista','📝':'lista',
  '📕':'libro','📗':'libro','📘':'libro','📚':'libro',
  '💰':'plata','💵':'plata','💲':'plata',
  '🧾':'recibo',
  '📐':'regla','📏':'regla',
  '🛡':'escudo','🛡️':'escudo',
  '🔄':'sync','♻':'sync','♻️':'sync',
  '🌙':'luna','☀':'luna','☀️':'luna','📱':'celular','🔔':'campana',
  '💼':'maletin','🏢':'maletin','📁':'maletin','🗂':'maletin','🗂️':'maletin'
};

function svg(nombre){
  var d = P[nombre] || P.punto;
  return '<svg class="ic" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
}

/* Detecta el emoji inicial de un texto.
   Consume la secuencia completa: emoji + selectores + ZWJ + tonos de piel. */
var RE_EMOJI = /^(?:\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic}|[\u{1F3FB}-\u{1F3FF}])*)/u;

function primerEmoji(txt){
  var t = txt.trim();
  var i, L, f;
  // 1) Detectar la SECUENCIA completa (👨‍💼 = persona + ZWJ + maletín cuenta como una)
  var m = t.match(RE_EMOJI);
  if (m) {
    var sec = m[0];
    // la secuencia entera en el mapa
    if (MAPA[sec]) return {emoji: sec, icono: MAPA[sec]};
    // si no, alguna de sus partes (se prefiere la última: define mejor el significado)
    for (i = sec.length - 1; i >= 0; i--) {
      for (L = 1; L <= 3 && i + L <= sec.length; L++) {
        f = sec.substr(i, L);
        if (MAPA[f]) return {emoji: sec, icono: MAPA[f]};
      }
    }
    return {emoji: sec, icono: 'punto'};
  }
  // 2) Emoji que no matchea la regex pero sí está en el mapa
  for (L = 3; L >= 1; L--) {
    f = t.slice(0, L);
    if (MAPA[f]) return {emoji: f, icono: MAPA[f]};
  }
  return null;
}

/* Convierte un <a> del menú: emoji → SVG, resto del texto → <span class="nav-lbl"> */
function convertir(a){
  if (a.dataset.iconizado) return;
  // no tocar si ya tiene elementos hijos que no sean el caret
  var texto = '';
  var nodos = [];
  a.childNodes.forEach(function(n){
    if (n.nodeType === 3) { texto += n.nodeValue; nodos.push(n); }
  });
  if (!texto.trim()) { a.dataset.iconizado = '1'; return; }

  var det = primerEmoji(texto);
  var etiqueta = det ? texto.trim().slice(det.emoji.length).trim() : texto.trim();
  var nombreIcono = det ? det.icono : 'punto';

  // sacar los nodos de texto originales
  nodos.forEach(function(n){ n.parentNode.removeChild(n); });

  var lbl = document.createElement('span');
  lbl.className = 'nav-lbl';
  lbl.textContent = etiqueta;

  var caret = a.querySelector('.nav-caret');
  a.insertAdjacentHTML('afterbegin', svg(nombreIcono));
  if (caret) a.insertBefore(lbl, caret); else a.appendChild(lbl);

  a.title = etiqueta;            // tooltip nativo cuando está colapsada
  a.dataset.iconizado = '1';
}

function iconizarMenu(){
  var nav = document.querySelector('.nav');
  if (!nav) return;
  nav.querySelectorAll('.nav-links a').forEach(convertir);
  // pie: tema oscuro, vista móvil, salir, notificaciones
  nav.querySelectorAll('.nav-right .nav-logout').forEach(function(b){
    if (b.dataset.iconizado) return;
    var txt = (b.textContent || '').trim();
    if (!primerEmoji(txt)) {            // "Salir" no tiene emoji
      b.textContent = '';
      b.insertAdjacentHTML('afterbegin', svg('salir'));
      var s = document.createElement('span');
      s.className = 'nav-lbl'; s.textContent = txt;
      b.appendChild(s); b.title = txt; b.dataset.iconizado = '1';
      return;
    }
    convertir(b);
  });
  var notif = nav.querySelector('.nav-right .notif-btn');
  if (notif && !notif.dataset.iconizado) {
    var badge = notif.querySelector('.notif-badge');
    notif.textContent = '';
    notif.insertAdjacentHTML('afterbegin', svg('campana'));
    if (badge) notif.appendChild(badge);
    notif.dataset.iconizado = '1';
  }
}

/* ── Comportamiento: abrir con el mouse (con retardo) y fijar ── */
function activarBarra(){
  var nav = document.querySelector('.nav');
  if (!nav || nav.dataset.nocListo) return;
  nav.dataset.nocListo = '1';

  var fija = localStorage.getItem('pucara_nav_fija') === '1';
  var t = null;

  function aplicarFija(){
    document.body.classList.toggle('nav-fija', fija);
    nav.classList.toggle('abierta', fija);
    var b = nav.querySelector('.nav-fijar');
    if (b) {
      b.title = fija ? 'Soltar la barra' : 'Fijar la barra abierta';
      var l = b.querySelector('.nav-lbl');
      if (l) l.textContent = fija ? 'Soltar barra' : 'Fijar barra';
    }
  }

  nav.addEventListener('mouseenter', function(){
    if (fija) return;
    t = setTimeout(function(){ nav.classList.add('abierta'); }, 200);
  });
  nav.addEventListener('mouseleave', function(){
    if (fija) return;
    clearTimeout(t);
    nav.classList.remove('abierta');
    if (typeof closeNavGroups === 'function') closeNavGroups();
  });

  // botón de fijar, al pie de la barra
  var btn = document.createElement('button');
  btn.className = 'nav-fijar';
  btn.type = 'button';
  btn.innerHTML = '<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">' + P.pin + '</svg><span class="nav-lbl">Fijar barra</span>';
  btn.addEventListener('click', function(){
    fija = !fija;
    localStorage.setItem('pucara_nav_fija', fija ? '1' : '0');
    aplicarFija();
  });
  var links = nav.querySelector('.nav-links');
  if (links && links.parentNode) links.parentNode.insertBefore(btn, links.nextSibling);
  else nav.appendChild(btn);

  aplicarFija();
}

/* Marca el body cuando el tema oscuro está activo, para que los tokens
   de monitoreo usen superficies más profundas. Sigue el toggle en vivo. */
function seguirTema(){
  var link = document.getElementById('tema-oscuro-css');
  function aplicar(){
    document.body.classList.toggle('noc-oscuro', !!(link && !link.disabled));
  }
  aplicar();
  if (link) new MutationObserver(aplicar).observe(link, {attributes:true, attributeFilter:['disabled']});
}

function init(){ iconizarMenu(); activarBarra(); seguirTema(); }

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else init();

// Si algo re-renderiza el menú (permisos, módulos), reconvertir
var obs = new MutationObserver(function(){ iconizarMenu(); });
document.addEventListener('DOMContentLoaded', function(){
  var l = document.querySelector('.nav-links');
  if (l) obs.observe(l, {childList:true, subtree:true});
});

window.PucaraNOC = {iconizarMenu: iconizarMenu};
})();

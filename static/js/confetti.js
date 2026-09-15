/* ═══════════════════════════════════════════════════════════════
   confetti.js — Lluvia de papel picado celeste y blanco 🇦🇷
   Se ejecuta una vez al cargar la página, cae con balanceo suave
   y se limpia solo al terminar. Liviano (canvas + requestAnimationFrame).

   Para desactivarlo cuando termine el festejo: sacá el <script> del HTML.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  // No repetir si ya corrió en esta carga
  if (window.__confettiRan) return;
  window.__confettiRan = true;

  // Paleta: celestes argentinos + blanco
  const COLORES = ['#75AADB', '#FFFFFF', '#4A90D9', '#AECBEB', '#FFFFFF', '#6FB7E0'];
  const DURACION = 9000;   // milisegundos que dura el efecto
  const CANTIDAD = 170;    // cantidad de papelitos

  // Canvas a pantalla completa, por encima de todo, sin bloquear clics
  const canvas = document.createElement('canvas');
  canvas.style.cssText =
    'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:99999';
  document.body.appendChild(canvas);
  const ctx = canvas.getContext('2d');

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // Crear los papelitos
  const papeles = [];
  for (let i = 0; i < CANTIDAD; i++) {
    const esCinta = Math.random() < 0.25; // 25% son cintas largas, el resto cuadraditos
    papeles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * -canvas.height,          // arrancan arriba, fuera de pantalla (cascada)
      w: esCinta ? 4 + Math.random() * 3 : 7 + Math.random() * 7,
      h: esCinta ? 16 + Math.random() * 14 : 7 + Math.random() * 7,
      color: COLORES[(Math.random() * COLORES.length) | 0],
      vy: 1.3 + Math.random() * 2.8,              // velocidad de caída
      vx: -0.6 + Math.random() * 1.2,             // deriva horizontal
      rot: Math.random() * Math.PI * 2,
      vrot: -0.12 + Math.random() * 0.24,         // giro
      sway: Math.random() * Math.PI * 2,          // fase del balanceo
      swaySpeed: 0.015 + Math.random() * 0.03,
      swayAmp: 0.8 + Math.random() * 1.6
    });
  }

  const inicio = Date.now();

  function frame() {
    const t = Date.now() - inicio;
    const progreso = t / DURACION;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Desvanecer suavemente en el último 20% del tiempo
    ctx.globalAlpha = progreso > 0.8 ? Math.max(0, 1 - (progreso - 0.8) / 0.2) : 1;

    for (const p of papeles) {
      // Movimiento: caída + balanceo lateral (mecidita de papel picado)
      p.sway += p.swaySpeed;
      p.x += p.vx + Math.sin(p.sway) * p.swayAmp;
      p.y += p.vy;
      p.rot += p.vrot;

      // Reciclar arriba mientras el efecto sigue activo (rain continuo)
      if (p.y > canvas.height + 24 && progreso < 0.72) {
        p.y = -24;
        p.x = Math.random() * canvas.width;
      }

      // Dibujar el papelito (rectángulo rotado, con leve efecto de "vuelta")
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      // El escalado en X simula que el papel gira mostrando canto/cara
      ctx.scale(Math.cos(p.sway) * 0.6 + 0.4, 1);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    }

    if (t < DURACION) {
      requestAnimationFrame(frame);
    } else {
      // Limpiar todo al terminar
      window.removeEventListener('resize', resize);
      canvas.remove();
    }
  }

  requestAnimationFrame(frame);
})();

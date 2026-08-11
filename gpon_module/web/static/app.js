/* Utilidades compartidas de la interfaz.
 *
 * Todo el acceso a datos pasa por `api()`. Ninguna página consulta otra cosa:
 * la interfaz habla con la API del módulo y con nada más.
 */

'use strict';

/** Llama a la API y traduce los errores a algo que el operador entienda. */
async function api(ruta, opciones = {}) {
  const respuesta = await fetch(`/api${ruta}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opciones,
  });
  const texto = await respuesta.text();
  let datos = null;
  try { datos = texto ? JSON.parse(texto) : null; } catch { datos = null; }

  if (!respuesta.ok) {
    const detalle = (datos && (datos.detalle || datos.error)) || `HTTP ${respuesta.status}`;
    const error = new Error(detalle);
    error.codigo = respuesta.status;
    error.tipo = datos && datos.error;
    throw error;
  }
  return datos;
}

/** Aviso flotante. `tono` es una clase de Bootstrap: success, danger, warning. */
function avisar(mensaje, tono = 'secondary') {
  const contenedor = document.getElementById('avisos');
  if (!contenedor) return;
  const elemento = document.createElement('div');
  elemento.className = `toast align-items-center text-bg-${tono} border-0 show`;
  elemento.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${escapar(mensaje)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  contenedor.appendChild(elemento);
  setTimeout(() => elemento.remove(), 8000);
}

function escapar(valor) {
  const div = document.createElement('div');
  div.textContent = valor === null || valor === undefined ? '' : String(valor);
  return div.innerHTML;
}

/** Un dato ausente se muestra como "—", nunca como 0. */
function valor(dato, sufijo = '') {
  if (dato === null || dato === undefined || dato === '') {
    return '<span class="sin-dato">—</span>';
  }
  return `${escapar(dato)}${sufijo}`;
}

function fecha(iso) {
  if (!iso) return '<span class="sin-dato">—</span>';
  const d = new Date(iso);
  return escapar(d.toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'medium' }));
}

function duracion(segundos) {
  if (segundos === null || segundos === undefined) return '<span class="sin-dato">—</span>';
  const dias = Math.floor(segundos / 86400);
  const horas = Math.floor((segundos % 86400) / 3600);
  const minutos = Math.floor((segundos % 3600) / 60);
  if (dias > 0) return `${dias} d ${horas} h`;
  if (horas > 0) return `${horas} h ${minutos} min`;
  return `${minutos} min`;
}

const ETIQUETAS_ESTADO = {
  en_linea: ['En línea', 'success'],
  fuera_de_linea: ['Fuera de línea', 'danger'],
  no_autorizada: ['Sin autorizar', 'warning'],
  deshabilitada: ['Deshabilitada', 'secondary'],
  desconocido: ['Desconocido', 'secondary'],
  degradada: ['Degradada', 'warning'],
};

function insigniaEstado(estado) {
  const [texto, tono] = ETIQUETAS_ESTADO[estado] || [estado, 'secondary'];
  return `<span class="badge text-bg-${tono}">${escapar(texto)}</span>`;
}

/* El motivo de caída es la información más accionable del inventario: separa
 * "se cortó la luz en la casa" de "hay que mandar una cuadrilla". */
const ETIQUETAS_MOTIVO = {
  apagado: ['Corte de luz', 'secondary', 'Dying gasp: el cliente se quedó sin energía'],
  perdida_senal: ['Pérdida de señal', 'danger', 'Problema de fibra: requiere cuadrilla'],
  desactivada_admin: ['Desactivada', 'secondary', 'Dada de baja administrativamente'],
  ninguno: ['', '', ''],
  desconocido: ['Desconocido', 'secondary', ''],
};

function insigniaMotivo(motivo) {
  const entrada = ETIQUETAS_MOTIVO[motivo];
  if (!entrada || !entrada[0]) return '';
  const [texto, tono, ayuda] = entrada;
  return `<span class="badge text-bg-${tono}" title="${escapar(ayuda)}">${escapar(texto)}</span>`;
}

function claseOptica(clasificacion) {
  return `optica-${clasificacion || 'sin_lectura'}`;
}

function potencia(dbm, clasificacion) {
  if (dbm === null || dbm === undefined) return '<span class="sin-dato">—</span>';
  return `<span class="${claseOptica(clasificacion)}">${dbm.toFixed(2)} dBm</span>`;
}

/** Estado del módulo en la barra superior. */
async function mostrarEstadoModulo() {
  const destino = document.getElementById('estado-modulo');
  if (!destino) return;
  try {
    const salud = await api('/salud');
    const modo = salud.dry_run_por_defecto
      ? '<span class="badge text-bg-info">modo simulación</span>'
      : '<span class="badge text-bg-danger">ESCRITURA REAL</span>';
    destino.innerHTML = `${salud.olts} OLT · ${modo}`;
  } catch (error) {
    destino.innerHTML = `<span class="badge text-bg-danger">sin conexión</span>`;
  }
}

document.addEventListener('DOMContentLoaded', mostrarEstadoModulo);

/** Ordena una tabla al hacer clic en el encabezado. */
function habilitarOrden(tabla, filas, redibujar) {
  let campoActual = null;
  let ascendente = true;
  tabla.querySelectorAll('th[data-orden]').forEach((th) => {
    th.addEventListener('click', () => {
      const campo = th.dataset.orden;
      ascendente = campo === campoActual ? !ascendente : true;
      campoActual = campo;
      filas.sort((a, b) => {
        const x = a[campo], y = b[campo];
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        if (x === y) return 0;
        return (x > y ? 1 : -1) * (ascendente ? 1 : -1);
      });
      redibujar();
    });
  });
}

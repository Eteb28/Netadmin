"""Driver VSOL V1600G1 / V1600G1-B — **sólo lectura** (Fase 2).

Lee por SNMP todo lo que estos equipos exponen de verdad, que es menos de lo
que promete el folleto. Las ausencias están verificadas contra los walks reales
de las OLT de ERLAN, no supuestas:

* **el número de serie de la ONU no existe por SNMP** — la rama que consulta el
  poller actual de Pucará devuelve cero resultados;
* **no hay contadores de tráfico por ONU** — los ifHCInOctets dan 0;
* **no hay CPU, memoria ni temperatura de chasis** en la rama del fabricante.

Cada una de esas ausencias se declara como capacidad faltante. La interfaz
oculta lo que este equipo no puede dar, en vez de mostrar ceros que parecen
mediciones.

Lo que falta y llega después:

* **Escritura** (autorizar, borrar, reiniciar): Fase 5. Es CLI obligatoriamente
  —SNMP en VSOL es de sólo lectura— y necesita el comando de autorización
  confirmado contra un equipo.
* **ONU sin autorizar y perfiles**: exigen CLI por la misma razón (el serial no
  viaja por SNMP). Se declaran no soportadas hasta que exista el transporte CLI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ...core.enums import Capacidad, EstadoONU, Fabricante
from ...core.errors import CapacidadNoSoportada, ErrorLecturaParcial, ErrorValidacion
from ...core.models import (
    OLT,
    ONU,
    CredencialesOLT,
    InfoSistema,
    LecturaOptica,
    PuertoPON,
    RefONU,
)
from ...core.registry import registrar_driver
from ..base import DriverBase
from ..transport.snmp import crear_transporte_snmp, indice_doble, indice_simple
from . import oids, parsers

log = logging.getLogger(__name__)

#: Lo que estos equipos **hacen**, comprobado. Declarar de más sería peor que
#: declarar de menos: la interfaz mostraría un botón que falla en producción.
CAPACIDADES_VSOL: frozenset[Capacidad] = frozenset(
    {
        Capacidad.DESCUBRIR_PUERTOS,
        Capacidad.DESCUBRIR_ONUS,
        Capacidad.POTENCIA_OPTICA,
        Capacidad.POTENCIA_MASIVA,
        Capacidad.TEMPERATURA_PON,
        Capacidad.TEMPERATURA_ONU,
        Capacidad.VOLTAJE,
        Capacidad.UPTIME,
        Capacidad.MOTIVO_CAIDA,
    }
)


@dataclass(frozen=True, slots=True)
class MuestraSondeo:
    """Una lectura cruda junto a su interpretación, para poder auditarla."""

    descripcion: str
    oid: str
    crudo: str | None
    interpretado: object = None
    nota: str = ""


@registrar_driver(
    Fabricante.VSOL,
    nombre="VSOL V1600G1 / V1600G1-B (lectura)",
    modelos=("V1600G1", "V1600G1-B", "V1600G1B"),
    protocolos=("snmp",),
    version="2.0-lectura",
)
class DriverVSOL(DriverBase):
    """Lectura SNMP de una OLT VSOL."""

    FABRICANTE = Fabricante.VSOL
    CAPACIDADES = CAPACIDADES_VSOL
    MODELOS = ("V1600G1", "V1600G1-B", "V1600G1B")

    def __init__(
        self,
        *,
        olt: OLT,
        credenciales: CredencialesOLT,
        dry_run: bool = True,
        reloj: object | None = None,
        transporte_snmp: object | None = None,
        preferencia_snmp: str | None = None,
        timeout: float = 5.0,
        reintentos: int = 2,
        **_extras: object,
    ) -> None:
        super().__init__(olt=olt, credenciales=credenciales, dry_run=dry_run, reloj=reloj)
        # El transporte se puede inyectar: así los tests corren sin red.
        self._snmp = transporte_snmp or crear_transporte_snmp(
            host=olt.host,
            comunidad=credenciales.comunidad_snmp_lectura or "public",
            puerto=credenciales.puerto_snmp,
            timeout=timeout,
            reintentos=reintentos,
            preferencia=preferencia_snmp,
        )
        #: Escala con la que este equipo publica dBm. Se deduce de la primera
        #: lectura masiva y se reusa: un lote de 473 ONU la determina sin
        #: ambigüedad, un valor suelto no.
        self._escala_dbm: int | None = None

    # --- ciclo de vida ----------------------------------------------------

    def conectar(self) -> None:
        # SNMP no tiene sesión: la primera consulta es la que verifica que el
        # equipo responde. Se hace acá para fallar temprano y con motivo.
        self._snmp.get(oids.MODELO)
        super().conectar()

    def desconectar(self) -> None:
        self._snmp.cerrar()
        super().desconectar()

    # --- identidad --------------------------------------------------------

    def get_system_info(self) -> InfoSistema:
        modelo = self._snmp.get(oids.MODELO) or ""
        return InfoSistema(
            modelo=modelo,
            fabricante=Fabricante.VSOL,
            firmware=self._snmp.get(oids.FIRMWARE) or "",
            numero_serie=self._snmp.get(oids.NUMERO_SERIE) or "",
            mac=self._snmp.get(oids.MAC) or "",
            nombre_equipo=self._snmp.get(oids.NOMBRE_EQUIPO)
            or self._snmp.get(oids.NOMBRE_SISTEMA)
            or "",
            uptime_segundos=parsers.parsear_uptime(self._snmp.get(oids.UPTIME)),
            # Verificado: estos equipos no exponen ninguno de los tres. Devolver
            # 0 sería inventar una medición.
            cpu_porcentaje=None,
            memoria_porcentaje=None,
            temperatura_celsius=None,
            leido_en=self._reloj.ahora(),
        )

    def get_uptime(self) -> int | None:
        self._exigir(Capacidad.UPTIME)
        return parsers.parsear_uptime(self._snmp.get(oids.UPTIME))

    # --- puertos PON ------------------------------------------------------

    def discover_ports(self) -> list[PuertoPON]:
        self._exigir(Capacidad.DESCUBRIR_PUERTOS)
        momento = self._reloj.ahora()

        temperaturas = self._snmp.walk(oids.PON_TEMPERATURA)
        voltajes = self._snmp.walk(oids.PON_VOLTAJE)
        nombres = self._nombres_de_pon()

        indices = sorted(
            {i for i in (indice_simple(o) for o in temperaturas) if i is not None}
            | {i for i in (indice_simple(o) for o in voltajes) if i is not None}
            | set(nombres)
        )
        if not indices:
            log.warning(
                "No se encontró ningún puerto PON en %s. La rama existe pero vino vacía.",
                self.olt.host,
            )
            return []

        conteo, en_linea = self._conteo_de_onus()
        puertos: list[PuertoPON] = []
        for indice in indices:
            puertos.append(
                PuertoPON(
                    olt_id=self.olt_id,
                    indice=indice,
                    nombre=nombres.get(indice, f"GPON0/{indice}"),
                    habilitado=True,
                    operativo=True,
                    cantidad_onus=conteo.get(indice, 0),
                    cantidad_onus_en_linea=en_linea.get(indice, 0),
                    temperatura_celsius=parsers.parsear_temperatura(
                        self._por_indice(temperaturas, indice)
                    ),
                    voltaje_voltios=parsers.parsear_voltaje(self._por_indice(voltajes, indice)),
                    leido_en=momento,
                )
            )
        return puertos

    def _nombres_de_pon(self) -> dict[int, str]:
        nombres: dict[int, str] = {}
        for descripcion in self._snmp.walk(oids.IF_DESCR).values():
            indice = parsers.pon_desde_descripcion(descripcion)
            if indice is not None:
                nombres[indice] = descripcion
        return nombres

    @staticmethod
    def _por_indice(tabla: dict[str, str], indice: int) -> str | None:
        sufijo = f".{indice}"
        for oid, valor in tabla.items():
            if oid.endswith(sufijo):
                return valor
        return None

    def _conteo_de_onus(self) -> tuple[dict[int, int], dict[int, int]]:
        total: dict[int, int] = {}
        en_linea: dict[int, int] = {}
        for oid, valor in self._snmp.walk(oids.ONU_ESTADO).items():
            ref = indice_doble(oid)
            if ref is None:
                continue
            pon, _ = ref
            total[pon] = total.get(pon, 0) + 1
            if parsers.parsear_estado(valor) is EstadoONU.EN_LINEA:
                en_linea[pon] = en_linea.get(pon, 0) + 1
        return total, en_linea

    # --- inventario de ONU ------------------------------------------------

    def discover_onus(self) -> list[ONU]:
        """Inventario completo de ONU.

        Se construye a partir de la **tabla de estado**, cuyos índices son la
        posición ``(pon, onu)``. Los nombres salen de ifDescr cuando se pueden
        emparejar; el número de serie queda vacío porque estos equipos no lo
        publican por SNMP.
        """
        self._exigir(Capacidad.DESCUBRIR_ONUS)
        momento = self._reloj.ahora()

        estados = self._snmp.walk(oids.ONU_ESTADO)
        if not estados:
            # La rama existe en estos equipos: que venga vacía es sospechoso.
            # Se avisa como lectura parcial en vez de reportar "cero ONU", que
            # el sincronizador interpretaría como una baja masiva.
            raise ErrorLecturaParcial(
                f"La tabla de ONU de {self.olt.host} vino vacía. No se asume que no haya ONU.",
                obtenidos=0,
                esperados=None,
            )

        motivos = self._snmp.walk(oids.ONU_MOTIVO_CAIDA)
        subidas = self._snmp.walk(oids.ONU_ULTIMA_SUBIDA)
        bajadas = self._snmp.walk(oids.ONU_ULTIMA_BAJADA)
        tiempos = self._snmp.walk(oids.ONU_TIEMPO_EN_ESTADO)
        nombres = self._nombres_de_onu()

        indexado_motivos = self._indexar(motivos)
        indexado_subidas = self._indexar(subidas)
        indexado_bajadas = self._indexar(bajadas)
        indexado_tiempos = self._indexar(tiempos)

        onus: list[ONU] = []
        for oid, crudo in estados.items():
            ref_cruda = indice_doble(oid)
            if ref_cruda is None:
                continue
            pon, numero = ref_cruda
            ref = RefONU(pon=pon, onu_id=numero)
            estado = parsers.parsear_estado(crudo)
            onus.append(
                ONU(
                    olt_id=self.olt_id,
                    ref=ref,
                    # Verificado: no viaja por SNMP en estos equipos. El
                    # repositorio protege el caso y no pisa un serial ya conocido.
                    numero_serie="",
                    nombre=nombres.get(ref, ""),
                    estado=estado,
                    motivo_caida=parsers.parsear_motivo(indexado_motivos.get(ref)),
                    autorizada=True,
                    ultima_subida=parsers.parsear_fecha(indexado_subidas.get(ref)),
                    ultima_bajada=parsers.parsear_fecha(indexado_bajadas.get(ref)),
                    tiempo_en_estado=(indexado_tiempos.get(ref) or "").strip(),
                    ultima_vez_vista=momento,
                )
            )
        onus.sort(key=lambda o: o.ref)
        return onus

    def _nombres_de_onu(self) -> dict[RefONU, str]:
        nombres: dict[RefONU, str] = {}
        for descripcion in self._snmp.walk(oids.IF_DESCR).values():
            ref_cruda = parsers.ref_desde_descripcion(descripcion)
            if ref_cruda is not None:
                nombres[RefONU(pon=ref_cruda[0], onu_id=ref_cruda[1])] = descripcion
        # El nombre útil (nº de cliente, CDO, NAP) suele estar en ifAlias.
        for alias in self._snmp.walk(oids.IF_ALIAS).values():
            if not alias.strip():
                continue
            ref_cruda = parsers.ref_desde_descripcion(alias)
            if ref_cruda is not None:
                nombres[RefONU(pon=ref_cruda[0], onu_id=ref_cruda[1])] = alias.strip()
        return nombres

    @staticmethod
    def _indexar(tabla: dict[str, str]) -> dict[RefONU, str]:
        indexado: dict[RefONU, str] = {}
        for oid, valor in tabla.items():
            ref_cruda = indice_doble(oid)
            if ref_cruda is not None:
                indexado[RefONU(pon=ref_cruda[0], onu_id=ref_cruda[1])] = valor
        return indexado

    # --- potencias ópticas ------------------------------------------------

    def get_signals(self) -> list[LecturaOptica]:
        self._exigir(Capacidad.POTENCIA_MASIVA)
        momento = self._reloj.ahora()

        rx = self._indexar(self._snmp.walk(oids.ONU_POTENCIA_RX))
        tx = self._indexar(self._snmp.walk(oids.ONU_POTENCIA_TX))
        temperaturas = self._indexar(self._snmp.walk(oids.ONU_TEMPERATURA))
        voltajes = self._indexar(self._snmp.walk(oids.ONU_VOLTAJE))

        # La escala se determina una vez, sobre todas las lecturas juntas, y se
        # aplica pareja. Deducirla valor por valor daría resultados
        # inconsistentes entre ONU de la misma OLT.
        self._escala_dbm = parsers.inferir_escala_dbm(list(rx.values()))
        escala = self._escala_dbm

        refs = sorted(set(rx) | set(tx) | set(temperaturas) | set(voltajes))
        return [
            LecturaOptica(
                ref=ref,
                rx_onu_dbm=parsers.parsear_dbm(rx.get(ref), escala),
                tx_onu_dbm=parsers.parsear_dbm(tx.get(ref), escala),
                temperatura_celsius=parsers.parsear_temperatura(temperaturas.get(ref)),
                voltaje_voltios=parsers.parsear_voltaje(voltajes.get(ref)),
                leido_en=momento,
            )
            for ref in refs
        ]

    def get_signal(self, ref: RefONU) -> LecturaOptica:
        self._exigir(Capacidad.POTENCIA_OPTICA)
        if ref.pon <= 0 or ref.onu_id <= 0:
            raise ErrorValidacion(f"Referencia de ONU inválida: {ref}")
        sufijo = f".{ref.pon}.{ref.onu_id}"
        escala = self._escala_dbm  # None hasta la primera lectura masiva
        return LecturaOptica(
            ref=ref,
            rx_onu_dbm=parsers.parsear_dbm(self._snmp.get(oids.ONU_POTENCIA_RX + sufijo), escala),
            tx_onu_dbm=parsers.parsear_dbm(self._snmp.get(oids.ONU_POTENCIA_TX + sufijo), escala),
            temperatura_celsius=parsers.parsear_temperatura(
                self._snmp.get(oids.ONU_TEMPERATURA + sufijo)
            ),
            voltaje_voltios=parsers.parsear_voltaje(self._snmp.get(oids.ONU_VOLTAJE + sufijo)),
            leido_en=self._reloj.ahora(),
        )

    # --- lo que exige CLI, todavía ausente --------------------------------

    def generate_running_config(self) -> str:
        raise CapacidadNoSoportada(
            "RESPALDO_CONFIGURACION — requiere transporte CLI (Fase 5)", Fabricante.VSOL
        )

    # --- diagnóstico ------------------------------------------------------

    def sondear(self) -> list[MuestraSondeo]:
        """Devuelve valores crudos junto a su interpretación.

        Existe para resolver el único punto que quedó sin confirmar del driver:
        **la escala con la que el equipo publica potencias, temperatura y
        voltaje**. Los parsers la infieren por orden de magnitud; esto permite
        verificar esa inferencia contra un equipo real en un solo comando, sin
        leer código.
        """
        muestras: list[MuestraSondeo] = []

        def agregar(descripcion: str, oid: str, interpretar=None, nota: str = "") -> None:
            crudo = self._snmp.get(oid)
            muestras.append(
                MuestraSondeo(
                    descripcion=descripcion,
                    oid=oid,
                    crudo=crudo,
                    interpretado=interpretar(crudo) if interpretar else crudo,
                    nota=nota,
                )
            )

        agregar("Modelo", oids.MODELO)
        agregar("Nombre del equipo", oids.NOMBRE_EQUIPO)
        agregar("Firmware", oids.FIRMWARE)
        agregar("MAC", oids.MAC)
        agregar("Número de serie", oids.NUMERO_SERIE)
        agregar("Uptime (segundos)", oids.UPTIME, parsers.parsear_uptime)
        agregar(
            "OID engañoso (NO es temperatura)",
            oids.OID_ENGANOSO_NO_USAR,
            nota="Devolvía 39 en una G1 y 87 en una G1-B. El driver no lo usa.",
        )

        # Primera ONU encontrada: sirve para verificar la escala de verdad.
        estados = self._snmp.walk(oids.ONU_ESTADO)
        primera = next(
            (ref for ref in (indice_doble(o) for o in sorted(estados)) if ref is not None), None
        )

        muestras.append(
            MuestraSondeo(
                descripcion="ONU encontradas en la tabla de estado",
                oid=oids.ONU_ESTADO,
                crudo=str(len(estados)),
                interpretado=len(estados),
            )
        )

        if primera is not None:
            pon, numero = primera
            sufijo = f".{pon}.{numero}"
            nota_escala = "Verificar que la interpretación coincida con la web del equipo"
            agregar(
                f"ONU {pon}:{numero} — estado",
                oids.ONU_ESTADO + sufijo,
                parsers.parsear_estado,
            )
            agregar(
                f"ONU {pon}:{numero} — motivo de caída",
                oids.ONU_MOTIVO_CAIDA + sufijo,
                parsers.parsear_motivo,
            )
            agregar(
                f"ONU {pon}:{numero} — RX (dBm)",
                oids.ONU_POTENCIA_RX + sufijo,
                parsers.parsear_dbm,
                nota_escala,
            )
            agregar(
                f"ONU {pon}:{numero} — TX (dBm)",
                oids.ONU_POTENCIA_TX + sufijo,
                parsers.parsear_dbm,
                nota_escala,
            )
            agregar(
                f"ONU {pon}:{numero} — temperatura (°C)",
                oids.ONU_TEMPERATURA + sufijo,
                parsers.parsear_temperatura,
                nota_escala,
            )
            agregar(
                f"ONU {pon}:{numero} — voltaje (V)",
                oids.ONU_VOLTAJE + sufijo,
                parsers.parsear_voltaje,
                nota_escala,
            )

        # Comprobación de la ausencia documentada: debe dar vacío.
        serie = self._snmp.walk(oids.ONU_SERIE_INEXISTENTE)
        muestras.append(
            MuestraSondeo(
                descripcion="Serial de ONU (rama que usa el poller de Pucará)",
                oid=oids.ONU_SERIE_INEXISTENTE,
                crudo=f"{len(serie)} resultados",
                interpretado=len(serie),
                nota=(
                    "Se espera 0: esta rama no existe en la G1-B. Si diera resultados, "
                    "el driver puede declarar SERIAL_POR_SNMP y ganar el descubrimiento "
                    "de ONU sin autorizar."
                ),
            )
        )
        return muestras

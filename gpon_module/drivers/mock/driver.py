"""Driver simulado: una OLT completa que no existe.

Cumple la misma interfaz que un driver real y sostiene estado propio, así que
el módulo entero —servicios, sincronización, alarmas, API y web— se puede
desarrollar y probar sin tocar un equipo de producción.

Dos cosas lo hacen útil de verdad y no un simple relleno:

1. **Reproduce el parque real de ERLAN**: 473 ONU, la misma proporción de
   caídas y la misma mezcla de motivos (corte de luz contra pérdida de señal).
2. **Sabe fallar a pedido**: timeouts, lecturas truncadas, rechazo de comandos.
   Las fallas son la mitad del trabajo de un sistema que habla con equipos por
   la red, y sin poder provocarlas no se pueden probar.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime

from ...core.enums import (
    Capacidad,
    EstadoONU,
    Fabricante,
    ModoServicio,
    MotivoCaida,
    TipoOperacion,
)
from ...core.errors import (
    ErrorAutenticacion,
    ErrorComando,
    ErrorLecturaParcial,
    ErrorTiempoAgotado,
    ErrorValidacion,
)
from ...core.models import (
    OLT,
    ONU,
    ClienteConectado,
    ConfigWiFi,
    CredencialesOLT,
    CredencialPPPoE,
    InfoSistema,
    LecturaOptica,
    LecturaTrafico,
    ONUNoAutorizada,
    Perfiles,
    PuertoLAN,
    PuertoPON,
    RefONU,
    RespaldoConfiguracion,
    ResultadoOperacion,
    SolicitudAutorizacion,
)
from ...core.registry import registrar_driver
from ..base import DriverBase
from .parque import ONUSimulada, ParqueSimulado, generar_parque

#: Todo lo que un equipo ideal podría hacer. Útil para ejercitar el sistema
#: completo sin que ninguna capacidad falte.
PERFIL_COMPLETO: frozenset[Capacidad] = frozenset(Capacidad)

#: Capacidades equivalentes a una VSOL V1600G1/G1-B según lo **verificado** en
#: Fase 0. Sirve para probar hoy, contra el simulador, que la interfaz web y los
#: servicios se comportan bien ante un equipo limitado: sin tráfico por ONU, sin
#: CPU ni memoria, sin temperatura de chasis y sin serial por SNMP.
PERFIL_VSOL: frozenset[Capacidad] = frozenset(
    {
        Capacidad.DESCUBRIR_PUERTOS,
        Capacidad.DESCUBRIR_ONUS,
        Capacidad.DESCUBRIR_NO_AUTORIZADAS,
        Capacidad.DESCUBRIR_PERFILES,
        Capacidad.POTENCIA_OPTICA,
        Capacidad.POTENCIA_MASIVA,
        Capacidad.TEMPERATURA_PON,
        Capacidad.TEMPERATURA_ONU,
        Capacidad.VOLTAJE,
        Capacidad.DISTANCIA,
        Capacidad.UPTIME,
        Capacidad.MOTIVO_CAIDA,
        Capacidad.AUTORIZAR_ONU,
        Capacidad.ELIMINAR_ONU,
        Capacidad.REINICIAR_ONU,
        Capacidad.RESTAURAR_FABRICA,
        Capacidad.GESTION_PERFILES,
        Capacidad.GESTION_VLAN,
        Capacidad.GESTION_SERVICE_PORT,
        Capacidad.RESPALDO_CONFIGURACION,
    }
)


@dataclass
class FallasSimuladas:
    """Fallas que el simulador puede provocar a pedido.

    Cada una corresponde a un riesgo identificado en Fase 0, de modo que el
    manejo de errores se pueda probar en vez de suponer.
    """

    #: No se puede establecer la conexión (R5).
    conexion_falla: bool = False
    #: Credenciales rechazadas.
    autenticacion_falla: bool = False
    #: La lectura se corta a mitad de camino. Fracción que sí se lee, de 0 a 1.
    #: Es el caso que **no** debe interpretarse como baja masiva.
    fraccion_lectura_parcial: float | None = None
    #: El equipo rechaza todo comando de escritura (R2).
    rechazar_comandos: bool = False
    #: La lectura vence por tiempo (R5). Un timeout no es una ausencia.
    lectura_agota_tiempo: bool = False


@registrar_driver(
    Fabricante.SIMULADO,
    nombre="Driver simulado",
    modelos=("V1600G1B-SIM",),
    protocolos=("memoria",),
)
class DriverSimulado(DriverBase):
    """OLT simulada en memoria, con estado que responde a las escrituras."""

    FABRICANTE = Fabricante.SIMULADO
    CAPACIDADES = PERFIL_COMPLETO
    MODELOS = ("V1600G1B-SIM",)

    def __init__(
        self,
        *,
        olt: OLT,
        credenciales: CredencialesOLT,
        dry_run: bool = True,
        reloj: object | None = None,
        parque: ParqueSimulado | None = None,
        capacidades: frozenset[Capacidad] | None = None,
        fallas: FallasSimuladas | None = None,
        semilla: int = 20260804,
        cantidad_onus: int = 473,
    ) -> None:
        super().__init__(olt=olt, credenciales=credenciales, dry_run=dry_run, reloj=reloj)
        self.parque = parque or generar_parque(semilla=semilla, cantidad_onus=cantidad_onus)
        self.fallas = fallas or FallasSimuladas()
        if capacidades is not None:
            # Instancia con capacidades recortadas: permite emular hoy un equipo
            # limitado (p. ej. PERFIL_VSOL) sin escribir un driver aparte.
            self.CAPACIDADES = capacidades
        #: Comandos que se enviaron de verdad. Los tests verifican contra esto
        #: que en modo simulación no se envió absolutamente nada.
        self.comandos_ejecutados: list[str] = []

    # --- ciclo de vida ----------------------------------------------------

    def conectar(self) -> None:
        if self.fallas.autenticacion_falla:
            raise ErrorAutenticacion(f"Credenciales rechazadas por {self.olt.host}")
        if self.fallas.conexion_falla:
            raise ErrorTiempoAgotado(f"No hubo respuesta de {self.olt.host}")
        super().conectar()

    # --- lectura ----------------------------------------------------------

    def _ahora(self) -> datetime:
        return self._reloj.ahora()

    def _verificar_lectura(self, cantidad_total: int) -> int:
        """Aplica las fallas de lectura y devuelve cuántos elementos entregar.

        Cuando la lectura sale truncada levanta ``ErrorLecturaParcial`` con la
        cuenta de lo obtenido: quien la reciba sabe que los datos son válidos
        pero incompletos, y **no** debe concluir que el resto se cayó.
        """
        if self.fallas.lectura_agota_tiempo:
            raise ErrorTiempoAgotado(f"La lectura de {self.olt.host} venció por tiempo")
        fraccion = self.fallas.fraccion_lectura_parcial
        if fraccion is None:
            return cantidad_total
        obtenidos = max(0, int(cantidad_total * fraccion))
        raise ErrorLecturaParcial(
            f"Lectura truncada en {self.olt.host}: {obtenidos} de {cantidad_total}",
            obtenidos=obtenidos,
            esperados=cantidad_total,
        )

    def get_system_info(self) -> InfoSistema:
        if self.fallas.lectura_agota_tiempo:
            raise ErrorTiempoAgotado(f"La lectura de {self.olt.host} venció por tiempo")
        info = self.parque.info
        # Un equipo sin sensor de CPU/memoria no reporta 0: no reporta nada.
        return replace(
            info,
            cpu_porcentaje=info.cpu_porcentaje if self.soporta(Capacidad.CPU) else None,
            memoria_porcentaje=(
                info.memoria_porcentaje if self.soporta(Capacidad.MEMORIA) else None
            ),
            temperatura_celsius=(
                info.temperatura_celsius if self.soporta(Capacidad.TEMPERATURA_CHASIS) else None
            ),
            leido_en=self._ahora(),
        )

    def discover_ports(self) -> list[PuertoPON]:
        self._exigir(Capacidad.DESCUBRIR_PUERTOS)
        self._verificar_lectura(len(self.parque.puertos))
        momento = self._ahora()
        resultado: list[PuertoPON] = []
        for puerto in self.parque.puertos:
            del_pon = [o for ref, o in self.parque.onus.items() if ref.pon == puerto.indice]
            resultado.append(
                replace(
                    puerto,
                    olt_id=self.olt_id,
                    cantidad_onus=len(del_pon),
                    cantidad_onus_en_linea=sum(
                        1 for o in del_pon if o.estado is EstadoONU.EN_LINEA
                    ),
                    leido_en=momento,
                )
            )
        return resultado

    def discover_onus(self) -> list[ONU]:
        self._exigir(Capacidad.DESCUBRIR_ONUS)
        refs = sorted(self.parque.onus)
        entregar = self._verificar_lectura(len(refs))
        momento = self._ahora()
        return [
            replace(
                self.parque.onus[ref].a_modelo(self.olt_id),
                ultima_vez_vista=momento,
                numero_serie=(
                    self.parque.onus[ref].numero_serie
                    if self.soporta(Capacidad.SERIAL_POR_SNMP)
                    or self.soporta(Capacidad.DESCUBRIR_NO_AUTORIZADAS)
                    else ""
                ),
            )
            for ref in refs[:entregar]
        ]

    def discover_unauthorized_onus(self) -> list[ONUNoAutorizada]:
        self._exigir(Capacidad.DESCUBRIR_NO_AUTORIZADAS)
        return list(self.parque.no_autorizadas)

    def get_signal(self, ref: RefONU) -> LecturaOptica:
        self._exigir(Capacidad.POTENCIA_OPTICA)
        simulada = self._buscar(ref)
        return simulada.a_lectura(self._ahora())

    def get_signals(self) -> list[LecturaOptica]:
        self._exigir(Capacidad.POTENCIA_MASIVA)
        refs = sorted(self.parque.onus)
        entregar = self._verificar_lectura(len(refs))
        momento = self._ahora()
        return [self.parque.onus[ref].a_lectura(momento) for ref in refs[:entregar]]

    def get_traffic(self, ref: RefONU) -> LecturaTrafico:
        self._exigir(Capacidad.TRAFICO_POR_ONU)
        simulada = self._buscar(ref)
        # Contadores acumulados y estables por ONU, para que las tasas
        # calculadas entre dos lecturas tengan sentido.
        semilla = int(hashlib.sha256(simulada.numero_serie.encode()).hexdigest()[:8], 16)
        return LecturaTrafico(
            octetos_entrada=semilla % 10_000_000_000,
            octetos_salida=(semilla // 3) % 10_000_000_000,
            paquetes_entrada=semilla % 50_000_000,
            paquetes_salida=(semilla // 7) % 50_000_000,
            leido_en=self._ahora(),
        )

    def get_temperature(self) -> float | None:
        self._exigir(Capacidad.TEMPERATURA_CHASIS)
        return self.parque.info.temperatura_celsius

    def get_distance(self, ref: RefONU) -> int | None:
        self._exigir(Capacidad.DISTANCIA)
        return self._buscar(ref).distancia_metros

    def get_cpu(self) -> float | None:
        self._exigir(Capacidad.CPU)
        return self.parque.info.cpu_porcentaje

    def get_memory(self) -> float | None:
        self._exigir(Capacidad.MEMORIA)
        return self.parque.info.memoria_porcentaje

    def get_uptime(self) -> int | None:
        self._exigir(Capacidad.UPTIME)
        return self.parque.info.uptime_segundos

    def get_profiles(self) -> Perfiles:
        self._exigir(Capacidad.DESCUBRIR_PERFILES)
        return self.parque.perfiles

    def get_connected_clients(self, ref: RefONU) -> list[ClienteConectado]:
        self._exigir(Capacidad.CLIENTES_CONECTADOS)
        simulada = self._buscar(ref)
        if simulada.estado is not EstadoONU.EN_LINEA:
            return []
        return [
            ClienteConectado(
                mac=f"AA:BB:CC:{indice:02X}:{ref.pon:02X}:{ref.onu_id:02X}",
                ip=f"192.168.1.{100 + indice}",
                nombre=f"dispositivo-{indice}",
                interfaz="wlan0" if indice % 2 else "lan1",
            )
            for indice in range(1, 4)
        ]

    def get_lan_ports(self, ref: RefONU) -> list[PuertoLAN]:
        self._exigir(Capacidad.PUERTOS_LAN)
        simulada = self._buscar(ref)
        en_linea = simulada.estado is EstadoONU.EN_LINEA
        return [
            PuertoLAN(
                numero=numero,
                habilitado=True,
                enlace=en_linea and numero == 1,
                velocidad_mbps=1000 if en_linea and numero == 1 else None,
            )
            for numero in range(1, 5)
        ]

    def generate_running_config(self) -> str:
        return self.parque.running_config

    # --- escritura --------------------------------------------------------

    def _ejecutar(self, comandos):
        """Aplica comandos "de verdad" contra el estado simulado."""
        if self.fallas.rechazar_comandos:
            raise ErrorComando(
                "% Invalid input detected at '^' marker",
                comando=comandos[0] if comandos else "",
                salida="% Invalid input detected at '^' marker",
            )
        self.comandos_ejecutados.extend(comandos)
        return "\n".join(f"{comando}  -> ok" for comando in comandos)

    def _buscar(self, ref: RefONU) -> ONUSimulada:
        try:
            return self.parque.onus[ref]
        except KeyError:
            raise ErrorValidacion(f"No existe la ONU {ref} en {self.olt.host}") from None

    def authorize_onu(self, solicitud: SolicitudAutorizacion) -> ResultadoOperacion:
        self._exigir(Capacidad.AUTORIZAR_ONU)
        if not solicitud.numero_serie:
            raise ErrorValidacion("La autorización requiere el número de serie de la ONU")

        ya_existe = next(
            (o for o in self.parque.onus.values() if o.numero_serie == solicitud.numero_serie),
            None,
        )
        if ya_existe is not None:
            return self._fallo(
                TipoOperacion.AUTORIZAR_ONU,
                [],
                error=(
                    f"El serial {solicitud.numero_serie} ya está autorizado "
                    f"en {ya_existe.ref}"
                ),
                ref=ya_existe.ref,
            )

        onu_id = solicitud.onu_id or self.parque.siguiente_id_libre(solicitud.pon)
        ref = RefONU(pon=solicitud.pon, onu_id=onu_id)
        comandos = [
            "configure terminal",
            f"interface gpon 0/{solicitud.pon}",
            f"onu {onu_id} type {solicitud.modelo_onu or 'auto'} sn {solicitud.numero_serie}",
            f"onu {onu_id} description {solicitud.nombre or solicitud.numero_serie}",
            f"onu {onu_id} line-profile {solicitud.perfil_linea or 'linea_100m'}",
            f"onu {onu_id} service-profile {solicitud.perfil_servicio or 'internet'}",
            *(
                [f"service-port gemport 1 uservlan {solicitud.vlan_usuario or solicitud.vlan} "
                 f"vlan {solicitud.vlan}"]
                if solicitud.vlan
                else []
            ),
            "exit",
            "write memory",
        ]

        resultado = self._operacion(
            TipoOperacion.AUTORIZAR_ONU, comandos, self._ejecutar, ref=ref
        )
        if resultado.ok and not self.dry_run:
            self._alta_en_parque(ref, solicitud)
        return resultado

    def _alta_en_parque(self, ref: RefONU, solicitud: SolicitudAutorizacion) -> None:
        pendiente = next(
            (n for n in self.parque.no_autorizadas if n.numero_serie == solicitud.numero_serie),
            None,
        )
        if pendiente is not None:
            self.parque.no_autorizadas.remove(pendiente)
        tx_pon = next(
            (p.potencia_tx_dbm or 3.0 for p in self.parque.puertos if p.indice == ref.pon), 3.0
        )
        self.parque.onus[ref] = ONUSimulada(
            ref=ref,
            numero_serie=solicitud.numero_serie,
            nombre=solicitud.nombre or solicitud.numero_serie,
            modelo=solicitud.modelo_onu or "HG323",
            firmware="V1.3.0",
            estado=EstadoONU.EN_LINEA,
            motivo_caida=MotivoCaida.NINGUNO,
            modo_servicio=solicitud.modo_servicio,
            rx_onu_dbm=-22.5,
            tx_onu_dbm=2.1,
            rx_olt_dbm=-21.8,
            tx_olt_dbm=tx_pon,
            temperatura_celsius=42.0,
            voltaje_voltios=3.3,
            distancia_metros=1200,
            perfil_linea=solicitud.perfil_linea or "linea_100m",
            perfil_servicio=solicitud.perfil_servicio or "internet",
            vlan=solicitud.vlan or 2026,
            ssid=solicitud.wifi.ssid if solicitud.wifi else "",
            clave_wifi=solicitud.wifi.password if solicitud.wifi else "",
            usuario_pppoe=solicitud.pppoe.usuario if solicitud.pppoe else "",
            clave_pppoe=solicitud.pppoe.password if solicitud.pppoe else "",
            ultima_subida=self._ahora(),
        )

    def delete_onu(self, ref: RefONU) -> ResultadoOperacion:
        self._exigir(Capacidad.ELIMINAR_ONU)
        self._buscar(ref)
        comandos = [
            "configure terminal",
            f"interface gpon 0/{ref.pon}",
            f"no onu {ref.onu_id}",
            "exit",
            "write memory",
        ]
        resultado = self._operacion(TipoOperacion.ELIMINAR_ONU, comandos, self._ejecutar, ref=ref)
        if resultado.ok and not self.dry_run:
            self.parque.onus.pop(ref, None)
        return resultado

    def reboot_onu(self, ref: RefONU) -> ResultadoOperacion:
        self._exigir(Capacidad.REINICIAR_ONU)
        simulada = self._buscar(ref)
        comandos = [f"interface gpon 0/{ref.pon}", f"onu {ref.onu_id} reboot"]
        resultado = self._operacion(TipoOperacion.REINICIAR_ONU, comandos, self._ejecutar, ref=ref)
        if resultado.ok and not self.dry_run:
            simulada.reinicios += 1
            simulada.ultima_subida = self._ahora()
        return resultado

    def factory_reset(self, ref: RefONU) -> ResultadoOperacion:
        self._exigir(Capacidad.RESTAURAR_FABRICA)
        simulada = self._buscar(ref)
        comandos = [f"interface gpon 0/{ref.pon}", f"onu {ref.onu_id} factory-reset"]
        resultado = self._operacion(
            TipoOperacion.RESTAURAR_FABRICA, comandos, self._ejecutar, ref=ref
        )
        if resultado.ok and not self.dry_run:
            simulada.ssid = ""
            simulada.clave_wifi = ""
            simulada.usuario_pppoe = ""
            simulada.clave_pppoe = ""
            simulada.modo_servicio = ModoServicio.BRIDGE
        return resultado

    def set_wifi(self, ref: RefONU, config: ConfigWiFi) -> ResultadoOperacion:
        self._exigir(Capacidad.WIFI_POR_OMCI)
        simulada = self._buscar(ref)
        if not config.ssid:
            raise ErrorValidacion("El SSID no puede estar vacío")
        comandos = [
            f"pon-onu-mng gpon 0/{ref.pon}:{ref.onu_id}",
            f"wifi ssid {config.ssid} band {config.banda}",
            f"wifi state {'enable' if config.habilitado else 'disable'}",
            *([f"wifi channel {config.canal}"] if config.canal else []),
            "wifi password ********",
        ]
        resultado = self._operacion(TipoOperacion.CAMBIAR_WIFI, comandos, self._ejecutar, ref=ref)
        if resultado.ok and not self.dry_run:
            simulada.ssid = config.ssid
            if config.password:
                simulada.clave_wifi = config.password
        return resultado

    def change_wifi_password(self, ref: RefONU, password: str) -> ResultadoOperacion:
        self._exigir(Capacidad.WIFI_POR_OMCI)
        simulada = self._buscar(ref)
        if len(password) < 8:
            raise ErrorValidacion("La clave WiFi debe tener al menos 8 caracteres")
        # La clave nunca aparece en el registro de comandos: la auditoría se
        # guarda en base y no debe convertirse en un depósito de contraseñas.
        comandos = [
            f"pon-onu-mng gpon 0/{ref.pon}:{ref.onu_id}",
            "wifi password ********",
        ]
        resultado = self._operacion(
            TipoOperacion.CAMBIAR_CLAVE_WIFI, comandos, self._ejecutar, ref=ref
        )
        if resultado.ok and not self.dry_run:
            simulada.clave_wifi = password
        return resultado

    def change_pppoe(self, ref: RefONU, credencial: CredencialPPPoE) -> ResultadoOperacion:
        self._exigir(Capacidad.PPPOE_POR_OMCI)
        simulada = self._buscar(ref)
        if not credencial.usuario:
            raise ErrorValidacion("El usuario PPPoE no puede estar vacío")
        comandos = [
            f"pon-onu-mng gpon 0/{ref.pon}:{ref.onu_id}",
            f"wan-ip mode pppoe username {credencial.usuario} password ********",
        ]
        resultado = self._operacion(TipoOperacion.CAMBIAR_PPPOE, comandos, self._ejecutar, ref=ref)
        if resultado.ok and not self.dry_run:
            simulada.usuario_pppoe = credencial.usuario
            simulada.clave_pppoe = credencial.password
        return resultado

    def set_bridge(self, ref: RefONU, vlan: int | None = None) -> ResultadoOperacion:
        self._exigir(Capacidad.MODO_BRIDGE_ROUTER)
        simulada = self._buscar(ref)
        comandos = [
            f"pon-onu-mng gpon 0/{ref.pon}:{ref.onu_id}",
            "service internet type bridge",
            *([f"service internet vlan {vlan}"] if vlan else []),
        ]
        resultado = self._operacion(TipoOperacion.MODO_BRIDGE, comandos, self._ejecutar, ref=ref)
        if resultado.ok and not self.dry_run:
            simulada.modo_servicio = ModoServicio.BRIDGE
            if vlan:
                simulada.vlan = vlan
        return resultado

    def set_router(
        self, ref: RefONU, credencial: CredencialPPPoE, vlan: int | None = None
    ) -> ResultadoOperacion:
        self._exigir(Capacidad.MODO_BRIDGE_ROUTER)
        simulada = self._buscar(ref)
        comandos = [
            f"pon-onu-mng gpon 0/{ref.pon}:{ref.onu_id}",
            "service internet type route",
            *([f"service internet vlan {vlan}"] if vlan else []),
            f"wan-ip mode pppoe username {credencial.usuario} password ********",
        ]
        resultado = self._operacion(TipoOperacion.MODO_ROUTER, comandos, self._ejecutar, ref=ref)
        if resultado.ok and not self.dry_run:
            simulada.modo_servicio = ModoServicio.ROUTER
            simulada.usuario_pppoe = credencial.usuario
            simulada.clave_pppoe = credencial.password
            if vlan:
                simulada.vlan = vlan
        return resultado

    def backup_configuration(self) -> RespaldoConfiguracion:
        self._exigir(Capacidad.RESPALDO_CONFIGURACION)
        contenido = self.generate_running_config()
        return RespaldoConfiguracion(
            olt_id=self.olt_id,
            contenido=contenido,
            formato="running-config",
            hash_contenido=hashlib.sha256(contenido.encode()).hexdigest(),
            tomado_en=self._ahora(),
        )

    def restore_configuration(self, respaldo: RespaldoConfiguracion) -> ResultadoOperacion:
        self._exigir(Capacidad.RESTAURACION_CONFIGURACION)
        if not respaldo.contenido.strip():
            raise ErrorValidacion("El respaldo está vacío: no hay nada que restaurar")
        comandos = ["configure terminal", *respaldo.contenido.splitlines(), "end", "write memory"]
        resultado = self._operacion(
            TipoOperacion.RESTAURAR_CONFIGURACION, comandos, self._ejecutar
        )
        if resultado.ok and not self.dry_run:
            self.parque.running_config = respaldo.contenido
        return resultado

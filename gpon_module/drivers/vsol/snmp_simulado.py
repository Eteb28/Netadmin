"""SNMP simulado con la forma exacta de una V1600G1-B.

Sirve para dos cosas, y las dos importan:

* probar el driver VSOL sin una OLT del otro lado;
* dejar escrita, en código ejecutable, **la forma en que este equipo responde**
  — incluidas sus ausencias. Cuando lleguen los walks reales, este archivo se
  compara contra ellos y las diferencias saltan como tests que fallan.
"""

from __future__ import annotations

from ...core.errors import ErrorTiempoAgotado
from . import oids


class SNMPSimuladoVSOL:
    """Responde como una V1600G1-B, con sus limitaciones verificadas."""

    def __init__(
        self,
        *,
        cantidad_pon: int = 8,
        onus_por_pon: int = 4,
        sin_respuesta: bool = False,
        tabla_onu_vacia: bool = False,
        escala_potencia: int = 100,
    ) -> None:
        self.cantidad_pon = cantidad_pon
        self.onus_por_pon = onus_por_pon
        self.sin_respuesta = sin_respuesta
        #: Simula el caso en que la tabla de ONU responde pero sin filas.
        self.tabla_onu_vacia = tabla_onu_vacia
        #: Divisor con el que el equipo publica las potencias. Cambiarlo es la
        #: forma de comprobar que el parser infiere bien la escala.
        self.escala_potencia = escala_potencia
        self.consultas: list[str] = []
        self.cerrado = False

    # --- datos simulados ---

    def _refs(self) -> list[tuple[int, int]]:
        if self.tabla_onu_vacia:
            return []
        return [
            (pon, onu)
            for pon in range(1, self.cantidad_pon + 1)
            for onu in range(1, self.onus_por_pon + 1)
        ]

    def _estado(self, pon: int, onu: int) -> str:
        # Una de cada cinco caída, para que haya de los dos casos.
        return "3" if (pon + onu) % 5 else "4"

    def _motivo(self, pon: int, onu: int) -> str:
        if self._estado(pon, onu) == "3":
            return "N/A"
        return "Power Off" if (pon + onu) % 2 else "Onu Los"

    def _rx(self, pon: int, onu: int) -> str:
        dbm = -18.0 - (pon + onu) % 12
        return str(int(dbm * self.escala_potencia))

    # --- interfaz de transporte ---

    def get(self, oid: str) -> str | None:
        if self.sin_respuesta:
            raise ErrorTiempoAgotado("equipo simulado sin respuesta")
        self.consultas.append(oid)

        fijos = {
            oids.MODELO: "V1600G1B",
            oids.NOMBRE_EQUIPO: "OLT-ERLAN-CENTRO",
            oids.FIRMWARE: "V2.1.7_2023",
            oids.MAC: "00:1E:C0:AA:BB:CC",
            oids.NUMERO_SERIE: "VS2023110001",
            oids.UPTIME: "(123456789) 14 days, 6:56:07.89",
            oids.OID_ENGANOSO_NO_USAR: "87",
        }
        if oid in fijos:
            return fijos[oid]

        for base, generador in (
            (oids.ONU_ESTADO, lambda p, o: self._estado(p, o)),
            (oids.ONU_MOTIVO_CAIDA, lambda p, o: self._motivo(p, o)),
            (oids.ONU_POTENCIA_RX, lambda p, o: self._rx(p, o)),
            (oids.ONU_POTENCIA_TX, lambda p, o: str(int(2.5 * self.escala_potencia))),
            (oids.ONU_TEMPERATURA, lambda p, o: str(42 + (p % 5))),
            (oids.ONU_VOLTAJE, lambda p, o: "3280"),
        ):
            if oid.startswith(base + "."):
                sufijo = oid[len(base) + 1 :].split(".")
                if len(sufijo) == 2 and all(p.isdigit() for p in sufijo):
                    pon, onu = int(sufijo[0]), int(sufijo[1])
                    if (pon, onu) in self._refs():
                        return generador(pon, onu)
                return None
        return None

    def walk(self, oid_base: str) -> dict[str, str]:
        if self.sin_respuesta:
            raise ErrorTiempoAgotado("equipo simulado sin respuesta")
        self.consultas.append(oid_base)

        # Verificado en los equipos reales: esta rama no existe. Devolver un
        # diccionario vacío es lo correcto — el equipo contestó, y no hay nada.
        if oid_base == oids.ONU_SERIE_INEXISTENTE:
            return {}

        if oid_base == oids.PON_TEMPERATURA:
            return {f"{oid_base}.{p}": str(39 + p % 4) for p in range(1, self.cantidad_pon + 1)}
        if oid_base == oids.PON_VOLTAJE:
            return {f"{oid_base}.{p}": "3300" for p in range(1, self.cantidad_pon + 1)}

        if oid_base == oids.IF_DESCR:
            filas = {
                f"{oid_base}.{100 + p}": f"GPON0/{p}" for p in range(1, self.cantidad_pon + 1)
            }
            for indice, (pon, onu) in enumerate(self._refs(), start=200):
                filas[f"{oid_base}.{indice}"] = f"GPON0/{pon}:{onu}"
            return filas
        if oid_base == oids.IF_ALIAS:
            return {
                f"{oid_base}.{200 + indice}": f"CLI{1000 + indice}-CDO{pon}-NAP{onu:02d} "
                f"GPON0/{pon}:{onu}"
                for indice, (pon, onu) in enumerate(self._refs())
            }

        tablas = {
            oids.ONU_ESTADO: self._estado,
            oids.ONU_MOTIVO_CAIDA: self._motivo,
            oids.ONU_POTENCIA_RX: self._rx,
            oids.ONU_POTENCIA_TX: lambda p, o: str(int(2.5 * self.escala_potencia)),
            oids.ONU_TEMPERATURA: lambda p, o: str(42 + (p % 5)),
            oids.ONU_VOLTAJE: lambda p, o: "3280",
            oids.ONU_TIEMPO_EN_ESTADO: lambda p, o: "6 05:49:51",
            oids.ONU_ULTIMA_SUBIDA: lambda p, o: "2026-08-01 09:15:00",
            oids.ONU_ULTIMA_BAJADA: lambda p, o: "0",
        }
        generador = tablas.get(oid_base)
        if generador is None:
            return {}
        return {f"{oid_base}.{pon}.{onu}": generador(pon, onu) for pon, onu in self._refs()}

    def cerrar(self) -> None:
        self.cerrado = True

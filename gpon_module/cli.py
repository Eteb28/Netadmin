"""Interfaz de línea de comandos del módulo GPON.

Sirve para operar el módulo sin interfaz web (que llega en la Fase 3) y, sobre
todo, para verlo funcionando de punta a punta contra la OLT simulada::

    python -m gpon_module.cli demo

Comandos disponibles::

    generar-clave     clave de cifrado para GPON_CLAVE_CIFRADO
    init-db           crea el esquema
    demo              corre un ciclo completo contra la OLT simulada
    alta-olt          registra una OLT
    eliminar-olt <id> da de baja una OLT del módulo (no toca el equipo)
    credenciales <id> cambia usuario, contraseña o community de una OLT
    probar <id>       verifica la conexión con el equipo
    sondear <id>      valores crudos del equipo, para verificar la lectura
    listar-olts       OLT registradas
    descubrir <id>    descubre e inventaría una OLT
    onus <id>         inventario de ONU de una OLT
    web               levanta la interfaz web
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from getpass import getpass

from .config import Configuracion
from .core.cifrado import CifradorFernet
from .core.enums import Capacidad, EstadoONU, Fabricante, MotivoCaida
from .core.errors import ErrorGPON
from .core.models import CredencialesOLT, SolicitudAutorizacion
from .core.optica import clasificar
from .core.registry import fabricantes_registrados
from .drivers.mock.parque import generar_parque
from .services import Contenedor, crear_contenedor


def _configurar_log(nivel: str) -> None:
    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _titulo(texto: str) -> None:
    print(f"\n\033[1m{texto}\033[0m")
    print("─" * len(texto))


# --- comandos -------------------------------------------------------------


def comando_generar_clave(_args: argparse.Namespace) -> int:
    print(CifradorFernet.generar_clave())

    aviso = (
        "\nGuardala en la variable de entorno GPON_CLAVE_CIFRADO.\n"
        "Si se pierde, las credenciales guardadas quedan irrecuperables."
    )
    if os.environ.get("GPON_CLAVE_CIFRADO"):
        # Genera una clave distinta cada vez. Pisar la que ya está en uso deja
        # ilegibles las credenciales de las OLT ya registradas.
        aviso += (
            "\n\nATENCIÓN: ya hay una GPON_CLAVE_CIFRADO definida en este entorno.\n"
            "Si la reemplazás por ésta, las credenciales guardadas con la anterior\n"
            "dejan de poder leerse. Generá una clave nueva sólo para una base nueva."
        )
    print(aviso, file=sys.stderr)
    return 0


def comando_init_db(args: argparse.Namespace) -> int:
    configuracion = Configuracion.desde_entorno()
    if args.base_datos:
        configuracion = _con_base(configuracion, args.base_datos)
    with crear_contenedor(configuracion) as sistema:
        print(f"Esquema creado en {sistema.configuracion.url_base_datos}")
    return 0


def comando_alta_olt(args: argparse.Namespace) -> int:
    """Registra una OLT en la base. No se conecta al equipo: eso es 'probar'."""
    fabricantes = {str(f): f for f in fabricantes_registrados()}
    if args.fabricante not in fabricantes:
        print(
            f"Fabricante '{args.fabricante}' sin driver. "
            f"Disponibles: {', '.join(sorted(fabricantes))}",
            file=sys.stderr,
        )
        return 1

    # La contraseña nunca se pide por parámetro: quedaría en el historial del
    # shell y en la lista de procesos. Se toma del entorno o se pregunta.
    password = os.environ.get("GPON_OLT_PASSWORD") or getpass("Contraseña de la OLT: ")
    comunidad = os.environ.get("GPON_OLT_COMUNIDAD") or args.comunidad

    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.registrar(
            nombre=args.nombre,
            host=args.host,
            fabricante=fabricantes[args.fabricante],
            credenciales=CredencialesOLT(
                usuario=args.usuario,
                password=password,
                comunidad_snmp_lectura=comunidad,
                puerto_snmp=args.puerto_snmp,
                puerto_telnet=args.puerto_telnet,
                puerto_ssh=args.puerto_ssh,
            ),
            descripcion=args.descripcion,
        )
        print(f"OLT #{olt.id} registrada: {olt.nombre} ({olt.host}, {olt.fabricante})")
        print(f"Siguiente paso:  gpon descubrir {olt.id}")
    return 0


def comando_eliminar_olt(args: argparse.Namespace) -> int:
    """Borra una OLT del módulo. **No toca el equipo**, sólo la base local."""
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        cantidad = sistema.repositorio_onu.contar_de_olt(args.olt_id)

        if not args.si:
            print(f"Se va a borrar del módulo la OLT #{olt.id}: {olt.nombre} ({olt.host})")
            print(f"Junto con su inventario: {cantidad} ONU, puertos, perfiles y eventos.")
            print("El equipo NO se toca: no se envía ningún comando ni se da de baja nada.")
            respuesta = input("Escribí 'si' para confirmar: ").strip().lower()
            if respuesta not in ("si", "sí"):
                print("Cancelado.")
                return 1

        sistema.servicio_olt.eliminar(args.olt_id)
        print(f"OLT #{olt.id} eliminada del módulo. El equipo quedó intacto.")
    return 0


def comando_credenciales(args: argparse.Namespace) -> int:
    """Reemplaza las credenciales de una OLT ya registrada."""
    password = os.environ.get("GPON_OLT_PASSWORD") or getpass("Contraseña de la OLT: ")
    comunidad = os.environ.get("GPON_OLT_COMUNIDAD") or args.comunidad

    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        sistema.servicio_olt.actualizar_credenciales(
            args.olt_id,
            CredencialesOLT(
                usuario=args.usuario,
                password=password,
                comunidad_snmp_lectura=comunidad,
                puerto_snmp=args.puerto_snmp,
                puerto_telnet=args.puerto_telnet,
                puerto_ssh=args.puerto_ssh,
            ),
        )
        print(f"Credenciales actualizadas para #{olt.id} {olt.nombre} ({olt.host}).")
        print(f"Verificá con:  gpon probar {olt.id}")
    return 0


def comando_probar(args: argparse.Namespace) -> int:
    """Verifica que se puede hablar con el equipo y actualiza su estado."""
    with _sistema(args) as sistema:
        ok, detalle = sistema.servicio_olt.probar_conexion(args.olt_id)
        print(f"{'OK' if ok else 'FALLÓ'} — {detalle}")
    return 0 if ok else 1


def comando_sondear(args: argparse.Namespace) -> int:
    """Muestra los valores crudos del equipo junto a su interpretación.

    Es la herramienta para confirmar, contra un equipo real, la única cosa que
    el driver VSOL deduce en vez de saber: la escala con la que la OLT publica
    potencias, temperatura y voltaje.
    """
    with _sistema(args) as sistema:
        with sistema.fabrica_drivers.sesion(args.olt_id) as driver:
            if not hasattr(driver, "sondear"):
                print(
                    f"El driver de {driver.fabricante} no tiene sondeo de diagnóstico.",
                    file=sys.stderr,
                )
                return 1
            muestras = driver.sondear()

        _titulo(f"Sondeo de la OLT {args.olt_id}")
        for muestra in muestras:
            print(f"\n{muestra.descripcion}")
            print(f"  OID           {muestra.oid}")
            print(f"  crudo         {muestra.crudo!r}")
            print(f"  interpretado  {muestra.interpretado!r}")
            if muestra.nota:
                print(f"  · {muestra.nota}")
        print(
            "\nCompará 'interpretado' con lo que muestra la web del equipo. "
            "Si alguna potencia o temperatura no coincide, pasame estos valores "
            "y ajusto la escala del parser."
        )
    return 0


def comando_listar_olts(args: argparse.Namespace) -> int:
    with _sistema(args) as sistema:
        olts = sistema.servicio_olt.listar()
        if not olts:
            print("No hay OLT registradas.")
            return 0
        print(f"{'id':>3}  {'nombre':<20} {'host':<16} {'fabricante':<10} {'estado':<14} ONU")
        for olt in olts:
            print(
                f"{olt.id:>3}  {olt.nombre:<20} {olt.host:<16} "
                f"{olt.fabricante!s:<10} {olt.estado!s:<14} {olt.cantidad_onus}"
            )
    return 0


def comando_descubrir(args: argparse.Namespace) -> int:
    with _sistema(args) as sistema:
        resultado = sistema.servicio_descubrimiento.descubrir(args.olt_id)
        _titulo(f"Descubrimiento de {resultado.olt.nombre} ({resultado.olt.host})")
        print(f"Modelo            {resultado.olt.modelo or '—'}")
        print(f"Firmware          {resultado.olt.firmware or '—'}")
        print(f"Puertos PON       {len(resultado.puertos)}")
        print(f"ONU leídas        {resultado.onus_leidas}")
        print(f"ONU nuevas        {resultado.onus_nuevas}")
        print(f"Sin autorizar     {len(resultado.no_autorizadas)}")
        print(f"Lectura           {'completa' if resultado.completo else 'PARCIAL'}")
        print(f"Duración          {resultado.duracion_ms} ms")
        for advertencia in resultado.advertencias:
            print(f"  · {advertencia}")
        if not resultado.completo:
            print(
                "\nLa lectura quedó incompleta. No se dio de baja ninguna ONU: "
                "lo que no se leyó no se da por inexistente."
            )
    return 0


def comando_onus(args: argparse.Namespace) -> int:
    with _sistema(args) as sistema:
        onus = sistema.servicio_onu.listar(args.olt_id, args.pon)
        if not onus:
            print("Sin ONU registradas. ¿Corriste 'descubrir' antes?")
            return 0
        _titulo(f"ONU de la OLT {args.olt_id}" + (f", PON {args.pon}" if args.pon else ""))
        print(f"{'ref':<8} {'serie':<14} {'estado':<16} {'motivo':<16} nombre")
        for onu in onus[: args.limite]:
            print(
                f"{onu.ref!s:<8} {onu.numero_serie:<14} {onu.estado!s:<16} "
                f"{onu.motivo_caida!s:<16} {onu.nombre}"
            )
        if len(onus) > args.limite:
            print(f"… y {len(onus) - args.limite} más")

        estados = Counter(str(o.estado) for o in onus)
        print("\nResumen:", ", ".join(f"{k}={v}" for k, v in sorted(estados.items())))
    return 0


def comando_web(args: argparse.Namespace) -> int:
    """Levanta la interfaz web.

    Con ``--simulada`` arranca contra la OLT simulada y una base en memoria:
    sirve para recorrer la interfaz sin tener ningún equipo ni base configurada.
    """
    try:
        from .web import crear_app
    except ImportError:
        print(
            "Falta Flask. Instalalo con:  pip install 'gpon-module[web]'",
            file=sys.stderr,
        )
        return 1

    if args.simulada:
        configuracion = Configuracion(
            url_base_datos="sqlite:///:memory:",
            permitir_cifrado_nulo=True,
            dry_run_por_defecto=True,
        )
        parque = generar_parque(cantidad_onus=args.onus)
        sistema = crear_contenedor(configuracion, extras_driver={"parque": parque})
        olt = sistema.servicio_olt.registrar(
            nombre="OLT simulada",
            host="10.255.0.1",
            fabricante=Fabricante.SIMULADO,
            credenciales=CredencialesOLT(usuario="admin", password="simulada"),
            descripcion="Equipo de demostración, no existe",
        )
        sistema.servicio_descubrimiento.descubrir(olt.id)
        print(f"OLT simulada lista con {args.onus} ONU. Nada de esto es un equipo real.")
    else:
        sistema = _sistema(args)

    app = crear_app(sistema, modo_debug=args.debug)
    print(f"\n  Interfaz web en  http://{args.host}:{args.puerto}\n")
    app.run(host=args.host, port=args.puerto, debug=args.debug, use_reloader=False)
    return 0


def comando_demo(args: argparse.Namespace) -> int:
    """Ciclo completo contra la OLT simulada: alta, descubrimiento y operación.

    No toca ningún equipo real y no necesita base previa: es la comprobación
    de que el módulo funciona entero por sí solo.
    """
    configuracion = Configuracion(
        url_base_datos=args.base_datos or "sqlite:///:memory:",
        permitir_cifrado_nulo=True,
        dry_run_por_defecto=True,
    )
    # Un único parque compartido: así las escrituras que se ejecuten de verdad
    # se ven reflejadas en las lecturas siguientes.
    parque = generar_parque(cantidad_onus=args.onus)

    with crear_contenedor(configuracion, extras_driver={"parque": parque}) as sistema:
        _titulo("1. Alta de la OLT")
        olt = sistema.servicio_olt.registrar(
            nombre="OLT simulada",
            host="10.255.0.1",
            fabricante=Fabricante.SIMULADO,
            credenciales=CredencialesOLT(usuario="admin", password="Xpon@Olt9417#"),
            descripcion="Equipo de demostración, no existe",
        )
        ok, detalle = sistema.servicio_olt.probar_conexion(olt.id)
        print(f"OLT #{olt.id} registrada. Conexión: {'ok' if ok else 'falló'} — {detalle}")

        _titulo("2. Descubrimiento")
        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)
        print(f"Puertos PON      {len(resultado.puertos)}")
        print(f"ONU descubiertas {resultado.onus_leidas} ({resultado.onus_nuevas} nuevas)")
        print(f"Sin autorizar    {len(resultado.no_autorizadas)}")
        print(f"Perfiles DBA     {len(resultado.perfiles.dba)}")
        print(f"VLAN             {len(resultado.perfiles.vlans)}")

        _titulo("3. Estado del parque")
        estados = sistema.servicio_onu.resumen_estado(olt.id)
        for estado, cantidad in sorted(estados.items()):
            print(f"  {estado:<18} {cantidad:>4}")
        motivos = Counter(
            str(o.motivo_caida)
            for o in sistema.servicio_onu.listar(olt.id)
            if o.estado is EstadoONU.FUERA_DE_LINEA
        )
        if motivos:
            print("  Motivos de caída:")
            for motivo, cantidad in sorted(motivos.items()):
                nota = ""
                if motivo == str(MotivoCaida.APAGADO):
                    nota = "  ← corte de luz en el domicilio"
                elif motivo == str(MotivoCaida.PERDIDA_SENAL):
                    nota = "  ← problema de fibra: requiere cuadrilla"
                print(f"    {motivo:<16} {cantidad:>4}{nota}")

        _titulo("4. Potencias ópticas")
        potencias = sistema.servicio_onu.potencias(olt.id)
        con_lectura = [p for p in potencias if p.rx_dbm is not None]
        clasificaciones = Counter(str(p.clasificacion) for p in potencias)
        for clase, cantidad in sorted(clasificaciones.items()):
            print(f"  {clase:<14} {cantidad:>4}")
        if con_lectura:
            peor = min(con_lectura, key=lambda p: p.rx_dbm)
            mejor = max(con_lectura, key=lambda p: p.rx_dbm)
            print(f"  Más débil: {peor.rx_dbm} dBm en {peor.lectura.ref}")
            print(
                f"  Más fuerte: {mejor.rx_dbm} dBm en {mejor.lectura.ref} "
                f"({clasificar(mejor.rx_dbm)})"
            )

        _titulo("5. Autorización de una ONU (simulada)")
        pendiente = resultado.no_autorizadas[0]
        operacion = sistema.servicio_onu.autorizar(
            olt.id,
            SolicitudAutorizacion(
                numero_serie=pendiente.numero_serie,
                pon=pendiente.pon,
                nombre="CLIENTE-DEMO",
                perfil_linea="linea_100m",
                perfil_servicio="internet",
                vlan=2026,
            ),
            usuario="demo",
        )
        print(f"Resultado: {'ok' if operacion.ok else 'falló'} · simulado={operacion.simulado}")
        print("Comandos que se habrían enviado al equipo:")
        for comando in operacion.comandos_enviados:
            print(f"    {comando}")

        _titulo("6. Capacidades declaradas por el driver")
        capacidades = sistema.servicio_olt.capacidades(olt.id)
        faltantes = sorted(c.name for c in Capacidad if c not in capacidades)
        print(f"Soportadas: {len(capacidades)} de {len(list(Capacidad))}")
        if faltantes:
            print(f"No soportadas: {', '.join(faltantes)}")
        print("La interfaz web oculta lo no soportado en vez de mostrarlo y fallar.")

        _titulo("7. Auditoría")
        for op in sistema.repositorio_operacion.listar(limite=5):
            marca = "SIMULADA" if op.simulado else "REAL"
            print(f"  [{marca}] {op.tipo} por {op.usuario} — ok={op.ok}")

    print("\nListo. No se tocó ningún equipo real.\n")
    return 0


# --- utilidades -----------------------------------------------------------


def _con_base(configuracion: Configuracion, url: str) -> Configuracion:
    from dataclasses import replace

    return replace(configuracion, url_base_datos=url)


def _sistema(args: argparse.Namespace) -> Contenedor:
    configuracion = Configuracion.desde_entorno()
    if getattr(args, "base_datos", None):
        configuracion = _con_base(configuracion, args.base_datos)
    return crear_contenedor(configuracion)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpon_module",
        description="Administración GPON multifabricante",
    )
    parser.add_argument("--log", default="WARNING", help="nivel de registro (INFO, DEBUG…)")
    parser.add_argument("--base-datos", help="URL de base de datos, p. ej. sqlite:///gpon.db")

    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("generar-clave", help="genera una clave de cifrado").set_defaults(
        funcion=comando_generar_clave
    )
    sub.add_parser("init-db", help="crea el esquema").set_defaults(funcion=comando_init_db)
    sub.add_parser("listar-olts", help="lista las OLT registradas").set_defaults(
        funcion=comando_listar_olts
    )

    alta = sub.add_parser("alta-olt", help="registra una OLT")
    alta.add_argument("--nombre", required=True)
    alta.add_argument("--host", required=True, help="dirección IP o nombre del equipo")
    alta.add_argument(
        "--fabricante",
        required=True,
        choices=sorted(str(f) for f in fabricantes_registrados()),
    )
    alta.add_argument("--usuario", default="admin")
    alta.add_argument("--comunidad", default="public", help="community SNMP de lectura")
    alta.add_argument("--descripcion", default="")
    alta.add_argument("--puerto-snmp", type=int, default=161)
    alta.add_argument("--puerto-telnet", type=int, default=23)
    alta.add_argument("--puerto-ssh", type=int, default=22)
    alta.set_defaults(funcion=comando_alta_olt)

    baja = sub.add_parser("eliminar-olt", help="borra una OLT del módulo (no toca el equipo)")
    baja.add_argument("olt_id", type=int)
    baja.add_argument("--si", action="store_true", help="no preguntar confirmación")
    baja.set_defaults(funcion=comando_eliminar_olt)

    credenciales = sub.add_parser("credenciales", help="cambia las credenciales de una OLT")
    credenciales.add_argument("olt_id", type=int)
    credenciales.add_argument("--usuario", default="admin")
    credenciales.add_argument("--comunidad", default="public")
    credenciales.add_argument("--puerto-snmp", type=int, default=161)
    credenciales.add_argument("--puerto-telnet", type=int, default=23)
    credenciales.add_argument("--puerto-ssh", type=int, default=22)
    credenciales.set_defaults(funcion=comando_credenciales)

    probar = sub.add_parser("probar", help="verifica la conexión con una OLT")
    probar.add_argument("olt_id", type=int)
    probar.set_defaults(funcion=comando_probar)

    sondear = sub.add_parser("sondear", help="valores crudos del equipo, para verificar")
    sondear.add_argument("olt_id", type=int)
    sondear.set_defaults(funcion=comando_sondear)

    servidor = sub.add_parser("web", help="levanta la interfaz web")
    servidor.add_argument("--host", default="127.0.0.1", help="dirección de escucha")
    servidor.add_argument("--puerto", type=int, default=8070)
    servidor.add_argument(
        "--simulada",
        action="store_true",
        help="arranca con una OLT simulada y base en memoria, sin configurar nada",
    )
    servidor.add_argument("--onus", type=int, default=473, help="ONU a simular")
    servidor.add_argument("--debug", action="store_true")
    servidor.set_defaults(funcion=comando_web)

    demo = sub.add_parser("demo", help="ciclo completo contra la OLT simulada")
    demo.add_argument("--onus", type=int, default=473, help="cantidad de ONU a simular")
    demo.set_defaults(funcion=comando_demo)

    descubrir = sub.add_parser("descubrir", help="descubre e inventaría una OLT")
    descubrir.add_argument("olt_id", type=int)
    descubrir.set_defaults(funcion=comando_descubrir)

    onus = sub.add_parser("onus", help="inventario de ONU")
    onus.add_argument("olt_id", type=int)
    onus.add_argument("--pon", type=int, help="filtrar por puerto PON")
    onus.add_argument("--limite", type=int, default=25)
    onus.set_defaults(funcion=comando_onus)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    _configurar_log(args.log)
    try:
        return int(args.funcion(args))
    except ErrorGPON as exc:
        print(f"\nError: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

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
    capturar <id>     qué comandos entiende la CLI del equipo (sólo lectura)
    probar-cli <id>   por qué puerto se puede entrar a la CLI, y por cuál no
    cargar-equipos    da de alta las OLT descritas en equipos.toml
    inventario-cli    completa el inventario con los seriales, leídos por CLI
    explorar-config   busca los comandos de GPON en los modos de la CLI
    pendientes <id>   ONU detectadas y sin autorizar (AutoFind)
    autorizar <id>    da de alta una ONU (simulado salvo que se pida --aplicar)
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
from dataclasses import replace
from getpass import getpass

from .config import Configuracion
from .core.cifrado import CifradorFernet
from .core.enums import Capacidad, EstadoONU, Fabricante, MotivoCaida
from .core.errors import ErrorAutenticacion, ErrorGPON, ErrorTransporte
from .core.models import CredencialesOLT, SolicitudAutorizacion
from .core.optica import clasificar
from .core.registry import fabricantes_registrados
from .drivers.mock.parque import generar_parque
from .drivers.transport import PROTOCOLOS_CLI
from .drivers.transport.deteccion import sondear_gestion
from .drivers.vsol.parser_config import parsear_running_config
from .services import (
    Contenedor,
    ServicioInventarioArchivo,
    crear_contenedor,
    leer_equipos,
)


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
    """Cambia las credenciales de una OLT, **conservando lo que no se indique**.

    Es deliberado que sólo toque lo que se pide. Corregir la contraseña de la
    CLI no debería poder romper la lectura por SNMP, y con valores por defecto
    aplicados a ciegas la community volvería a 'public' sin que nadie lo pida.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        actuales = sistema.repositorio_olt.obtener_credenciales(args.olt_id)

        password = os.environ.get("GPON_OLT_PASSWORD")
        if password is None:
            escrita = getpass("Contraseña de la OLT (vacío = dejar la que está): ")
            password = escrita or actuales.password

        password_enable = actuales.password_enable
        if args.con_enable:
            password_enable = getpass("Contraseña de 'enable' (vacío = igual a la anterior): ")

        nuevas = replace(
            actuales,
            usuario=args.usuario or actuales.usuario,
            password=password,
            password_enable=password_enable,
            comunidad_snmp_lectura=(
                os.environ.get("GPON_OLT_COMUNIDAD")
                or args.comunidad
                or actuales.comunidad_snmp_lectura
            ),
            puerto_snmp=args.puerto_snmp or actuales.puerto_snmp,
            puerto_telnet=args.puerto_telnet or actuales.puerto_telnet,
            puerto_ssh=args.puerto_ssh or actuales.puerto_ssh,
        )
        sistema.servicio_olt.actualizar_credenciales(args.olt_id, nuevas)

        print(f"Credenciales actualizadas para #{olt.id} {olt.nombre} ({olt.host}).")
        print(f"  usuario          {nuevas.usuario}")
        print(f"  community SNMP   {'(sin cambios)' if nuevas.comunidad_snmp_lectura else '—'}")
        print(
            f"  puertos          snmp {nuevas.puerto_snmp} · telnet "
            f"{nuevas.puerto_telnet} · ssh {nuevas.puerto_ssh}"
        )
        print(f"\nVerificá la lectura con:  gpon probar {olt.id}")
        print(f"Y la CLI con:             gpon capturar {olt.id} --protocolo ssh")
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


def comando_capturar(args: argparse.Namespace) -> int:
    """Registra qué comandos entiende la CLI de la OLT y qué devuelven.

    Es el paso previo obligatorio a autorizar y configurar ONU. Todo eso es CLI
    —en VSOL el serial no viaja por SNMP—, y la sintaxis cambia entre versiones
    de firmware. Antes de escribir un comando de configuración hay que ver la
    salida real del equipo, no el manual de otra versión.

    No envía ni un solo comando de escritura: hay un filtro que lo impide.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        comandos = args.comando_extra or None

        _titulo(f"Captura CLI de {olt.nombre} ({olt.host}) por {args.protocolo}")
        print("Sólo se envían comandos de lectura. No se modifica ninguna configuración.")
        print("Puede tardar varios minutos: cada comando espera la respuesta completa.\n")

        def progreso(salida) -> None:
            marca = "\033[32mok \033[0m" if salida.ok else "\033[33mn/d\033[0m"
            etiqueta = salida.comando or "? (árbol completo)"
            print(f"  {marca}  {etiqueta:<34} {salida.duracion_ms:>6} ms")

        password = getpass("Contraseña para esta prueba: ") if args.preguntar_password else None

        try:
            captura = sistema.servicio_captura.capturar(
                args.olt_id,
                protocolo=args.protocolo,
                comandos=comandos,
                incluir_ayuda=not args.sin_ayuda,
                timeout=args.timeout,
                al_avanzar=progreso,
                usuario=args.usuario,
                password=password,
                ruta_traza=args.traza,
            )
        except ErrorAutenticacion as exc:
            # Acá el canal está bien: lo que falla son las credenciales. Un
            # escaneo de puertos no aportaría nada, así que se dice lo que sí
            # sirve.
            print(f"\n{exc}\n", file=sys.stderr)
            _ayuda_credenciales(args.olt_id, args.protocolo)
            return 1
        except ErrorTransporte as exc:
            # No alcanza con decir "no respondió": lo que hace falta saber es
            # si el equipo no escucha ahí o si el paquete no llega. Se averigua
            # en el momento, mientras el operador está mirando la pantalla.
            print(f"\nNo se pudo abrir la CLI: {exc}\n", file=sys.stderr)
            _diagnosticar_gestion(olt.host)
            return 1

    destino = args.salida or f"captura-olt{args.olt_id}-{captura.momento:%Y%m%d-%H%M}.txt"
    with open(destino, "w", encoding="utf-8") as archivo:
        archivo.write(captura.a_texto())

    _titulo("Resultado")
    print(f"Comandos con datos : {len(captura.aceptados)}")
    print(f"No disponibles     : {len(captura.rechazados)}")
    print(f"Archivo            : {destino}")
    print(
        "\nRevisá el archivo antes de compartirlo: 'show running-config' puede\n"
        "incluir contraseñas del equipo y de PPPoE de los clientes."
    )
    return 0


def comando_cargar_equipos(args: argparse.Namespace) -> int:
    """Da de alta o actualiza las OLT descritas en un archivo TOML.

    Es idempotente: identifica cada equipo por su dirección, crea el que falta y
    actualiza el que ya está. Correrlo dos veces no duplica nada, y corregir una
    contraseña es editar el archivo y volver a correrlo.
    """
    equipos = leer_equipos(args.archivo)

    with _sistema(args) as sistema:
        servicio = ServicioInventarioArchivo(sistema.servicio_olt, sistema.repositorio_olt)
        resultado = servicio.aplicar(equipos)

    _titulo(f"Equipos cargados desde {args.archivo}")
    for creada in resultado.creadas:
        print(f"  nueva        {creada}")
    for actualizada in resultado.actualizadas:
        print(f"  actualizada  {actualizada}")
    if not resultado.total:
        print("  (el archivo no declaraba ningún equipo)")
        return 1

    print(f"\n{resultado.total} equipo(s). Siguiente paso:")
    print("  gpon listar-olts")
    print("  gpon probar <id>")
    return 0


def comando_inventario_cli(args: argparse.Namespace) -> int:
    """Completa el inventario con lo que sólo la CLI sabe: los seriales.

    SNMP da el estado en vivo de cada ONU pero no su número de serie, y sin
    serial no se puede identificar un cliente. El serial vive en la
    configuración del equipo, así que se lee de ahí. Es sólo lectura: el único
    comando que se envía es 'show running-config'.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        _titulo(f"Inventario por CLI de {olt.nombre} ({olt.host})")

        if args.desde_archivo:
            print(f"Leyendo la configuración de {args.desde_archivo} (no se toca el equipo).")
            with open(args.desde_archivo, encoding="utf-8", errors="replace") as archivo:
                texto = archivo.read()
            resultado = sistema.servicio_inventario_cli.aplicar(
                args.olt_id, parsear_running_config(texto)
            )
        else:
            print(f"Leyendo 'show running-config' por {args.protocolo}. No se modifica nada.")
            try:
                resultado = sistema.servicio_inventario_cli.importar(
                    args.olt_id,
                    protocolo=args.protocolo,
                    timeout=args.timeout,
                    ruta_traza=args.traza,
                )
            except ErrorAutenticacion as exc:
                print(f"\n{exc}\n", file=sys.stderr)
                _ayuda_credenciales(args.olt_id, args.protocolo)
                return 1

    print(f"\nONU en la configuración   {resultado.onus_en_configuracion}")
    print(f"ONU actualizadas          {resultado.onus_actualizadas}")
    print(f"Seriales nuevos           {resultado.series_nuevas}")
    print(f"Perfiles DBA              {resultado.perfiles_dba}")
    print(f"Perfiles de tráfico       {resultado.perfiles_trafico}")
    print(f"VLAN                      {resultado.vlans}")

    if resultado.onus_solo_en_configuracion:
        print(
            f"\n{len(resultado.onus_solo_en_configuracion)} ONU están dadas de alta en el "
            "equipo pero no las vio SNMP.\nProbablemente estén configuradas y todavía sin "
            "conectar. Las primeras:"
        )
        for entrada in resultado.onus_solo_en_configuracion[:10]:
            print(f"    {entrada}")

    if resultado.pon_sin_autoaprendizaje:
        print(
            "\nPuertos PON con el autoaprendizaje apagado: "
            f"{', '.join(resultado.pon_sin_autoaprendizaje)}.\n"
            "Ahí una ONU nueva no aparece sola: hay que darla de alta a mano."
        )

    print(f"\nVerlo en la web:  gpon web   →  /olts/{args.olt_id}/onus")
    return 0


def comando_explorar_config(args: argparse.Namespace) -> int:
    """Busca los comandos de GPON entrando a modo configuración.

    En este firmware el 'show' del modo EXEC es el del switch y no tiene nada de
    GPON: lo que interesa vive dentro de 'configure terminal' y de
    'interface gpon 0/N'. Para verlo hay que entrar a esos modos.

    **Entrar a modo configuración no cambia ninguna configuración**, pero sí es
    más que mirar de afuera, así que conviene saberlo. Los únicos comandos que
    se ejecutan son de navegación entre modos y 'show'; todo lo demás se
    pregunta con '?', que no ejecuta nada. Al terminar se vuelve con 'end'.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)

        _titulo(f"Explorando la CLI de {olt.nombre} ({olt.host}), puerto {args.pon}")
        print("Se entra a modo configuración para leer la ayuda en línea.")
        print("No se ejecuta ningún comando de configuración, y se vuelve con 'end'.\n")

        if not args.si:
            respuesta = input("Escribí 'si' para continuar: ").strip().lower()
            if respuesta not in ("si", "sí"):
                print("Cancelado. No se tocó el equipo.")
                return 1
            print()

        def progreso(salida) -> None:
            marca = "\033[32mok \033[0m" if salida.ok else "\033[33mn/d\033[0m"
            es_ayuda = salida.proposito.startswith("Ayuda")
            etiqueta = f"{salida.comando}?" if es_ayuda else salida.comando
            print(f"  {marca}  [{salida.grupo:<20}] {etiqueta}")

        try:
            exploracion = sistema.servicio_exploracion.explorar(
                args.olt_id,
                pon=args.pon,
                protocolo=args.protocolo,
                timeout=args.timeout,
                ruta_traza=args.traza,
                al_avanzar=progreso,
            )
        except ErrorAutenticacion as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            _ayuda_credenciales(args.olt_id, args.protocolo)
            return 1

    destino = args.salida or f"exploracion-olt{args.olt_id}-{exploracion.momento:%Y%m%d-%H%M}.txt"
    with open(destino, "w", encoding="utf-8") as archivo:
        archivo.write(exploracion.a_texto())

    _titulo("Resultado")
    print(f"Comandos con datos : {len(exploracion.aceptados)}")
    print(f"Recorrido          : {' → '.join(exploracion.recorrido)}")
    print(f"Archivo            : {destino}")
    print("\nLa sesión volvió al modo EXEC. No se modificó ninguna configuración.")
    return 0


def comando_pendientes(args: argparse.Namespace) -> int:
    """Lista las ONU detectadas y sin autorizar, para dar de alta un cliente.

    Es la pantalla "ONU AutoFind" de la web del equipo, por consola. Recorre los
    puertos PON en una sola sesión y muestra lo que está esperando.

    Sólo lectura: el comando que se envía es 'show onu auto-find'. Vive dentro
    de 'interface gpon 0/N', así que se entra a modo configuración y se sale con
    'end', sin ejecutar ahí ningún comando de configuración.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        puertos = tuple(args.pon) if args.pon else ()

        _titulo(f"ONU esperando autorización en {olt.nombre} ({olt.host})")
        try:
            resultado = sistema.servicio_pendientes.listar(
                args.olt_id,
                puertos=puertos,
                protocolo=args.protocolo,
                timeout=args.timeout,
                ruta_traza=args.traza,
            )
        except ErrorAutenticacion as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            _ayuda_credenciales(args.olt_id, args.protocolo)
            return 1

    if args.serie:
        encontrada = resultado.buscar(args.serie)
        if encontrada is None:
            print(f"El serial {args.serie} NO está esperando autorización.")
            print("\nPuede ser que la ONU todavía no llegó a registrarse, que esté")
            print("en otra OLT, o que el serial venga con un error de tipeo.")
            return 1
        print(f"{args.serie} está esperando en el PON {encontrada.pon}.")
        print(f"  índice propuesto : {encontrada.indice_propuesto}")
        print(f"  estado           : {encontrada.estado_informado}")
        return 0

    if not resultado.pendientes:
        print("No hay ninguna ONU esperando autorización.")
    else:
        print(f"{'PON':<6} {'Número de serie':<18} {'Índice':<8} Estado")
        for pendiente in resultado.pendientes:
            indice = "" if pendiente.indice_propuesto is None else pendiente.indice_propuesto
            print(
                f"{pendiente.pon:<6} {pendiente.numero_serie:<18} "
                f"{indice!s:<8} {pendiente.estado_informado}"
            )

    if resultado.puertos_con_falla:
        print("\nPuertos que no se pudieron leer (no significa que no tengan ONU):")
        for pon, motivo in resultado.puertos_con_falla:
            print(f"    {pon}: {motivo}")

    return 0


def comando_autorizar(args: argparse.Namespace) -> int:
    """Da de alta una ONU que está esperando en un puerto PON.

    **Por defecto no envía nada**: muestra la secuencia exacta que aplicaría.
    Para que salga de verdad al equipo hay que agregar --aplicar y confirmar.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)
        _titulo(f"Alta de {args.serie} en {olt.nombre} ({olt.host})")

        if args.aplicar:
            print("\033[33mMODO REAL: los comandos se van a enviar al equipo.\033[0m")
        else:
            print("Modo simulación: no se envía ningún comando. Agregá --aplicar para hacerlo.")

        try:
            resultado = sistema.servicio_alta_onu.autorizar(
                args.olt_id,
                numero_serie=args.serie,
                pon=args.pon,
                onu_id=args.indice,
                perfil_onu=args.perfil,
                descripcion=args.descripcion,
                perfil_dba=args.dba,
                trafico_subida=args.subida,
                trafico_bajada=args.bajada,
                vlan=args.vlan,
                dry_run=not args.aplicar,
                protocolo=args.protocolo,
                timeout=args.timeout,
                usuario=args.usuario_operacion,
                ruta_traza=args.traza,
            )
        except ErrorAutenticacion as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            _ayuda_credenciales(args.olt_id, args.protocolo)
            return 1

    solicitud = resultado.solicitud
    print(f"\nPuerto PON  {solicitud.pon}")
    print(f"Índice ONU  {solicitud.onu_id}")
    print(f"Perfil      {solicitud.perfil_onu}")
    print(f"Descripción {solicitud.descripcion_efectiva}")

    _titulo("Comandos" if resultado.simulado else "Comandos enviados")
    for comando in resultado.comandos:
        if resultado.simulado:
            marca = " "
        else:
            marca = "+" if comando in resultado.comandos_aplicados else "·"
        print(f"  {marca} {comando}")

    if resultado.simulado:
        print("\nNo se envió ninguno. Para aplicarlo de verdad:")
        print(
            f"  gpon autorizar {args.olt_id} --serie {args.serie} --perfil {args.perfil} --aplicar"
        )
        return 0

    if resultado.ok:
        ubicacion = f"{solicitud.pon}:{solicitud.onu_id}"
        print(f"\n\033[32mONU {args.serie} autorizada en {ubicacion}.\033[0m")
        print("Verificala con:  gpon inventario-cli", args.olt_id)
        return 0

    print(f"\n\033[31mEl equipo rechazó: {resultado.comando_que_fallo}\033[0m", file=sys.stderr)
    print(f"{resultado.error}", file=sys.stderr)
    if resultado.quedo_a_medias:
        print(
            f"\nATENCIÓN: se alcanzaron a aplicar {len(resultado.comandos_aplicados)} comandos.\n"
            f"La ONU {solicitud.pon}:{solicitud.onu_id} quedó a medio configurar y hay que\n"
            "revisarla en el equipo antes de reintentar.",
            file=sys.stderr,
        )
    return 1


def comando_probar_cli(args: argparse.Namespace) -> int:
    """Dice por dónde se puede entrar a la CLI de una OLT, y por dónde no.

    No manda credenciales ni comandos: abre y cierra una conexión TCP. Sirve
    para separar dos problemas que se parecen y no lo son —el servicio está
    apagado, o el paquete no llega— antes de sospechar de la contraseña.
    """
    with _sistema(args) as sistema:
        olt = sistema.servicio_olt.obtener(args.olt_id)

    _titulo(f"Puertos de gestión de {olt.nombre} ({olt.host})")
    print("Sólo se abre y cierra una conexión. No se envía usuario ni contraseña.\n")
    _diagnosticar_gestion(olt.host, timeout=args.timeout)
    return 0


def _ayuda_credenciales(olt_id: int, protocolo: str) -> None:
    """Qué revisar cuando el canal abre pero el equipo rechaza el login."""
    print("El canal está bien: el equipo escucha y contesta. Lo que rechaza es")
    print("el usuario o la contraseña.\n")
    print("Lo más común, en orden:\n")
    print("  1. La contraseña guardada es la que se cargó en 'alta-olt'. Si ahí")
    print("     se puso la community SNMP o una contraseña vieja, es esto.")
    print(f"     Corregila:  gpon credenciales {olt_id}")
    print("     (sólo cambia lo que le indiques: la community SNMP queda intacta)\n")
    print("  2. El usuario de la CLI puede no ser el mismo que el de la web.")
    print("     Probá otros sin guardar nada:")
    print(
        f"       gpon capturar {olt_id} --protocolo {protocolo} --usuario root "
        "--preguntar-password\n"
    )
    print("  3. Verificalo a mano, que descarta el módulo entero del medio:")
    print("       ssh admin@<ip-de-la-olt>\n")
    print("Ojo con el bloqueo por intentos fallidos: varias OLT bloquean la")
    print("cuenta o la IP después de unos pocos. Si probás a mano y tampoco")
    print("entra, revisá el usuario en la web del equipo antes de seguir.")


def _diagnosticar_gestion(host: str, timeout: float = 3.0) -> None:
    """Sondea los puertos de gestión y dice qué hacer con el resultado."""
    sondeos = sondear_gestion(host, timeout=timeout)
    for sondeo in sondeos:
        color = "\033[32m" if sondeo.abierto else "\033[33m"
        etiqueta = f"{sondeo.puerto} ({sondeo.servicio})" if sondeo.servicio else str(sondeo.puerto)
        print(f"  {color}{sondeo.estado:<14}\033[0m {etiqueta:<18} {sondeo.explicacion}")

    abiertos = [s for s in sondeos if s.abierto]
    cli = [s for s in abiertos if s.puerto in (22, 23)]

    print()
    if cli:
        protocolo = "ssh" if any(s.puerto == 22 for s in cli) else "telnet"
        print(f"Probá la captura por ahí:  gpon capturar <id> --protocolo {protocolo}")
        if protocolo == "ssh":
            print("SSH necesita paramiko:     pip install paramiko")
        return

    print("Ningún puerto de CLI responde. Las opciones, en orden:")
    print("  1. Habilitar Telnet o SSH en la OLT, desde su interfaz web.")
    print("  2. Revisar la lista de gestión del equipo: varias OLT sólo aceptan")
    print("     administración desde direcciones IP declaradas de antemano.")
    print("  3. Revisar el firewall entre este servidor y la OLT.")
    if any(s.abierto for s in sondeos):
        print("\nLa web del equipo sí responde, así que llegar se llega: el problema")
        print("está en el servicio de CLI, no en el camino.")
    print(
        "\nMientras tanto, la lectura por SNMP sigue funcionando: 'descubrir',\n"
        "'sondear' y la interfaz web no dependen de la CLI."
    )


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

    credenciales = sub.add_parser(
        "credenciales",
        help="cambia las credenciales de una OLT (conserva lo que no se indique)",
    )
    credenciales.add_argument("olt_id", type=int)
    # Sin valores por defecto a propósito: lo que no se pasa, no se toca. Con
    # defaults, corregir la contraseña de la CLI pisaría la community SNMP.
    credenciales.add_argument("--usuario")
    credenciales.add_argument("--comunidad", help="community SNMP de lectura")
    credenciales.add_argument("--puerto-snmp", type=int)
    credenciales.add_argument("--puerto-telnet", type=int)
    credenciales.add_argument("--puerto-ssh", type=int)
    credenciales.add_argument(
        "--con-enable",
        action="store_true",
        help="pedir también la contraseña de 'enable' de la CLI",
    )
    credenciales.set_defaults(funcion=comando_credenciales)

    probar = sub.add_parser("probar", help="verifica la conexión con una OLT")
    probar.add_argument("olt_id", type=int)
    probar.set_defaults(funcion=comando_probar)

    sondear = sub.add_parser("sondear", help="valores crudos del equipo, para verificar")
    sondear.add_argument("olt_id", type=int)
    sondear.set_defaults(funcion=comando_sondear)

    capturar = sub.add_parser(
        "capturar",
        help="registra qué comandos entiende la CLI de la OLT (sólo lectura)",
    )
    capturar.add_argument("olt_id", type=int)
    capturar.add_argument(
        "--protocolo", default="telnet", choices=list(PROTOCOLOS_CLI), help="canal de la CLI"
    )
    capturar.add_argument("--salida", help="archivo donde guardar la captura")
    capturar.add_argument("--timeout", type=float, default=20.0, help="espera por comando, en s")
    capturar.add_argument(
        "--sin-ayuda",
        action="store_true",
        help="no pedir la ayuda en línea ('?') del equipo",
    )
    capturar.add_argument(
        "--traza",
        metavar="ARCHIVO",
        help="guardar la sesión cruda (todo lo enviado y recibido) para diagnóstico",
    )
    capturar.add_argument(
        "--usuario",
        help="probar con otro usuario, sólo para esta corrida (no se guarda)",
    )
    capturar.add_argument(
        "--preguntar-password",
        action="store_true",
        help="pedir la contraseña por teclado, sólo para esta corrida (no se guarda)",
    )
    capturar.add_argument(
        "--comando-extra",
        action="append",
        metavar="COMANDO",
        help="probar sólo estos comandos, en vez del catálogo (repetible; sólo lectura)",
    )
    capturar.set_defaults(funcion=comando_capturar)

    equipos = sub.add_parser(
        "cargar-equipos",
        help="da de alta o actualiza las OLT descritas en un archivo TOML",
    )
    equipos.add_argument(
        "archivo",
        nargs="?",
        default="equipos.toml",
        help="archivo de equipos (por defecto: equipos.toml)",
    )
    equipos.set_defaults(funcion=comando_cargar_equipos)

    inventario = sub.add_parser(
        "inventario-cli",
        help="completa el inventario con los seriales que sólo da la CLI (sólo lectura)",
    )
    inventario.add_argument("olt_id", type=int)
    inventario.add_argument(
        "--protocolo", default="ssh", choices=list(PROTOCOLOS_CLI), help="canal de la CLI"
    )
    inventario.add_argument("--timeout", type=float, default=60.0, help="espera, en segundos")
    inventario.add_argument("--traza", metavar="ARCHIVO", help="guardar la sesión cruda")
    inventario.add_argument(
        "--desde-archivo",
        metavar="ARCHIVO",
        help="leer la configuración de un archivo ya capturado, sin tocar el equipo",
    )
    inventario.set_defaults(funcion=comando_inventario_cli)

    explorar = sub.add_parser(
        "explorar-config",
        help="busca los comandos de GPON entrando a modo configuración (sin configurar nada)",
    )
    explorar.add_argument("olt_id", type=int)
    explorar.add_argument("--pon", default="0/1", help="puerto PON a explorar, p. ej. 0/1")
    explorar.add_argument(
        "--protocolo", default="ssh", choices=list(PROTOCOLOS_CLI), help="canal de la CLI"
    )
    explorar.add_argument("--timeout", type=float, default=30.0)
    explorar.add_argument("--salida", help="archivo donde guardar la exploración")
    explorar.add_argument("--traza", metavar="ARCHIVO", help="guardar la sesión cruda")
    explorar.add_argument("--si", action="store_true", help="no preguntar confirmación")
    explorar.set_defaults(funcion=comando_explorar_config)

    pendientes = sub.add_parser(
        "pendientes", help="ONU detectadas y sin autorizar, listas para dar de alta"
    )
    pendientes.add_argument("olt_id", type=int)
    pendientes.add_argument(
        "--serie", help="buscar un número de serie puntual, el que manda el técnico"
    )
    pendientes.add_argument(
        "--pon", action="append", metavar="PUERTO", help="limitar a estos puertos, p. ej. 0/1"
    )
    pendientes.add_argument(
        "--protocolo", default="ssh", choices=list(PROTOCOLOS_CLI), help="canal de la CLI"
    )
    pendientes.add_argument("--timeout", type=float, default=30.0)
    pendientes.add_argument("--traza", metavar="ARCHIVO", help="guardar la sesión cruda")
    pendientes.set_defaults(funcion=comando_pendientes)

    autorizar = sub.add_parser(
        "autorizar", help="da de alta una ONU que está esperando (simulado por defecto)"
    )
    autorizar.add_argument("olt_id", type=int)
    autorizar.add_argument("--serie", required=True, help="número de serie que mandó el técnico")
    autorizar.add_argument("--perfil", required=True, help="perfil de ONU, p. ej. V2802DAC")
    autorizar.add_argument("--pon", type=int, help="puerto PON; si no se indica, se busca")
    autorizar.add_argument(
        "--indice", type=int, help="índice de ONU; por defecto el más bajo libre"
    )
    autorizar.add_argument("--descripcion", default="", help="sin espacios")
    autorizar.add_argument("--dba", default="Internet", help="perfil DBA")
    autorizar.add_argument("--subida", default="", help="plan de subida, p. ej. 100M-Dom-UP")
    autorizar.add_argument("--bajada", default="", help="plan de bajada, p. ej. 100M-Dom-DOW")
    autorizar.add_argument("--vlan", type=int, default=1001)
    autorizar.add_argument(
        "--aplicar", action="store_true", help="enviar los comandos de verdad al equipo"
    )
    autorizar.add_argument(
        "--protocolo", default="ssh", choices=list(PROTOCOLOS_CLI), help="canal de la CLI"
    )
    autorizar.add_argument("--timeout", type=float, default=30.0)
    autorizar.add_argument("--traza", metavar="ARCHIVO", help="guardar la sesión cruda")
    autorizar.add_argument(
        "--usuario-operacion", default="", help="quién hace el alta, para la auditoría"
    )
    autorizar.set_defaults(funcion=comando_autorizar)

    probar_cli = sub.add_parser(
        "probar-cli", help="sondea los puertos de gestión de una OLT (no envía credenciales)"
    )
    probar_cli.add_argument("olt_id", type=int)
    probar_cli.add_argument("--timeout", type=float, default=3.0, help="espera por puerto, en s")
    probar_cli.set_defaults(funcion=comando_probar_cli)

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

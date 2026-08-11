"""Exploración de los modos de la CLI.

Este servicio entra a modo configuración, que es más de lo que hace el resto del
módulo. Lo que estos tests protegen es el límite exacto de ese permiso: sólo
navegar entre modos y leer, nunca configurar, y salir siempre.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import ErrorComando, ErrorValidacion
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.services.captura import es_solo_lectura
from gpon_module.services.exploracion import (
    CANDIDATOS_INTERFAZ_PON,
    MAXIMO_NODOS,
    MAXIMO_RAMAS,
    SUBARBOLES_A_RECORRER,
    VALOR_DE_PRUEBA,
    ServicioExploracion,
    _hay_que_bajar,
    es_navegacion,
    es_permitido,
    ramas_de,
)


class RepositorioOLTFalso:
    def obtener(self, _olt_id: int) -> OLT:
        return OLT(id=1, nombre="Belgrano", host="10.0.0.1", fabricante=Fabricante.VSOL)

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="eaguiar", password="x")


class TransporteFalso:
    def __init__(self, respuestas: dict[str, str] | None = None) -> None:
        self.respuestas = respuestas or {}
        self.ejecutados: list[str] = []
        self.ayudas: list[str] = []
        self.cerrado = False

    def abrir(self) -> None: ...

    def cerrar(self) -> None:
        self.cerrado = True

    def ejecutar(self, comando: str) -> str:
        self.ejecutados.append(comando)
        if comando in self.respuestas:
            return self.respuestas[comando]
        if comando.startswith("show "):
            raise ErrorComando("% Unknown command", comando=comando)
        return ""

    def ayuda(self, prefijo: str = "") -> str:
        self.ayudas.append(prefijo)
        return f"opciones de '{prefijo}'"


@pytest.fixture
def armar():
    def _armar(transporte: TransporteFalso) -> ServicioExploracion:
        return ServicioExploracion(
            RepositorioOLTFalso(),
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )

    return _armar


class TestPermisos:
    @pytest.mark.parametrize(
        "comando",
        ["configure terminal", "interface gpon 0/1", "interface gpon 1/16", "exit", "end", "quit"],
    )
    def test_la_navegacion_permitida(self, comando: str) -> None:
        assert es_navegacion(comando)

    @pytest.mark.parametrize(
        "comando",
        [
            "onu add 1 profile V2802GW sn GPON002E64F8",
            "no onu auto-learn",
            "interface gigabitethernet 0/1",
            "interface gpon",
            "write memory",
            "configure",
        ],
    )
    def test_todo_lo_que_configura_queda_afuera(self, comando: str) -> None:
        assert not es_navegacion(comando)
        assert not es_permitido(comando)

    def test_los_candidatos_del_catalogo_son_todos_de_lectura(self) -> None:
        for comando, _ in CANDIDATOS_INTERFAZ_PON:
            assert es_permitido(comando), comando

    def test_un_puerto_pon_mal_escrito_se_rechaza_antes_de_conectarse(self, armar) -> None:
        transporte = TransporteFalso()
        with pytest.raises(ErrorValidacion, match="Puerto PON inválido"):
            armar(transporte).explorar(1, pon="0/1 ; reboot")
        assert transporte.ejecutados == []


class TestRecorrido:
    def test_entra_a_los_dos_modos_y_vuelve(self, armar) -> None:
        transporte = TransporteFalso()

        exploracion = armar(transporte).explorar(1, pon="0/3")

        assert transporte.ejecutados[0] == "configure terminal"
        assert "interface gpon 0/3" in transporte.ejecutados
        assert transporte.ejecutados[-1] == "end"
        assert exploracion.recorrido == (
            "exec",
            "configure terminal",
            "interface gpon 0/3",
            "end",
        )

    def test_solo_ejecuta_navegacion_y_lectura(self, armar) -> None:
        """El invariante entero del servicio, comprobado sobre lo que salió."""
        transporte = TransporteFalso()

        armar(transporte).explorar(1)

        for comando in transporte.ejecutados:
            assert es_permitido(comando), comando

    def test_vuelve_al_modo_exec_aunque_algo_falle(self, armar) -> None:
        """Dejar la sesión en modo configuración confunde a quien entre después."""

        class TransporteQueExplota(TransporteFalso):
            def ejecutar(self, comando: str) -> str:
                self.ejecutados.append(comando)
                if comando.startswith("show onu"):
                    raise RuntimeError("se cayó el equipo")
                return ""

        transporte = TransporteQueExplota()
        with pytest.raises(RuntimeError):
            armar(transporte).explorar(1)

        assert "end" in transporte.ejecutados
        assert transporte.cerrado

    def test_recoge_el_listado_de_onu_sin_autorizar(self, armar) -> None:
        autofind = "Index  Sn              State\n1      GPON002E64F8    Unknown"
        transporte = TransporteFalso({"show onu autofind": autofind})

        exploracion = armar(transporte).explorar(1)

        aceptado = next(s for s in exploracion.aceptados if s.comando == "show onu autofind")
        assert "GPON002E64F8" in aceptado.salida

    def test_el_texto_deja_constancia_de_lo_que_se_hizo(self, armar) -> None:
        transporte = TransporteFalso()

        texto = armar(transporte).explorar(1).a_texto()

        assert "No se" in texto and "configuración" in texto
        assert "exec → configure terminal" in texto


class TestDescensoPorLaAyuda:
    """Bajar un nivel solo, para no pedir una corrida por nivel.

    ``onu 1 pri ?`` contesta 34 opciones, pero para escribir un comando hace
    falta saber qué va después de cada una. El ``?`` no ejecuta nada, así que
    bajar no cambia lo que el servicio puede hacer: sólo cuántas preguntas hace
    en el mismo viaje.
    """

    #: La salida real de la OLT de Belgrano, recortada.
    AYUDA_PRI = (
        "onu 1 pri \n"
        "  acl                   Specify ONU acl.\n"
        "  save_config           Specify onu save configuration control.\n"
        "  wan_conn              Specify ONU wan connection.\n"
        "  wifi_ssid             Specify onu wifi ssid.\n"
    )

    def test_encuentra_las_ramas_por_las_que_se_puede_seguir(self) -> None:
        assert ramas_de(self.AYUDA_PRI) == ("acl", "save_config", "wan_conn", "wifi_ssid")

    def test_los_marcadores_de_valor_no_son_ramas(self) -> None:
        """``<1-128>`` no es algo por lo que se pueda seguir preguntando."""
        ayuda = (
            "onu \n"
            "  <1-128>     Specify onu list. 1,3,5-10,12,16 etc.\n"
            "  <onu_list>  Specify onu list.\n"
            "  <cr>        Just Press Enter to Execute command!\n"
            "  add         Add onu to this gpon interface\n"
        )

        assert ramas_de(ayuda) == ("add",)

    def test_no_repite_una_rama_que_aparece_dos_veces(self) -> None:
        ayuda = "x \n  add  Uno\n  add  Otra vez\n"

        assert ramas_de(ayuda) == ("add",)

    def test_hay_un_tope_de_ramas(self) -> None:
        """Un firmware con una ayuda enorme no puede volver esto media hora."""
        ayuda = "x \n" + "".join(f"  opcion{n}  Descripción\n" for n in range(200))

        assert len(ramas_de(ayuda)) == MAXIMO_RAMAS

    def test_una_linea_sin_descripcion_no_cuenta(self) -> None:
        """El eco del prefijo tipeado no es una opción."""
        assert ramas_de("onu 1 pri \n") == ()


class TestRangosNumericos:
    """``wifi_ssid <1-8>`` no es una rama, pero detrás está lo que interesa.

    Llenar el hueco con el extremo bajo es lo que permite llegar a los
    parámetros de cada SSID sin pedir otra corrida. El ``?`` no ejecuta nada,
    así que elegir un número no configura ninguna ONU.
    """

    def test_un_rango_solo_se_usa_como_rama(self) -> None:
        ayuda = "onu 1 pri wifi_ssid \n  <1-8>  Specify onu wifi ssid number.\n"

        assert ramas_de(ayuda) == ("1",)

    def test_si_hay_palabras_el_rango_no_se_usa(self) -> None:
        """Las palabras son el camino; el número llevaría a preguntar de más."""
        ayuda = (
            "onu \n"
            "  <1-128>     Specify onu list.\n"
            "  add         Add onu to this gpon interface\n"
        )

        assert ramas_de(ayuda) == ("add",)

    def test_los_marcadores_que_no_son_numeros_se_descartan(self) -> None:
        ayuda = (
            "onu 1 pri dhcp_server \n"
            "  <A.B.C.D>  Specify ONU LAN IP Address.\n"
            "  ipv6       Specify ONU DHCP Server ipv6.\n"
        )

        assert ramas_de(ayuda) == ("ipv6",)


class TestLecturaConShowAlFinal:
    """En esta CLI ``onu 1 pri wan_conn show`` lee, y no empieza con 'show'."""

    def test_se_admite_la_forma_exacta(self) -> None:
        assert es_solo_lectura("onu 1 pri wan_conn show")
        assert es_solo_lectura("onu 29 pri acl show")

    def test_no_se_afloja_la_regla_para_todo_lo_demas(self) -> None:
        """"Contiene show" dejaría pasar un factory_reset de un tipeo."""
        assert not es_solo_lectura("onu 1 pri factory_reset")
        assert not es_solo_lectura("onu 1 pri wan_conn add")
        assert not es_solo_lectura("onu 1 pri save_config")
        assert not es_solo_lectura("onu 1 pri wan_conn show add")

    def test_los_candidatos_de_lectura_pasan_el_filtro(self) -> None:
        """El invariante del servicio: nada que no sea navegación o lectura."""
        for comando, _ in CANDIDATOS_INTERFAZ_PON:
            assert es_permitido(comando), comando


class TestSubarboles:
    """Enumerar los nodos de un árbol que todavía no se conoce fue el error.

    La lista de prefijos exactos se quedó corta dos veces —primero no llegaba a
    ``wan_conn add``, después a ``wan_conn add route`` y a ``wifi_ssid 1
    name``— y cada vez costó una corrida contra el equipo con alguien
    esperando. Lo que sí se conoce es por dónde hay que entrar.
    """

    def test_se_baja_por_todo_lo_que_cuelgue_de_un_subarbol(self) -> None:
        assert _hay_que_bajar("onu 1 pri wan_conn ")
        assert _hay_que_bajar("onu 1 pri wan_conn add ")
        assert _hay_que_bajar("onu 1 pri wan_conn add route ")
        assert _hay_que_bajar("onu 1 pri wifi_ssid 1 name ")

    def test_el_prefijo_de_un_nivel_sigue_bajando_uno_solo(self) -> None:
        assert _hay_que_bajar("onu 1 pri ")
        # 'catv' cuelga de 'onu 1 pri' pero no de ningún subárbol declarado.
        assert not _hay_que_bajar("onu 1 pri catv ")

    def test_no_se_baja_por_lo_que_no_se_declaro(self) -> None:
        assert not _hay_que_bajar("onu 1 pri voip_timer ")
        assert not _hay_que_bajar("show ")

    def test_los_subarboles_declarados_cuelgan_de_pri(self) -> None:
        """Si alguno no cuelga, no se llega nunca: el padre no lo enumera."""
        for subarbol in SUBARBOLES_A_RECORRER:
            assert subarbol.startswith("onu 1 pri ")


#: Las 18 interfaces que ``bind`` ofrece en la OLT real.
INTERFACES = [f"lan{n}" for n in range(1, 9)] + [f"ssid{n}" for n in range(1, 11)]


def ayuda_simulada(prefijo: str) -> str:
    """Réplica del árbol de la OLT de Belgrano, con su trampa incluida.

    ``bind`` acepta una **lista repetida**: cada nivel ofrece las interfaces que
    todavía no se usaron. Eso no es un árbol, es una combinatoria, y es lo que
    se tragó una corrida entera contra el equipo.
    """
    if prefijo == "onu 1 pri ":
        ramas = ["wan_conn", "wan_adv", "wifi_ssid", "wifi_switch", "username", "catv"]
        return "".join(f"  {r}   Cosa.\n" for r in ramas)
    if prefijo.endswith(("wan_conn ", "wan_adv ")):
        return "  add   A.\n  commit  C.\n  show  S.\n  index  I.\n"
    if prefijo.endswith("add "):
        return "  bridge  B.\n  route  R.\n"
    if prefijo.endswith("index "):
        return "  <1-8>  Wan index number.\n"
    if prefijo.endswith("index 1 "):
        # Sólo 'wan_adv' ofrece 'bind'; 'wan_conn' no. Es la diferencia que
        # permite bajar más hondo en uno sin caer en la combinatoria del otro.
        comun = "  bridge  B.\n  delete  D.\n  route  R.\n  vlan  V.\n"
        return ("  bind  B.\n" + comun) if "wan_adv" in prefijo else comun
    if " bind " in prefijo:
        usadas = set(prefijo.split())
        return "".join(f"  {i}  Wan bind {i}.\n" for i in INTERFACES if i not in usadas)
    if prefijo.endswith("wifi_ssid "):
        return "  <1-8>  Specify onu wifi ssid number.\n"
    if prefijo.endswith("wifi_ssid 1 "):
        return "  name  Specify onu wifi ssid name.\n  disable  Disable.\n"
    if prefijo.endswith("wifi_switch "):
        return "  <1-2>  Specify device number.\n"
    return "  <cr>  Just Press Enter!\n"


def recorrer(raiz: str = "onu 1 pri ") -> list[str]:
    """Corre el mismo algoritmo del servicio sobre el árbol simulado."""
    from collections import deque

    pendientes, vistos, orden = deque([raiz]), set(), []
    while pendientes and len(vistos) < MAXIMO_NODOS:
        prefijo = pendientes.popleft()
        if prefijo in vistos:
            continue
        vistos.add(prefijo)
        orden.append(prefijo)
        if _hay_que_bajar(prefijo):
            pendientes.extend(f"{prefijo}{r} " for r in ramas_de(ayuda_simulada(prefijo)))
    return orden


class TestElPozoCombinatorio:
    """La corrida del 10/08 gastó las 150 preguntas sin llegar a lo buscado.

    ``wan_adv index 1 bind`` acepta listas repetidas de interfaces, así que el
    recorrido en profundidad se hundió ahí: 159 preguntas, todas del ``bind``, y
    ni una a ``wan_conn`` ni a ``wifi_ssid``. Costó una corrida contra el equipo
    con alguien esperando.
    """

    def test_llega_a_todo_lo_que_hace_falta(self) -> None:
        recorrido = recorrer()

        for necesario in (
            "onu 1 pri wan_conn add route ",
            "onu 1 pri wan_conn index 1 ",
            "onu 1 pri wifi_ssid 1 name ",
            "onu 1 pri wifi_switch 1 ",
        ):
            assert necesario in recorrido, necesario

    def test_no_se_hunde_en_la_combinatoria(self) -> None:
        recorrido = recorrer()

        assert len(recorrido) < MAXIMO_NODOS
        # A 'bind' se le pregunta —devuelve la lista de interfaces, que sirve—
        # pero no se sigue por cada combinación de ellas.
        binds = [p for p in recorrido if " bind " in p]
        assert binds, "se tiene que llegar a preguntar por 'bind' una vez"
        assert all(p.endswith("bind ") for p in binds), binds

    def test_lo_ancho_se_pregunta_antes_que_lo_hondo(self) -> None:
        """El orden en que se pide es el orden en que se pierde si algo corta."""
        recorrido = recorrer()
        profundidades = [len(p.split()) for p in recorrido]

        assert profundidades == sorted(profundidades)

    def test_el_tope_de_profundidad_corta_donde_tiene_que_cortar(self) -> None:
        """A 'bind' se llega y se le pregunta; de ahí para abajo, no."""
        assert _hay_que_bajar("onu 1 pri wan_adv index 1 ")
        assert not _hay_que_bajar("onu 1 pri wan_adv index 1 bind ")
        assert not _hay_que_bajar("onu 1 pri wan_adv index 1 bind lan1 ")

    def test_la_profundidad_alcanza_para_los_comandos_reales(self) -> None:
        assert _hay_que_bajar("onu 1 pri wan_conn add ")
        assert _hay_que_bajar("onu 1 pri wifi_ssid 1 ")

    def test_el_wifi_baja_mas_que_la_wan(self) -> None:
        """Formas distintas, profundidades distintas.

        ``wan_conn`` se agota en tres niveles y esconde la combinatoria del
        ``bind``; el WiFi es una cadena larga de pares clave-valor que hay que
        recorrer entera para llegar a la clave.
        """
        assert SUBARBOLES_A_RECORRER["onu 1 pri wifi_ssid "] > (
            SUBARBOLES_A_RECORRER["onu 1 pri wan_conn "]
        )
        assert _hay_que_bajar("onu 1 pri wifi_ssid 1 name X auth_mode wpa2psk encrypt ")


class TestHuecosDeTexto:
    """``wifi_ssid 1 name ?`` contesta sólo ``<string>``.

    Lo que interesa —el modo de autenticación, el cifrado, la clave— está
    **después** del nombre. Sin rellenar ese hueco el recorrido se corta justo
    antes de lo único que faltaba.
    """

    def test_un_texto_libre_se_rellena_para_poder_seguir(self) -> None:
        ayuda = "  <string>  Specify onu wifi ssid name string, max length 32.\n"

        assert ramas_de(ayuda) == (VALOR_DE_PRUEBA,)

    def test_cr_no_se_rellena(self) -> None:
        """Ahí el comando termina de verdad: no hay nada más que preguntar."""
        assert ramas_de("  <cr>  Just Press Enter to Execute command!\n") == ()

    def test_una_ip_no_se_inventa(self) -> None:
        """Una dirección inventada no lleva a ningún lado."""
        assert ramas_de("  <A.B.C.D>  Specify ONU LAN IP Address.\n") == ()

    def test_si_hay_palabras_el_hueco_no_se_usa(self) -> None:
        """Rellenar igual sería preguntar de más por un camino ya enumerado."""
        assert ramas_de("  name  Nombre.\n  <string>  Texto.\n") == ("name",)

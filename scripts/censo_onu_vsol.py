#!/usr/bin/env python3
"""Censo de ONU por modelo y firmware, leyendo la OLT VSOL por SNMP.

Para qué existe: antes de decidir nada sobre TR-069 hay que saber **qué hay
instalado de verdad**. Cuántas ONU de cada modelo, con qué firmware, y en qué
PON. Ese dato hoy no está en ningún lado: `onu_senal` guarda serial y señal,
pero no modelo ni versión.

La buena noticia es que no hace falta tocar ni una ONU. `olt_poller.py` ya dejó
mapeada la rama de ONU de VSOL:

    1.3.6.1.4.1.37950.1.1.6.1.2.1.1.3   → serial, indexado por <pon>.<onu>

Eso es una TABLA SNMP. La columna 3 es el serial; las vecinas traen el resto de
los atributos de cada ONU. Cuáles exactamente **no se asume**: se descubren
mirando el equipo, que es justamente lo que hace el modo `--descubrir`.

Es de SÓLO LECTURA. Hace `snmpbulkwalk` y nada más: no escribe en la OLT, no
escribe en la base, y no modifica ninguna ONU.

Uso:

    # 1. Descubrir qué trae cada columna de la tabla de ONU
    python3 scripts/censo_onu_vsol.py --descubrir 192.168.10.247 [community]

    # 2. Con las columnas ya identificadas, censar la flota
    python3 scripts/censo_onu_vsol.py --censo 192.168.10.247 \\
            --col-modelo 5 --col-firmware 9 [--csv censo.csv]

Requiere net-snmp (`snmpbulkwalk`), igual que el poller.
"""
from __future__ import annotations

import argparse
import collections
import csv
import os
import re
import shutil
import subprocess
import sys

#: Tabla de ONU de VSOL. El índice de cada fila es <pon>.<onu>.
TABLA_ONU = "1.3.6.1.4.1.37950.1.1.6.1.2.1.1"

#: La columna 3 es serial: lo confirmó `olt_poller.py` con walks reales contra
#: una V1600G1 y una V1600G1B. Es el ancla para saber que estamos en la tabla
#: correcta antes de creerle nada al resto.
COL_SERIAL = 3

#: Hasta qué número de columna explorar. VSOL no publica el largo de la tabla;
#: 24 alcanza de sobra y evita un walk eterno si el equipo responde cualquier
#: cosa más allá del final.
MAX_COLUMNAS = 24

#: Techo de filas por columna. ERLAN tiene ~2.400 ONU de fibra; 4000 deja
#: margen y es el mismo tope que usa el poller para la óptica.
CAP_FILAS = 4000


def snmp_disponible() -> bool:
    return shutil.which("snmpbulkwalk") is not None


def bulkwalk(ip: str, community: str, oid: str, version: str = "2c",
             timeout: int = 60) -> list[str]:
    """Líneas crudas de un snmpbulkwalk. Lista vacía si el equipo no contesta."""
    cmd = ["snmpbulkwalk", "-On", "-v", version, "-c", community,
           "-t", "6", "-r", "1", "-Cr50", ip, oid]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []
    return [l for l in p.stdout.splitlines() if l.strip()][:CAP_FILAS]


def parsear_columna(lineas: list[str], base_oid: str) -> dict[str, str]:
    """Convierte la salida de snmpbulkwalk en {índice: valor}.

    El índice es lo que queda del OID después de la base — para esta tabla,
    `<pon>.<onu>`. Se separa en función aparte porque es la única lógica con
    riesgo real de equivocarse, y así se puede probar sin una OLT enfrente.
    """
    fuera: dict[str, str] = {}
    for linea in lineas:
        if "=" not in linea:
            continue
        oid_txt, valor = linea.split("=", 1)
        oid_txt = oid_txt.strip().lstrip(".")
        base = base_oid.strip().lstrip(".")
        if not oid_txt.startswith(base + "."):
            continue
        indice = oid_txt[len(base) + 1:]
        valor = valor.strip()
        if "No Such" in valor or "No more" in valor:
            continue
        # snmpbulkwalk antepone el tipo: 'STRING: "V2802GW"', 'INTEGER: 3'
        if ":" in valor:
            valor = valor.split(":", 1)[1]
        fuera[indice] = valor.strip().strip('"')
    return fuera


def parece_version(valor: str) -> bool:
    """¿El valor tiene pinta de ser una versión de firmware?

    No decide nada por sí solo: sirve para ordenar las columnas candidatas y
    que la persona que mira el informe encuentre rápido la correcta.
    """
    v = valor.strip()
    return bool(re.search(r"\bV?\d+\.\d+", v)) or bool(re.match(r"^[A-Z]+-V?\d", v))


def parece_modelo(valor: str) -> bool:
    """¿Tiene forma de nombre de modelo VSOL?

    Cubre V2802DAC y V2802GW (las ONU de ERLAN) y también V1600G1 / V1600G1B
    (las OLT), porque algunas columnas de la tabla repiten el modelo del
    chasis y conviene reconocerlo para no confundirlo con el de la ONU.

    No choca con los seriales: esos empiezan con cuatro letras (VSOL…), no
    con una letra seguida de dígitos.
    """
    return bool(re.match(r"^V\d{3,4}[A-Z0-9]{0,5}$", valor.strip()))


# ── Modo descubrimiento ─────────────────────────────────────────────────────

def descubrir(ip: str, community: str, version: str) -> int:
    print(f"Explorando la tabla de ONU de {ip} …\n")

    anclas = parsear_columna(
        bulkwalk(ip, community, f"{TABLA_ONU}.{COL_SERIAL}", version),
        f"{TABLA_ONU}.{COL_SERIAL}")
    if not anclas:
        print(f"✗ La columna {COL_SERIAL} (serial) no devolvió nada.")
        print("  O la community es otra, o este equipo no expone la tabla de ONU.")
        print("  Verificá primero que funcione:  snmpget -v2c -c <community> "
              f"{ip} 1.3.6.1.2.1.1.1.0")
        return 2
    print(f"✓ Columna {COL_SERIAL} (serial): {len(anclas)} ONU. "
          f"Ejemplo: {list(anclas.items())[0]}\n")

    print(f"{'col':>4}  {'filas':>6}  {'distintos':>9}  ejemplos")
    print("─" * 78)
    candidatas_modelo, candidatas_firmware = [], []

    for col in range(1, MAX_COLUMNAS + 1):
        oid = f"{TABLA_ONU}.{col}"
        datos = parsear_columna(bulkwalk(ip, community, oid, version), oid)
        if not datos:
            continue
        valores = list(datos.values())
        distintos = sorted(set(valores))
        muestra = ", ".join(repr(v) for v in distintos[:3])
        if len(distintos) > 3:
            muestra += f"  (+{len(distintos) - 3} más)"
        marca = ""
        if col == COL_SERIAL:
            marca = "  ← serial (confirmado)"
        elif sum(parece_modelo(v) for v in valores) > len(valores) * 0.5:
            marca = "  ← ¿MODELO?"
            candidatas_modelo.append(col)
        elif sum(parece_version(v) for v in valores) > len(valores) * 0.5:
            marca = "  ← ¿FIRMWARE?"
            candidatas_firmware.append(col)
        print(f"{col:>4}  {len(datos):>6}  {len(distintos):>9}  {muestra}{marca}")

    print("\n" + "─" * 78)
    if candidatas_modelo or candidatas_firmware:
        print("Sugerencia (verificala contra la web de la OLT antes de usarla):")
        if candidatas_modelo:
            print(f"  --col-modelo {candidatas_modelo[0]}")
        if candidatas_firmware:
            print(f"  --col-firmware {candidatas_firmware[0]}")
        print("\nDespués corré el censo:")
        print(f"  python3 {sys.argv[0]} --censo {ip} "
              f"--col-modelo {candidatas_modelo[0] if candidatas_modelo else '?'} "
              f"--col-firmware {candidatas_firmware[0] if candidatas_firmware else '?'}")
    else:
        print("No se identificaron columnas de modelo ni firmware automáticamente.")
        print("Mirá la lista de arriba: la de modelo debería tener pocos valores")
        print("distintos (V2802DAC, V2802GW) y la de firmware unos pocos más.")

    print("\nOJO: la detección de arriba es una PISTA, no una confirmación.")
    print("Comparala contra lo que muestra la web de la OLT para dos o tres ONU")
    print("antes de darla por buena. Ya hubo un OID que parecía temperatura de")
    print("chasis y no lo era (ver la historia del bug en olt_poller.py).")
    return 0


# ── Modo censo ──────────────────────────────────────────────────────────────

def censo(ip: str, community: str, version: str,
          col_modelo: int, col_firmware: int, salida_csv: str | None) -> int:
    print(f"Censando ONU de {ip} …\n")

    def leer(col: int) -> dict[str, str]:
        oid = f"{TABLA_ONU}.{col}"
        return parsear_columna(bulkwalk(ip, community, oid, version), oid)

    seriales = leer(COL_SERIAL)
    modelos = leer(col_modelo)
    firmwares = leer(col_firmware)

    if not seriales:
        print("✗ No se pudo leer la tabla de ONU.")
        return 2

    filas = []
    for indice, serial in sorted(seriales.items()):
        pon, _, onu = indice.partition(".")
        filas.append({
            "pon": pon, "onu": onu, "serial": serial,
            "modelo": modelos.get(indice, ""),
            "firmware": firmwares.get(indice, ""),
        })

    combos = collections.Counter((f["modelo"], f["firmware"]) for f in filas)
    total = len(filas)

    print(f"{'modelo':<14} {'firmware':<16} {'ONU':>6}  {'%':>6}")
    print("─" * 48)
    for (modelo, firmware), n in combos.most_common():
        pct = n / total * 100
        print(f"{modelo or '(vacío)':<14} {firmware or '(vacío)':<16} {n:>6}  {pct:>5.1f}%")
    print("─" * 48)
    print(f"{'TOTAL':<31} {total:>6}")

    sin_dato = sum(1 for f in filas if not f["modelo"] or not f["firmware"])
    if sin_dato:
        print(f"\n⚠ {sin_dato} ONU sin modelo o sin firmware. Puede ser que estén")
        print("  caídas, o que esas columnas no sean las correctas.")

    if salida_csv:
        with open(salida_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["pon", "onu", "serial", "modelo", "firmware"])
            w.writeheader()
            w.writerows(filas)
        print(f"\n✓ Detalle por ONU escrito en {salida_csv}")

    print("\nPara qué sirve este número: define el alcance de la fase 0 de TR-069.")
    print("Cada combinación de modelo + firmware es un árbol de parámetros que")
    print("hay que verificar por separado. Ver docs/PLAN-TR069-GENIEACS.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--descubrir", metavar="IP", help="Explorar la tabla de ONU")
    ap.add_argument("--censo", metavar="IP", help="Censar por modelo y firmware")
    ap.add_argument("community", nargs="?", default="public")
    ap.add_argument("--version", default="2c", help="Versión SNMP (por defecto 2c)")
    ap.add_argument("--col-modelo", type=int, help="Columna del modelo")
    ap.add_argument("--col-firmware", type=int, help="Columna del firmware")
    ap.add_argument("--csv", help="Archivo donde escribir el detalle por ONU")
    a = ap.parse_args()

    if not snmp_disponible():
        print("✗ Falta snmpbulkwalk.  sudo apt install snmp")
        return 2

    if a.descubrir:
        return descubrir(a.descubrir, a.community, a.version)
    if a.censo:
        if not a.col_modelo or not a.col_firmware:
            print("✗ El censo necesita --col-modelo y --col-firmware.")
            print("  Corré primero:  --descubrir <IP>")
            return 2
        return censo(a.censo, a.community, a.version,
                     a.col_modelo, a.col_firmware, a.csv)

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

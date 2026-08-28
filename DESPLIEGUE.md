# Cómo instalar esta entrega

## Importante antes de empezar

**No copies el ZIP encima del proyecto con `cp -r` a secas.** El paquete trae
carpetas que no deben pisar las tuyas:

- `.git/` — es el repositorio de la copia de trabajo con la que se desarrolló.
  Si lo copiás encima, **te reemplaza tu historial de git**.
- `netadmin.db` no está en el ZIP (bien: tu base no se toca), pero `uploads/`
  tampoco: tus archivos subidos se conservan.

Los comandos de abajo excluyen todo eso.

---

## Pasos

```bash
cd ~/ERLAN/erlan_v6.1.8

# 0) Respaldo. Siempre.
sudo systemctl stop pucara

# `cp netadmin.db` NO alcanza: con SQLite en modo WAL, las transacciones
# recientes viven en netadmin.db-wal y una copia suelta del archivo principal
# las pierde. `.backup` consolida todo en un archivo consistente.
sqlite3 netadmin.db ".backup 'netadmin.db.bak-$(date +%F)'"

tar czf ~/pucara-respaldo-$(date +%F).tgz --exclude=.git --exclude=uploads .

# 1) Desempaquetar aparte
rm -rf /tmp/pucara_new && unzip -q ~/Downloads/pucara_entrega.zip -d /tmp/pucara_new

# 2) Copiar EXCLUYENDO .git, la base y los uploads
rsync -a --exclude='.git/' --exclude='*.db' --exclude='uploads/' \
      /tmp/pucara_new/ ~/ERLAN/erlan_v6.1.8/

# 3) Dependencias nuevas (SQLAlchemy y Alembic) DENTRO del venv del proyecto.
#    `pip` a secas falla con "externally-managed-environment" (PEP 668).
./venv/bin/pip install -r requirements.txt

# 4) Crear las tablas nuevas en tu base
./venv/bin/python -m alembic upgrade head

# 5) Carpeta de las imágenes de las notas
mkdir -p uploads/tareas

# 6) Arrancar
sudo systemctl start pucara
```

## Si el paso 3 falla con `externally-managed-environment`

Debian y Ubuntu modernos (PEP 668) no dejan instalar con `pip` sobre el Python
del sistema. **No uses `--break-system-packages`**: rompe el Python del que
depende el resto del sistema operativo.

Este proyecto **ya usa un entorno virtual**: el servicio arranca con
`venv/bin/python3` y varios cron también. Instalá ahí:

```bash
cd ~/ERLAN/erlan_v6.1.8
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m alembic upgrade head
```

Si el `venv/` no existiera, se crea con `python3 -m venv --system-site-packages venv`
(reutiliza flask, reportlab y psycopg2 en vez de duplicarlos) y después hay que
apuntar el `ExecStart` de `/etc/systemd/system/pucara.service` a
`venv/bin/python3`.

### Los cron tienen que usar el mismo intérprete

`olt_poller.py` ahora invoca el motor de incidentes. Si el cron lo corre con
`python3` a secas no va a encontrar SQLAlchemy: el sondeo de señales sigue
funcionando —la llamada está dentro de un `try`— pero **no se registra ningún
incidente**. Revisá `crontab -e` y usá la ruta completa del venv en las líneas
que toquen `olt_poller.py`.

## Verificar que quedó bien

```bash
# Las rutas nuevas tienen que estar registradas (deberían ser 296 en total)
./venv/bin/python -c "import app; print(len(list(app.app.url_map.iter_rules())))"

# Los catálogos de reclamos tienen que estar cargados
sqlite3 netadmin.db "SELECT COUNT(*) FROM reclamo_causas;"     # → 16
sqlite3 netadmin.db "SELECT COUNT(*) FROM reclamo_resoluciones;"  # → 18

# Y la suite completa en verde
./venv/bin/python -m pytest tests/ -q
```

En el navegador, **recargá con Ctrl+Shift+R**: el JavaScript se cachea y si no
forzás la recarga vas a seguir viendo la versión vieja aunque el servidor ya
tenga la nueva.

Después:

- Abrí la ficha de un cliente → tiene que aparecer la pestaña **📋 Reclamos**.
- **Clientes → Antigüedad y churn** es una pantalla nueva.
- **Configuración** tiene la tarjeta **📋 Catálogos de reclamos**.
- **Mis Tareas** acepta capturas con Ctrl+V.

## Si algo falla al arrancar

El registro de los módulos nuevos está dentro de un `try/except`: si falta una
dependencia, el sistema arranca igual y avisa por consola. Buscá el aviso:

```bash
sudo journalctl -u pucara -n 50 | grep -i "aviso"
```

Si aparece `Módulos v2 no cargados`, el paso 3 (`pip install`) no se completó.

## Vuelta atrás

```bash
sudo systemctl stop pucara
cd ~ && rm -rf ERLAN/erlan_v6.1.8 && mkdir -p ERLAN/erlan_v6.1.8
tar xzf ~/pucara-respaldo-AAAA-MM-DD.tgz -C ERLAN/erlan_v6.1.8
sudo systemctl start pucara
```

Las tablas nuevas quedan en la base pero no molestan; si querés sacarlas también,
`./venv/bin/python -m alembic downgrade base`.

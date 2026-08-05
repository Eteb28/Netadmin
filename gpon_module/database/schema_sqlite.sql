-- Esquema del módulo GPON — SQLite
--
-- Base propia, sin reutilizar ninguna tabla de Pucará (requisito explícito).
-- Toda marca de tiempo se guarda en UTC, en formato ISO 8601.
--
-- El equivalente para PostgreSQL está en schema_postgres.sql y mantiene los
-- mismos nombres de tabla y columna, para que cambiar de motor no obligue a
-- tocar los repositorios.

PRAGMA foreign_keys = ON;

-- --------------------------------------------------------------------------
-- OLT
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS olts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre                  TEXT    NOT NULL,
    host                    TEXT    NOT NULL UNIQUE,
    fabricante              TEXT    NOT NULL,
    modelo                  TEXT    NOT NULL DEFAULT '',
    firmware                TEXT    NOT NULL DEFAULT '',
    numero_serie            TEXT    NOT NULL DEFAULT '',
    mac                     TEXT    NOT NULL DEFAULT '',
    descripcion             TEXT    NOT NULL DEFAULT '',
    estado                  TEXT    NOT NULL DEFAULT 'desconocido',
    activa                  INTEGER NOT NULL DEFAULT 1,
    cantidad_pon            INTEGER NOT NULL DEFAULT 0,
    cantidad_onus           INTEGER NOT NULL DEFAULT 0,
    uptime_segundos         INTEGER,
    ultima_sincronizacion   TEXT,
    creada_en               TEXT    NOT NULL,
    actualizada_en          TEXT    NOT NULL,

    -- Credenciales cifradas en reposo (mitiga R8). Nunca en texto plano: con
    -- estos datos se borran ONUs de clientes reales.
    usuario_cifrado             TEXT NOT NULL DEFAULT '',
    password_cifrado            TEXT NOT NULL DEFAULT '',
    password_enable_cifrado     TEXT NOT NULL DEFAULT '',
    comunidad_lectura_cifrada   TEXT NOT NULL DEFAULT '',
    comunidad_escritura_cifrada TEXT NOT NULL DEFAULT '',
    puerto_snmp             INTEGER NOT NULL DEFAULT 161,
    puerto_telnet           INTEGER NOT NULL DEFAULT 23,
    puerto_ssh              INTEGER NOT NULL DEFAULT 22
);

CREATE INDEX IF NOT EXISTS idx_olts_activa ON olts (activa);

-- --------------------------------------------------------------------------
-- Puertos PON
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS puertos_pon (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id                  INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    indice                  INTEGER NOT NULL,
    nombre                  TEXT    NOT NULL DEFAULT '',
    descripcion             TEXT    NOT NULL DEFAULT '',
    habilitado              INTEGER NOT NULL DEFAULT 1,
    operativo               INTEGER NOT NULL DEFAULT 1,
    cantidad_onus           INTEGER NOT NULL DEFAULT 0,
    cantidad_onus_en_linea  INTEGER NOT NULL DEFAULT 0,
    potencia_tx_dbm         REAL,
    temperatura_celsius     REAL,
    voltaje_voltios         REAL,
    corriente_ma            REAL,
    leido_en                TEXT,
    UNIQUE (olt_id, indice)
);

-- --------------------------------------------------------------------------
-- ONU
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS onus (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id              INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    pon                 INTEGER NOT NULL,
    onu_id              INTEGER NOT NULL,
    numero_serie        TEXT    NOT NULL DEFAULT '',
    nombre              TEXT    NOT NULL DEFAULT '',
    descripcion         TEXT    NOT NULL DEFAULT '',
    modelo              TEXT    NOT NULL DEFAULT '',
    fabricante_onu      TEXT    NOT NULL DEFAULT '',
    firmware            TEXT    NOT NULL DEFAULT '',
    estado              TEXT    NOT NULL DEFAULT 'desconocido',
    motivo_caida        TEXT    NOT NULL DEFAULT 'desconocido',
    modo_servicio       TEXT    NOT NULL DEFAULT 'desconocido',
    autorizada          INTEGER NOT NULL DEFAULT 1,
    distancia_metros    INTEGER,
    perfil_linea        TEXT    NOT NULL DEFAULT '',
    perfil_servicio     TEXT    NOT NULL DEFAULT '',
    vlan                INTEGER,
    ultima_subida       TEXT,
    ultima_bajada       TEXT,
    tiempo_en_estado    TEXT    NOT NULL DEFAULT '',
    primera_vez_vista   TEXT,
    ultima_vez_vista    TEXT,
    UNIQUE (olt_id, pon, onu_id)
);

-- El serial no es único a nivel global por diseño: una ONU puede migrar de OLT
-- y conviene poder ver el histórico. La búsqueda por serial sí necesita índice.
CREATE INDEX IF NOT EXISTS idx_onus_serie   ON onus (numero_serie);
CREATE INDEX IF NOT EXISTS idx_onus_olt_pon ON onus (olt_id, pon);
CREATE INDEX IF NOT EXISTS idx_onus_estado  ON onus (olt_id, estado);

-- --------------------------------------------------------------------------
-- Métricas (histórico con retención escalonada)
-- --------------------------------------------------------------------------
--
-- Con 473 ONU en una sola OLT y sondeo cada 5 minutos, una tabla plana llega a
-- ~50 millones de filas al año. Por eso la granularidad es parte de la clave:
-- 'fina' se depura a los 7 días, 'horaria' a los 90 y 'diaria' a los 2 años.

CREATE TABLE IF NOT EXISTS metricas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id          INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    entidad         TEXT    NOT NULL,          -- 'olt' | 'pon' | 'onu'
    entidad_id      INTEGER NOT NULL,
    tipo            TEXT    NOT NULL,
    valor           REAL    NOT NULL,
    granularidad    TEXT    NOT NULL DEFAULT 'fina',
    muestras        INTEGER NOT NULL DEFAULT 1,
    valor_minimo    REAL,
    valor_maximo    REAL,
    registrada_en   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metricas_serie
    ON metricas (entidad, entidad_id, tipo, granularidad, registrada_en);
CREATE INDEX IF NOT EXISTS idx_metricas_depuracion
    ON metricas (granularidad, registrada_en);

-- --------------------------------------------------------------------------
-- Perfiles y servicios
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS perfiles_dba (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id                      INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre                      TEXT    NOT NULL,
    identificador_equipo        TEXT    NOT NULL DEFAULT '',
    tipo                        TEXT    NOT NULL DEFAULT '',
    ancho_banda_fijo_kbps       INTEGER,
    ancho_banda_asegurado_kbps  INTEGER,
    ancho_banda_maximo_kbps     INTEGER,
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS perfiles_linea (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id                  INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre                  TEXT    NOT NULL,
    identificador_equipo    TEXT    NOT NULL DEFAULT '',
    perfil_dba              TEXT    NOT NULL DEFAULT '',
    cantidad_tcont          INTEGER NOT NULL DEFAULT 0,
    cantidad_gemport        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS perfiles_servicio (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id                  INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre                  TEXT    NOT NULL,
    identificador_equipo    TEXT    NOT NULL DEFAULT '',
    vlan                    INTEGER,
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS vlans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id      INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    vlan_id     INTEGER NOT NULL,
    nombre      TEXT    NOT NULL DEFAULT '',
    descripcion TEXT    NOT NULL DEFAULT '',
    UNIQUE (olt_id, vlan_id)
);

CREATE TABLE IF NOT EXISTS service_ports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id          INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    indice          INTEGER NOT NULL,
    pon             INTEGER,
    onu_id          INTEGER,
    gemport         INTEGER,
    vlan_usuario    INTEGER,
    vlan_servicio   INTEGER,
    perfil_trafico  TEXT NOT NULL DEFAULT '',
    UNIQUE (olt_id, indice)
);

-- --------------------------------------------------------------------------
-- Alarmas
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reglas_alarma (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo                        TEXT    NOT NULL,
    nombre                      TEXT    NOT NULL,
    severidad                   TEXT    NOT NULL DEFAULT 'advertencia',
    habilitada                  INTEGER NOT NULL DEFAULT 1,
    olt_id                      INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    umbral                      REAL,
    umbral_recuperacion         REAL,      -- histéresis: evita el parpadeo
    ocurrencias_para_disparar   INTEGER NOT NULL DEFAULT 1,
    silencio_minutos            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alarmas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    regla_id        INTEGER REFERENCES reglas_alarma (id) ON DELETE SET NULL,
    tipo            TEXT    NOT NULL,
    severidad       TEXT    NOT NULL,
    estado          TEXT    NOT NULL DEFAULT 'activa',
    olt_id          INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    entidad         TEXT    NOT NULL DEFAULT 'olt',
    entidad_id      INTEGER,
    mensaje         TEXT    NOT NULL DEFAULT '',
    valor           REAL,
    abierta_en      TEXT    NOT NULL,
    reconocida_en   TEXT,
    reconocida_por  TEXT    NOT NULL DEFAULT '',
    resuelta_en     TEXT
);

CREATE INDEX IF NOT EXISTS idx_alarmas_activas ON alarmas (estado, olt_id);
CREATE INDEX IF NOT EXISTS idx_alarmas_entidad ON alarmas (tipo, entidad, entidad_id, estado);

-- --------------------------------------------------------------------------
-- Eventos: el histórico del inventario
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eventos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            TEXT    NOT NULL,
    olt_id          INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    entidad         TEXT    NOT NULL DEFAULT 'onu',
    entidad_id      INTEGER,
    pon             INTEGER,
    onu_id          INTEGER,
    descripcion     TEXT    NOT NULL DEFAULT '',
    valor_anterior  TEXT    NOT NULL DEFAULT '',
    valor_nuevo     TEXT    NOT NULL DEFAULT '',
    ocurrido_en     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eventos_olt   ON eventos (olt_id, ocurrido_en);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo  ON eventos (tipo, ocurrido_en);

-- --------------------------------------------------------------------------
-- Auditoría de escrituras
-- --------------------------------------------------------------------------
--
-- Toda operación que toca una OLT queda registrada acá, incluidas las
-- simuladas. Es lo que permite responder después "quién hizo qué y qué
-- contestó el equipo". Las contraseñas nunca se guardan en 'comandos': los
-- drivers las enmascaran antes de devolver el resultado.

CREATE TABLE IF NOT EXISTS operaciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            TEXT    NOT NULL,
    olt_id          INTEGER REFERENCES olts (id) ON DELETE SET NULL,
    pon             INTEGER,
    onu_id          INTEGER,
    usuario         TEXT    NOT NULL DEFAULT 'sistema',
    ok              INTEGER NOT NULL DEFAULT 0,
    simulado        INTEGER NOT NULL DEFAULT 1,
    comandos        TEXT    NOT NULL DEFAULT '',
    salida          TEXT    NOT NULL DEFAULT '',
    error           TEXT    NOT NULL DEFAULT '',
    duracion_ms     INTEGER,
    ejecutada_en    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operaciones_olt ON operaciones (olt_id, ejecutada_en);

-- --------------------------------------------------------------------------
-- Sincronización
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sincronizaciones (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id              INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nivel               TEXT    NOT NULL DEFAULT 'rapido',
    resultado           TEXT    NOT NULL DEFAULT 'completa',
    onus_leidas         INTEGER NOT NULL DEFAULT 0,
    onus_esperadas      INTEGER,
    eventos_generados   INTEGER NOT NULL DEFAULT 0,
    detalle             TEXT    NOT NULL DEFAULT '',
    iniciada_en         TEXT    NOT NULL,
    finalizada_en       TEXT,
    duracion_ms         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sincronizaciones_olt ON sincronizaciones (olt_id, iniciada_en);

-- --------------------------------------------------------------------------
-- Respaldos de configuración
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS respaldos_configuracion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id          INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    contenido       TEXT    NOT NULL,
    formato         TEXT    NOT NULL DEFAULT 'running-config',
    hash_contenido  TEXT    NOT NULL DEFAULT '',
    tomado_en       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_respaldos_olt ON respaldos_configuracion (olt_id, tomado_en);

-- --------------------------------------------------------------------------
-- Usuarios de la interfaz web (Fase 3)
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS usuarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario         TEXT    NOT NULL UNIQUE,
    nombre          TEXT    NOT NULL DEFAULT '',
    hash_password   TEXT    NOT NULL,
    rol             TEXT    NOT NULL DEFAULT 'lectura',
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_en       TEXT    NOT NULL,
    ultimo_acceso   TEXT
);

-- --------------------------------------------------------------------------
-- Configuración interna del módulo
-- --------------------------------------------------------------------------
--
-- Guarda un verificador cifrado con GPON_CLAVE_CIFRADO. Si alguien cambia la
-- clave, las credenciales guardadas quedan ilegibles; sin este verificador el
-- módulo sólo se entera al intentar conectarse a una OLT, con un error que no
-- explica la causa. Con él, avisa al arrancar y dice exactamente qué pasó.

CREATE TABLE IF NOT EXISTS configuracion_modulo (
    clave       TEXT PRIMARY KEY,
    valor       TEXT NOT NULL,
    creada_en   TEXT NOT NULL
);

-- --------------------------------------------------------------------------
-- Versión del esquema
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS esquema_version (
    version     INTEGER NOT NULL,
    aplicada_en TEXT    NOT NULL
);

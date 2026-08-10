-- Esquema del módulo GPON — PostgreSQL
--
-- Equivalente exacto de schema_sqlite.sql: mismos nombres de tabla y columna,
-- para que cambiar de motor no obligue a tocar los repositorios.
--
-- PostgreSQL es el motor recomendado en producción por el volumen del
-- histórico (473 ONU por OLT cada 5 minutos). SQLite alcanza y sobra para
-- desarrollo, tests y una instalación chica.

-- --------------------------------------------------------------------------
-- OLT
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS olts (
    id                      SERIAL PRIMARY KEY,
    nombre                  TEXT    NOT NULL,
    host                    TEXT    NOT NULL UNIQUE,
    fabricante              TEXT    NOT NULL,
    modelo                  TEXT    NOT NULL DEFAULT '',
    firmware                TEXT    NOT NULL DEFAULT '',
    numero_serie            TEXT    NOT NULL DEFAULT '',
    mac                     TEXT    NOT NULL DEFAULT '',
    descripcion             TEXT    NOT NULL DEFAULT '',
    estado                  TEXT    NOT NULL DEFAULT 'desconocido',
    activa                  BOOLEAN NOT NULL DEFAULT TRUE,
    cantidad_pon            INTEGER NOT NULL DEFAULT 0,
    cantidad_onus           INTEGER NOT NULL DEFAULT 0,
    uptime_segundos         BIGINT,
    ultima_sincronizacion   TIMESTAMPTZ,
    creada_en               TIMESTAMPTZ NOT NULL,
    actualizada_en          TIMESTAMPTZ NOT NULL,

    -- Credenciales cifradas en reposo (mitiga R8).
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
    id                      SERIAL PRIMARY KEY,
    olt_id                  INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    indice                  INTEGER NOT NULL,
    nombre                  TEXT    NOT NULL DEFAULT '',
    descripcion             TEXT    NOT NULL DEFAULT '',
    habilitado              BOOLEAN NOT NULL DEFAULT TRUE,
    operativo               BOOLEAN NOT NULL DEFAULT TRUE,
    cantidad_onus           INTEGER NOT NULL DEFAULT 0,
    cantidad_onus_en_linea  INTEGER NOT NULL DEFAULT 0,
    potencia_tx_dbm         DOUBLE PRECISION,
    temperatura_celsius     DOUBLE PRECISION,
    voltaje_voltios         DOUBLE PRECISION,
    corriente_ma            DOUBLE PRECISION,
    leido_en                TIMESTAMPTZ,
    UNIQUE (olt_id, indice)
);

-- --------------------------------------------------------------------------
-- ONU
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS onus (
    id                  SERIAL PRIMARY KEY,
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
    autorizada          BOOLEAN NOT NULL DEFAULT TRUE,
    distancia_metros    INTEGER,
    perfil_linea        TEXT    NOT NULL DEFAULT '',
    perfil_servicio     TEXT    NOT NULL DEFAULT '',
    vlan                INTEGER,
    ultima_subida       TIMESTAMPTZ,
    ultima_bajada       TIMESTAMPTZ,
    tiempo_en_estado    TEXT    NOT NULL DEFAULT '',
    primera_vez_vista   TIMESTAMPTZ,
    ultima_vez_vista    TIMESTAMPTZ,
    UNIQUE (olt_id, pon, onu_id)
);

CREATE INDEX IF NOT EXISTS idx_onus_serie   ON onus (numero_serie);
CREATE INDEX IF NOT EXISTS idx_onus_olt_pon ON onus (olt_id, pon);
CREATE INDEX IF NOT EXISTS idx_onus_estado  ON onus (olt_id, estado);

-- --------------------------------------------------------------------------
-- Métricas (histórico con retención escalonada)
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS metricas (
    id              BIGSERIAL PRIMARY KEY,
    olt_id          INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    entidad         TEXT    NOT NULL,
    entidad_id      INTEGER NOT NULL,
    tipo            TEXT    NOT NULL,
    valor           DOUBLE PRECISION NOT NULL,
    granularidad    TEXT    NOT NULL DEFAULT 'fina',
    muestras        INTEGER NOT NULL DEFAULT 1,
    valor_minimo    DOUBLE PRECISION,
    valor_maximo    DOUBLE PRECISION,
    registrada_en   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metricas_serie
    ON metricas (entidad, entidad_id, tipo, granularidad, registrada_en);
CREATE INDEX IF NOT EXISTS idx_metricas_depuracion
    ON metricas (granularidad, registrada_en);

-- Nota para la Fase 4: si el volumen lo justifica, 'metricas' es candidata
-- natural a particionado por rango sobre registrada_en, o a TimescaleDB. El
-- esquema ya está preparado: la granularidad es una columna, no una tabla.

-- --------------------------------------------------------------------------
-- Perfiles y servicios
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS perfiles_dba (
    id                          SERIAL PRIMARY KEY,
    olt_id                      INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre                      TEXT    NOT NULL,
    identificador_equipo        TEXT    NOT NULL DEFAULT '',
    tipo                        TEXT    NOT NULL DEFAULT '',
    ancho_banda_fijo_kbps       INTEGER,
    ancho_banda_asegurado_kbps  INTEGER,
    ancho_banda_maximo_kbps     INTEGER,
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS perfiles_trafico (
    id                   SERIAL PRIMARY KEY,
    olt_id               INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre               TEXT    NOT NULL,
    identificador_equipo TEXT    NOT NULL DEFAULT '',
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS perfiles_linea (
    id                      SERIAL PRIMARY KEY,
    olt_id                  INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre                  TEXT    NOT NULL,
    identificador_equipo    TEXT    NOT NULL DEFAULT '',
    perfil_dba              TEXT    NOT NULL DEFAULT '',
    cantidad_tcont          INTEGER NOT NULL DEFAULT 0,
    cantidad_gemport        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS perfiles_servicio (
    id                      SERIAL PRIMARY KEY,
    olt_id                  INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nombre                  TEXT    NOT NULL,
    identificador_equipo    TEXT    NOT NULL DEFAULT '',
    vlan                    INTEGER,
    UNIQUE (olt_id, nombre)
);

CREATE TABLE IF NOT EXISTS vlans (
    id          SERIAL PRIMARY KEY,
    olt_id      INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    vlan_id     INTEGER NOT NULL,
    nombre      TEXT    NOT NULL DEFAULT '',
    descripcion TEXT    NOT NULL DEFAULT '',
    UNIQUE (olt_id, vlan_id)
);

CREATE TABLE IF NOT EXISTS service_ports (
    id              SERIAL PRIMARY KEY,
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
    id                          SERIAL PRIMARY KEY,
    tipo                        TEXT    NOT NULL,
    nombre                      TEXT    NOT NULL,
    severidad                   TEXT    NOT NULL DEFAULT 'advertencia',
    habilitada                  BOOLEAN NOT NULL DEFAULT TRUE,
    olt_id                      INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    umbral                      DOUBLE PRECISION,
    umbral_recuperacion         DOUBLE PRECISION,
    ocurrencias_para_disparar   INTEGER NOT NULL DEFAULT 1,
    silencio_minutos            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alarmas (
    id              SERIAL PRIMARY KEY,
    regla_id        INTEGER REFERENCES reglas_alarma (id) ON DELETE SET NULL,
    tipo            TEXT    NOT NULL,
    severidad       TEXT    NOT NULL,
    estado          TEXT    NOT NULL DEFAULT 'activa',
    olt_id          INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    entidad         TEXT    NOT NULL DEFAULT 'olt',
    entidad_id      INTEGER,
    mensaje         TEXT    NOT NULL DEFAULT '',
    valor           DOUBLE PRECISION,
    abierta_en      TIMESTAMPTZ NOT NULL,
    reconocida_en   TIMESTAMPTZ,
    reconocida_por  TEXT    NOT NULL DEFAULT '',
    resuelta_en     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alarmas_activas ON alarmas (estado, olt_id);
CREATE INDEX IF NOT EXISTS idx_alarmas_entidad ON alarmas (tipo, entidad, entidad_id, estado);

-- --------------------------------------------------------------------------
-- Eventos
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eventos (
    id              BIGSERIAL PRIMARY KEY,
    tipo            TEXT    NOT NULL,
    olt_id          INTEGER REFERENCES olts (id) ON DELETE CASCADE,
    entidad         TEXT    NOT NULL DEFAULT 'onu',
    entidad_id      INTEGER,
    pon             INTEGER,
    onu_id          INTEGER,
    descripcion     TEXT    NOT NULL DEFAULT '',
    valor_anterior  TEXT    NOT NULL DEFAULT '',
    valor_nuevo     TEXT    NOT NULL DEFAULT '',
    ocurrido_en     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eventos_olt  ON eventos (olt_id, ocurrido_en);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON eventos (tipo, ocurrido_en);

-- --------------------------------------------------------------------------
-- Auditoría de escrituras
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS operaciones (
    id              BIGSERIAL PRIMARY KEY,
    tipo            TEXT    NOT NULL,
    olt_id          INTEGER REFERENCES olts (id) ON DELETE SET NULL,
    pon             INTEGER,
    onu_id          INTEGER,
    usuario         TEXT    NOT NULL DEFAULT 'sistema',
    ok              BOOLEAN NOT NULL DEFAULT FALSE,
    simulado        BOOLEAN NOT NULL DEFAULT TRUE,
    comandos        TEXT    NOT NULL DEFAULT '',
    salida          TEXT    NOT NULL DEFAULT '',
    error           TEXT    NOT NULL DEFAULT '',
    duracion_ms     INTEGER,
    ejecutada_en    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operaciones_olt ON operaciones (olt_id, ejecutada_en);

-- --------------------------------------------------------------------------
-- Sincronización
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sincronizaciones (
    id                  BIGSERIAL PRIMARY KEY,
    olt_id              INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    nivel               TEXT    NOT NULL DEFAULT 'rapido',
    resultado           TEXT    NOT NULL DEFAULT 'completa',
    onus_leidas         INTEGER NOT NULL DEFAULT 0,
    onus_esperadas      INTEGER,
    eventos_generados   INTEGER NOT NULL DEFAULT 0,
    detalle             TEXT    NOT NULL DEFAULT '',
    iniciada_en         TIMESTAMPTZ NOT NULL,
    finalizada_en       TIMESTAMPTZ,
    duracion_ms         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sincronizaciones_olt ON sincronizaciones (olt_id, iniciada_en);

-- --------------------------------------------------------------------------
-- Respaldos de configuración
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS respaldos_configuracion (
    id              BIGSERIAL PRIMARY KEY,
    olt_id          INTEGER NOT NULL REFERENCES olts (id) ON DELETE CASCADE,
    contenido       TEXT    NOT NULL,
    formato         TEXT    NOT NULL DEFAULT 'running-config',
    hash_contenido  TEXT    NOT NULL DEFAULT '',
    tomado_en       TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_respaldos_olt ON respaldos_configuracion (olt_id, tomado_en);

-- --------------------------------------------------------------------------
-- Usuarios de la interfaz web (Fase 3)
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    usuario         TEXT    NOT NULL UNIQUE,
    nombre          TEXT    NOT NULL DEFAULT '',
    hash_password   TEXT    NOT NULL,
    rol             TEXT    NOT NULL DEFAULT 'lectura',
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMPTZ NOT NULL,
    ultimo_acceso   TIMESTAMPTZ
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
    creada_en   TIMESTAMPTZ NOT NULL
);

-- --------------------------------------------------------------------------
-- Versión del esquema
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS esquema_version (
    version     INTEGER NOT NULL,
    aplicada_en TIMESTAMPTZ NOT NULL
);

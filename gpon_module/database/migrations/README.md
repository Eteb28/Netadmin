# Migraciones

Vacío mientras el esquema esté en la versión 1: `inicializar_esquema()` crea las
tablas y es idempotente.

A partir de la versión 2, cada cambio de estructura va acá como un archivo
`NNN-descripcion.sql`, y `esquema_version` registra hasta dónde se aplicó. Los
cambios de esquema tienen que poder aplicarse sobre una base con datos de
producción sin perder histórico.

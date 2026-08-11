# Salidas reales capturadas

Está vacío a propósito. Acá van las salidas **reales** de los equipos, una por
comando, organizadas por fabricante y modelo:

```
fixtures/
├── vsol/v1600g1b/
│   ├── show_version.txt
│   ├── show_running_config.txt
│   ├── listado_onu.txt
│   ├── listado_onu_con_caidas.txt
│   ├── perfiles.txt
│   ├── onu_sin_autorizar.txt
│   └── comando_invalido.txt
└── zte/c320/
```

Son la base de los tests de parseo, y valen más que cualquier documentación: un
parser escrito contra el manual funciona hasta que se enfrenta a un equipo de
verdad. Además convierten un cambio de versión de firmware en un test que falla,
en vez de en un incidente en producción.

Al capturarlas, **quitar toda dirección IP, serial de cliente y contraseña** que
no haga falta para el parseo.

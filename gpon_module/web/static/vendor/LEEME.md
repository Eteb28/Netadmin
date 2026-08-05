# Dependencias del navegador

Bootstrap 5.3.3 y Chart.js 4.4.1, servidos desde acá y **no desde un CDN**.

El motivo es operativo, no estético: un servidor de NOC suele estar en una VLAN
de gestión sin salida a internet. Con CDN, la interfaz se vería sin estilos y
sin gráficos justo en el lugar donde tiene que funcionar. Sirviéndolos local,
el módulo se instala y anda en una red aislada.

Actualizar (desde una máquina con acceso a npm):

    curl -O https://registry.npmjs.org/bootstrap/-/bootstrap-5.3.3.tgz
    curl -O https://registry.npmjs.org/chart.js/-/chart.js-4.4.1.tgz
    tar xzf bootstrap-5.3.3.tgz && cp package/dist/css/bootstrap.min.css .
    cp package/dist/js/bootstrap.bundle.min.js .
    tar xzf chart.js-4.4.1.tgz && cp package/dist/chart.umd.js chart.umd.min.js

Licencias: Bootstrap y Chart.js son MIT.

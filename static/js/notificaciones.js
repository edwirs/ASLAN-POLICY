/* Campana de notificaciones de la barra superior.
   Hoy el menú trae filas de ejemplo (clase .notif-ejemplo) y el contador en 7 (de ejemplo, fijo en base.html). Cuando haya notificaciones reales:

     AslanNotificaciones.render([
         {texto: 'Mapfre pide un código de verificación', hora: 'ahora', icono: 'fa-key', color: 'warning',
          url: '/policies/vehiculos/', urgente: true},
         {texto: 'Cotización completada · BWF282', hora: 'hace 5 min', icono: 'fa-circle-check', color: 'success', url: '...'}
     ]);

   - El contador cuenta las notificaciones; en 0 es gris y discreto, con alguna es rojo.
   - Las «urgentes» (las que exigen una acción del usuario) van primero y con un punto rojo.
   - Con alguna notificación pendiente la campana vibra un instante cada pocos segundos (se pausa al abrir el menú);
     si llegan más que antes, vibra de inmediato. */
var AslanNotificaciones = (function () {
    'use strict';

    var anterior = 0;

    function esc(texto) {
        var d = document.createElement('div');
        d.textContent = texto == null ? '' : String(texto);
        return d.innerHTML;
    }

    function contador(n) {
        var $c = document.getElementById('notifContador');
        var menu = document.getElementById('menuNotificaciones');
        if (!$c || !menu) { return; }
        $c.textContent = n > 99 ? '99+' : String(n);
        $c.setAttribute('data-n', n);
        $c.classList.toggle('notif-con-avisos', n > 0);
        menu.querySelector('.nav-link').setAttribute('aria-label', n ? 'Notificaciones: ' + n + ' pendientes' : 'Notificaciones');
        // Con algo pendiente la campana vibra (CSS .notif-vibra) hasta que no quede nada; si llega algo nuevo vibra de inmediato.
        var campana = menu.querySelector('.fa-bell');
        campana.classList.toggle('notif-vibra', n > 0);
        if (n > anterior) {
            campana.classList.remove('notif-vibra');
            void campana.offsetWidth;  // reinicia la animación para que vibre ya
            campana.classList.add('notif-vibra');
        }
        anterior = n;
    }

    function fila(n) {
        var tag = n.url ? 'a' : 'div';
        return '<' + tag + (n.url ? ' href="' + esc(n.url) + '"' : '') + ' class="dropdown-item' + (n.urgente ? ' notif-urgente' : '') + '">' +
            '<span class="notif-icono bg-' + esc(n.color || 'primary') + '"><i class="fas ' + esc(n.icono || 'fa-bell') + '"></i></span>' +
            '<span class="notif-texto">' + esc(n.texto) + '</span>' +
            (n.hora ? '<span class="notif-hora">' + esc(n.hora) + '</span>' : '') + '</' + tag + '>';
    }

    // Reemplaza las filas (y el contador) por las notificaciones reales. Las urgentes van primero.
    function render(lista) {
        var cont = document.querySelector('#menuNotificaciones .notif-lista');
        if (!cont) { return; }
        lista = (lista || []).slice().sort(function (a, b) { return (b.urgente ? 1 : 0) - (a.urgente ? 1 : 0); });
        cont.innerHTML = lista.length
            ? lista.map(fila).join('<div class="dropdown-divider"></div>')
            : '<div class="notif-vacio"><i class="far fa-circle-check"></i> No tienes notificaciones pendientes</div>';
        var cabecera = document.querySelector('#menuNotificaciones .dropdown-header');
        if (cabecera) { cabecera.textContent = lista.length ? 'Notificaciones (' + lista.length + ')' : 'Notificaciones'; }
        contador(lista.length);
    }

    // Estado inicial: el número que trae el HTML (hoy 7, de ejemplo) define el color y la vibración desde que carga la página.
    function iniciar() {
        var c = document.getElementById('notifContador');
        if (c) { contador(parseInt(c.getAttribute('data-n'), 10) || 0); }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', iniciar); } else { iniciar(); }

    return {render: render, contador: contador};
})();

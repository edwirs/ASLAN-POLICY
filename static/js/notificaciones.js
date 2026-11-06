/* Campana de notificaciones de la barra superior.

   Pide al servidor (data-url del <li id="menuNotificaciones">, ver core/policies/services/notificaciones.py) las 4 cosas
   más importantes de la oficina y las pinta. Se actualiza sola cada minuto (cada 20 s si hay algo urgente, p. ej. Mapfre
   esperando el código), al volver a la pestaña y al abrir el menú. Son estados, no mensajes: desaparecen solas cuando
   se resuelven.

   - El contador cuenta las notificaciones; en 0 se oculta, con alguna es rojo.
   - Las «urgentes» (exigen una acción ya) van primero, con una franja roja, y la campana vibra.
   - Si aparece una urgente nueva, además sale un aviso (toastr) aunque el menú esté cerrado. */
var AslanNotificaciones = (function () {
    'use strict';

    var anterior = 0, urgentesVistas = {}, temporizador = null, primera = true;

    function esc(texto) {
        var d = document.createElement('div');
        d.textContent = texto == null ? '' : String(texto);
        return d.innerHTML;
    }

    function contador(n, hayUrgente) {
        var $c = document.getElementById('notifContador');
        var menu = document.getElementById('menuNotificaciones');
        if (!$c || !menu) { return; }
        $c.textContent = n > 99 ? '99+' : String(n);
        $c.setAttribute('data-n', n);
        $c.hidden = n === 0;
        $c.classList.toggle('notif-con-avisos', n > 0);
        menu.querySelector('.nav-link').setAttribute('aria-label', n ? 'Notificaciones: ' + n + ' pendientes' : 'Notificaciones');
        // La campana vibra solo si hay algo urgente; si llega algo nuevo vibra de inmediato.
        var campana = menu.querySelector('.fa-bell');
        campana.classList.toggle('notif-vibra', !!hayUrgente);
        if (hayUrgente && n > anterior) {
            campana.classList.remove('notif-vibra');
            void campana.offsetWidth;  // reinicia la animación para que vibre ya
            campana.classList.add('notif-vibra');
        }
        anterior = n;
    }

    function fila(n) {
        var tag = n.url ? 'a' : 'div';
        return '<' + tag + (n.url ? ' href="' + esc(n.url) + '"' : '') + ' class="dropdown-item' + (n.urgente ? ' notif-urgente' : '') + '">' +
            '<span class="notif-icono notif-' + esc(n.color || 'primary') + '"><i class="fas ' + esc(n.icono || 'fa-bell') + '"></i></span>' +
            '<span class="notif-texto"><b>' + esc(n.texto) + '</b>' + (n.detalle ? '<small>' + esc(n.detalle) + '</small>' : '') + '</span>' +
            (n.hora ? '<span class="notif-hora">' + esc(n.hora) + '</span>' : '') + '</' + tag + '>';
    }

    function render(lista) {
        var cont = document.querySelector('#menuNotificaciones .notif-lista');
        if (!cont) { return; }
        lista = (lista || []).slice().sort(function (a, b) { return (b.urgente ? 1 : 0) - (a.urgente ? 1 : 0); });
        cont.innerHTML = lista.length
            ? lista.map(fila).join('<div class="dropdown-divider"></div>')
            : '<div class="notif-vacio"><i class="far fa-circle-check"></i> Todo al día: no hay nada pendiente</div>';
        var cabecera = document.querySelector('#menuNotificaciones .dropdown-header');
        if (cabecera) { cabecera.textContent = lista.length ? 'Notificaciones (' + lista.length + ')' : 'Notificaciones'; }
        var urgentes = lista.filter(function (n) { return n.urgente; });
        contador(lista.length, urgentes.length > 0);
        avisarNuevas(urgentes);
        return urgentes.length > 0;
    }

    // Aviso flotante solo para urgentes que no estaban antes (no en la primera carga de la página).
    function avisarNuevas(urgentes) {
        var ahora = {};
        urgentes.forEach(function (n) {
            var clave = n.tipo + '|' + n.texto;
            ahora[clave] = true;
            if (!primera && !urgentesVistas[clave] && window.toastr) {
                toastr.warning(esc(n.detalle || ''), esc(n.texto), {timeOut: 10000, closeButton: true,
                    onclick: n.url ? function () { location.href = n.url; } : null});
            }
        });
        urgentesVistas = ahora;
        primera = false;
    }

    function programar(hayUrgente) {
        clearTimeout(temporizador);
        temporizador = setTimeout(cargar, hayUrgente ? 20000 : 60000);
    }

    function cargar() {
        var menu = document.getElementById('menuNotificaciones');
        var url = menu && menu.getAttribute('data-url');
        if (!url) { return; }
        fetch(url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (datos) { programar(datos ? render(datos.notificaciones) : false); })
            .catch(function () { programar(false); });
    }

    function iniciar() {
        var menu = document.getElementById('menuNotificaciones');
        if (!menu) { return; }
        cargar();
        menu.addEventListener('show.bs.dropdown', cargar);
        document.addEventListener('visibilitychange', function () { if (!document.hidden) { cargar(); } });
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', iniciar); } else { iniciar(); }

    return {render: render, recargar: cargar};
})();

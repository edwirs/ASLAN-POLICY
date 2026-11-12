/* Resalta en el menú lateral la opción de la página actual y deja abierto su grupo.
   Gana el enlace cuya ruta es el prefijo más largo de la dirección actual: así /pos/client/add/ marca «Clientes» y
   /policies/vehiculos/registrados/ marca «Vehículos registrados» y no «Solicitudes registradas». */
(function () {
    var menu = document.querySelector('.main-sidebar .nav-sidebar');
    if (!menu) return;
    var ruta = window.location.pathname;
    var mejor = null, largo = 0;
    menu.querySelectorAll('a.nav-link[href]').forEach(function (a) {
        var href = a.getAttribute('href');
        if (!href || href === '#') return;
        var p = a.pathname;
        if (!p.endsWith('/')) p += '/';
        var actual = ruta.endsWith('/') ? ruta : ruta + '/';
        if (actual.indexOf(p) === 0 && p.length > largo) { mejor = a; largo = p.length; }
    });
    if (!mejor) return;
    mejor.classList.add('active');
    mejor.setAttribute('aria-current', 'page');
    var li = mejor.closest('.nav-treeview');
    while (li) {
        var grupo = li.closest('.nav-item');
        if (!grupo) break;
        grupo.classList.add('menu-open', 'tiene-activo');
        li = grupo.parentElement.closest('.nav-treeview');
    }
})();

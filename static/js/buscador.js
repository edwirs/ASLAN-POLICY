// Buscador global de la barra superior: placa, cédula, nombre del cliente o número de póliza.
// Enter abre el primer resultado; ↑/↓ cambian de resultado; «/» enfoca el buscador desde cualquier pantalla.
var Etapa = {
    iconos: {
        sin_cotizar: 'fa-circle', cotizando: 'fa-spinner fa-spin', sin_valores: 'fa-circle-exclamation', esperando: 'fa-hourglass-half',
        no_compro: 'fa-circle-xmark', con_poliza: 'fa-shield-halved', por_renovar: 'fa-bell', vencida: 'fa-triangle-exclamation', inactivo: 'fa-ban'
    },
    esc: function (texto) {
        return String(texto == null ? '' : texto).replace(/[&<>"']/g, function (c) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
        });
    },
    // Etiqueta de la etapa; con `conDetalle` agrega debajo el detalle (aseguradora, días…).
    chip: function (etapa, conDetalle) {
        if (!etapa) { return ''; }
        var html = '<span class="etapa etapa-' + etapa.color + '" title="' + Etapa.esc(etapa.ayuda || '') + '"><i class="fa-solid ' +
            (Etapa.iconos[etapa.id] || 'fa-circle') + '"></i> ' + Etapa.esc(etapa.nombre) + '</span>';
        if (conDetalle && etapa.detalle) {
            html += '<span class="etapa-detalle">' + Etapa.esc(etapa.detalle) + '</span>';
        }
        return html;
    }
};

$(function () {
    var $input = $('#buscadorGlobal');
    if (!$input.length) { return; }
    var $caja = $input.closest('.buscador-global'), $res = $('#buscadorResultados');
    var url = $input.data('url'), espera = null, peticion = null, activo = -1;

    function cerrar() { $res.prop('hidden', true); activo = -1; $caja.removeClass('abierto'); }

    function pintar(resultados, q) {
        if (!resultados.length) {
            $res.html('<div class="bg-vacio">Sin resultados para «' + Etapa.esc(q) + '».</div>').prop('hidden', false);
            return;
        }
        $res.html(resultados.map(function (r) {
            var cliente = '<b>' + Etapa.esc(r.cliente) + '</b> <small>' + Etapa.esc(r.documento) + (r.celular ? ' · ' + Etapa.esc(r.celular) : '') +
                (r.numero_poliza ? ' · Póliza Nº ' + Etapa.esc(r.numero_poliza) : '') + '</small>';
            return '<div class="bg-item" data-url="' + Etapa.esc(r.enlaces[0].url) + '"><div class="bg-fila"><div><span class="bg-placa">' + Etapa.esc(r.placa) +
                '</span><span class="bg-vehiculo">' + Etapa.esc(r.vehiculo) + '</span></div>' + Etapa.chip(r.etapa) + '</div>' +
                '<div class="bg-cliente">' + cliente + (r.etapa.detalle ? '<br><small>' + Etapa.esc(r.etapa.detalle) + '</small>' : '') + '</div>' +
                '<div class="bg-enlaces">' + r.enlaces.map(function (e) {
                    return '<a href="' + Etapa.esc(e.url) + '"><i class="fa-solid ' + e.icono + '"></i> ' + Etapa.esc(e.texto) + '</a>';
                }).join('') + '</div></div>';
        }).join('')).prop('hidden', false);
        activo = 0;
        marcar();
    }

    function marcar() {
        $res.find('.bg-item').removeClass('activo').eq(activo).addClass('activo');
    }

    function buscar() {
        var q = $.trim($input.val());
        if (q.length < 2) { cerrar(); return; }
        if (peticion) { peticion.abort(); }
        peticion = $.getJSON(url, {q: q}).done(function (data) { pintar(data.resultados || [], q); });
    }

    $input.on('input', function () {
        clearTimeout(espera);
        espera = setTimeout(buscar, 250);
    });
    $input.on('focus', function () {
        $caja.addClass('abierto');
        if ($res.children().length && $.trim($input.val()).length >= 2) { $res.prop('hidden', false); }
    });
    $input.on('keydown', function (e) {
        var $items = $res.find('.bg-item');
        if (e.key === 'ArrowDown' && $items.length) { activo = Math.min(activo + 1, $items.length - 1); marcar(); e.preventDefault(); }
        else if (e.key === 'ArrowUp' && $items.length) { activo = Math.max(activo - 1, 0); marcar(); e.preventDefault(); }
        else if (e.key === 'Enter') {
            e.preventDefault();
            var destino = $items.eq(Math.max(activo, 0)).data('url');
            if (destino) { location.href = destino; } else { buscar(); }
        } else if (e.key === 'Escape') { cerrar(); $input.blur(); }
    });
    // Clic en la tarjeta = primer enlace (ficha del vehículo); los botones de abajo llevan a su módulo.
    $res.on('click', '.bg-item', function (e) {
        if (!$(e.target).closest('a').length) { location.href = $(this).data('url'); }
    });
    // En el celular el buscador es un ícono: al tocarlo se despliega.
    $caja.find('.bg-caja').on('click', function () { $input.trigger('focus'); });
    $(document).on('click', function (e) {
        if (!$(e.target).closest('.buscador-global').length) { cerrar(); }
    });
    $(document).on('keydown', function (e) {
        if (e.key === '/' && !$(e.target).is('input, textarea, select, [contenteditable]')) {
            e.preventDefault();
            $input.trigger('focus').select();
        }
    });
});

// Las listas aceptan ?buscar=PLACA (desde el buscador o un enlace): lo ponen en la búsqueda de la tabla al cargar.
function busquedaInicial() {
    return (new URLSearchParams(location.search).get('buscar') || '').trim();
}

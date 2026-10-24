var vehiculoRegistrado = {
    esc: function (texto) {
        return $('<div>').text(texto == null ? '' : String(texto)).html();
    },

    vacio: function (valor) {
        return valor ? vehiculoRegistrado.esc(valor) : '<span class="text-muted">—</span>';
    },

    dinero: function (valor) {
        return '$' + Number(valor).toLocaleString('es-CO', {maximumFractionDigits: 0});
    },

    fecha: function (texto) {
        if (!texto) {
            return null;
        }
        var p = String(texto).split('-');
        return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : texto;
    },

    // Un dato del detalle: etiqueta pequeña + valor. `copiable` agrega un botón para copiar el valor (chasis, motor…).
    dato: function (etiqueta, valor, opciones) {
        opciones = opciones || {};
        var tiene = valor !== null && valor !== undefined && valor !== '';
        var contenido = tiene ? vehiculoRegistrado.esc(valor) : '<span class="vr-sin-dato">Sin dato</span>';
        if (tiene && opciones.copiable) {
            contenido += ' <button type="button" class="vr-copiar" data-copiar="' + vehiculoRegistrado.esc(valor) +
                '" data-bs-toggle="tooltip" title="Copiar" aria-label="Copiar ' + vehiculoRegistrado.esc(etiqueta) + '">' +
                '<i class="fa-regular fa-copy"></i></button>';
        }
        return '<div class="vr-dato' + (opciones.ancho ? ' vr-dato-ancho' : '') + '"><dt>' + etiqueta + '</dt><dd' +
            (opciones.mono ? ' class="vr-mono"' : '') + '>' + contenido + '</dd></div>';
    },

    bloque: function (icono, titulo, datos, clase) {
        return '<section class="vr-bloque' + (clase ? ' ' + clase : '') + '"><h6 class="vr-bloque-titulo"><span class="vr-icono"><i class="fa-solid ' + icono +
            '"></i></span> ' + titulo + '</h6><dl class="vr-datos">' + datos.join('') + '</dl></section>';
    },

    // Panel que se despliega con el «+» de cada fila.
    detalle: function (v) {
        var d = vehiculoRegistrado.dato, f = vehiculoRegistrado.fecha;
        var titulo = [v.marca, v.clase || v.referencia].filter(Boolean).join(' ');
        var chips = '';
        if (v.es_cero_km) { chips += '<span class="vr-chip vr-chip-info"><i class="fa-solid fa-star"></i> 0 km</span>'; }
        if (v.servicio) { chips += '<span class="vr-chip">' + vehiculoRegistrado.esc(v.servicio) + '</span>'; }
        if (v.tipo_vehiculo) { chips += '<span class="vr-chip">' + vehiculoRegistrado.esc(v.tipo_vehiculo) + '</span>'; }
        if (v.combustible) { chips += '<span class="vr-chip"><i class="fa-solid fa-gas-pump"></i> ' + vehiculoRegistrado.esc(v.combustible) + '</span>'; }
        if (v.color) { chips += '<span class="vr-chip"><i class="fa-solid fa-palette"></i> ' + vehiculoRegistrado.esc(v.color) + '</span>'; }

        var cabecera = '<header class="vr-cabecera"><div><span class="vr-placa">' + vehiculoRegistrado.esc(v.placa) + '</span>' +
            '<span class="vr-titulo">' + (titulo ? vehiculoRegistrado.esc(titulo) : 'Vehículo') +
            (v.modelo ? ' <small>· ' + v.modelo + '</small>' : '') + '</span></div><div class="vr-chips">' + chips + '</div></header>';

        var vehiculo = vehiculoRegistrado.bloque('fa-car', 'Vehículo', [
            d('Marca', v.marca), d('Clase / línea', v.clase), d('Versión', v.referencia, {ancho: true}),
            d('Modelo', v.modelo), d('Tipo', v.tipo_vehiculo), d('Servicio', v.servicio),
            d('Color', v.color), d('Combustible', v.combustible),
        ]);
        var tecnica = vehiculoRegistrado.bloque('fa-fingerprint', 'Identificación técnica', [
            d('Motor', v.motor, {copiable: true, mono: true}), d('Chasis', v.chasis, {copiable: true, mono: true}),
            d('Serie', v.serie, {copiable: true, mono: true}), d('Código Fasecolda', v.codigo_fasecolda, {copiable: true, mono: true}),
        ]);
        var valores = vehiculoRegistrado.bloque('fa-sack-dollar', 'Valores', [
            d('Valor comercial', v.valor_comercial != null ? vehiculoRegistrado.dinero(v.valor_comercial) : null),
            d('Valor accesorios', v.valor_accesorios ? vehiculoRegistrado.dinero(v.valor_accesorios) : null),
        ], 'vr-bloque-compacto');
        var propietario = vehiculoRegistrado.bloque('fa-user', 'Propietario actual', [
            d('Nombre', v.propietario, {ancho: true}), d('Documento', v.documento), d('Teléfono', v.telefono),
            d('Correo', v.email, {ancho: true}), d('Dirección', v.direccion, {ancho: true}), d('Ciudad de residencia', v.ciudad_propietario),
        ]);
        var registro = vehiculoRegistrado.bloque('fa-clipboard-list', 'Registro y cotizaciones', [
            d('Zona de circulación', v.ciudad), d('Registrado', f(v.created_at)),
            d('Cotizaciones realizadas', v.cotizaciones || 0), d('Última cotización', f(v.ultima_cotizacion) || 'Aún no cotizado'),
        ], 'vr-bloque-compacto vr-bloque-ancho2');

        return '<div class="vr-detalle">' + cabecera + '<div class="vr-bloques">' + vehiculo + tecnica + propietario + valores + registro + '</div></div>';
    },

    list: function () {
        var tabla = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            responsive: {details: false},  // oculta columnas si no caben; todo el detalle va en el «+»
            order: [[1, 'asc']],
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: {'action': 'search'},
                dataSrc: ""
            },
            columns: [
                {data: null, orderable: false, searchable: false, defaultContent: '', responsivePriority: 1},
                {data: "placa", responsivePriority: 1},
                {data: "propietario", responsivePriority: 2},
                {data: "marca", responsivePriority: 3},
                {data: "clase", responsivePriority: 4},
                {data: "referencia", responsivePriority: 6},
                {data: "modelo", responsivePriority: 3},
                {data: "servicio", responsivePriority: 7},
                {data: "codigo_fasecolda", responsivePriority: 8},
                {data: "valor_comercial", responsivePriority: 5},
                {data: "ciudad", responsivePriority: 6},
                {data: "ultima_cotizacion", responsivePriority: 9},
                {data: "created_at", responsivePriority: 10},
            ],
            columnDefs: [
                {
                    targets: [0],
                    className: 'text-center vr-celda-control',
                    render: function () {
                        return '<button type="button" class="vr-mas" data-bs-toggle="tooltip" title="Ver todos los datos" ' +
                            'aria-label="Ver todos los datos del vehículo" aria-expanded="false"><i class="fa-solid fa-plus"></i></button>';
                    }
                },
                {
                    targets: [1],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data;
                        }
                        var cero = row.es_cero_km ? ' <span class="badge bg-info">0 km</span>' : '';
                        return '<b>' + vehiculoRegistrado.esc(data) + '</b>' + cero;
                    }
                },
                {
                    targets: [2],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + row.documento;
                        }
                        return '<div>' + vehiculoRegistrado.esc(data) + '</div><small class="text-muted">' + vehiculoRegistrado.esc(row.documento) + '</small>';
                    }
                },
                {
                    targets: [3, 4, 5, 7, 8, 10],
                    render: function (data, type) {
                        return type === 'display' ? vehiculoRegistrado.vacio(data) : (data || '');
                    }
                },
                {
                    targets: [6, 11],
                    class: 'text-center',
                    render: function (data, type) {
                        return type === 'display' ? vehiculoRegistrado.vacio(data) : (data || '');
                    }
                },
                {
                    targets: [9],
                    class: 'text-end',
                    render: function (data, type) {
                        if (data == null) {
                            return type === 'display' ? '<span class="text-muted">—</span>' : 0;
                        }
                        return type === 'display' ? vehiculoRegistrado.dinero(data) : data;
                    }
                },
                {targets: [12], class: 'text-center'},
            ],
            initComplete: function () {
                enable_tooltip();
            }
        });

        // El detalle debe abarcar TODAS las columnas visibles: con el plugin responsive el número cambia al
        // ocultar o mostrar columnas y DataTables no vuelve a calcularlo en las filas ya abiertas.
        var ajustarAncho = function () {
            var visibles = tabla.columns().visible().toArray().filter(Boolean).length;
            tabla.rows().every(function () {
                if (this.child.isShown()) {
                    $(this.child()).children('td').attr('colspan', visibles);
                }
            });
        };
        tabla.on('responsive-resize draw', ajustarAncho);

        // «+» / «−»: despliega o recoge el detalle completo del vehículo.
        $('#data tbody').on('click', 'button.vr-mas', function () {
            var $boton = $(this);
            var tooltip = bootstrap.Tooltip.getInstance(this);
            // dispose (no hide): un hide() durante la animación de entrada se ignora y el tooltip queda pegado. Se recrea abajo.
            if (tooltip) { tooltip.dispose(); }
            this.blur();
            var fila = tabla.row($boton.closest('tr'));
            if (fila.child.isShown()) {
                fila.child.hide();
                $boton.closest('tr').removeClass('vr-abierta');
                $boton.attr('aria-expanded', 'false').find('i').attr('class', 'fa-solid fa-plus');
                enable_tooltip();
            } else {
                fila.child(vehiculoRegistrado.detalle(fila.data()), 'vr-celda-detalle').show();
                ajustarAncho();
                $boton.closest('tr').addClass('vr-abierta');
                $boton.attr('aria-expanded', 'true').find('i').attr('class', 'fa-solid fa-minus');
                enable_tooltip();
            }
        });

        // Copiar un dato (motor, chasis, serie, Fasecolda).
        $('#data tbody').on('click', 'button.vr-copiar', function () {
            var valor = $(this).data('copiar');
            var listo = function () { toastr.success('Copiado: ' + valor); };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(String(valor)).then(listo, function () { toastr.error('No se pudo copiar'); });
            } else {
                var temporal = $('<textarea>').val(valor).appendTo('body').select();
                try { document.execCommand('copy'); listo(); } catch (e) { toastr.error('No se pudo copiar'); }
                temporal.remove();
            }
        });
    }
};

$(function () {
    vehiculoRegistrado.list();
});

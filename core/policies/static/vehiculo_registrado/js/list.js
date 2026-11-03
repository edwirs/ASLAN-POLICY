var vehiculoRegistrado = {
    filas: [],
    etapa: 'todas',
    ficha: {},

    pintarFiltros: function () {
        var conteo = {todas: vehiculoRegistrado.filas.length};
        vehiculoRegistrado.filas.forEach(function (v) { conteo[v.etapa.id] = (conteo[v.etapa.id] || 0) + 1; });
        $('#filtrosEtapa .btn').each(function () {
            var id = $(this).data('etapa'), n = conteo[id] || 0, activo = id === vehiculoRegistrado.etapa;
            $(this).find('.badge').text(n);
            $(this).toggleClass('vacio', n === 0 && !activo).toggleClass('btn-primary', activo).toggleClass('btn-outline-secondary', !activo);
        });
    },

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
        if (v.estado && v.estado.bloqueado) {
            chips += '<span class="vr-chip vr-chip-alerta"><i class="fa-solid fa-triangle-exclamation"></i> ' + vehiculoRegistrado.esc(v.estado.name) +
                (v.estado.fecha ? ' · ' + f(v.estado.fecha) : '') + '</span>';
        }
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
        var esEmpresa = /^NIT\b/.test(v.documento || '');  // el dueño de la empresa solo aplica a NIT
        var propietario = vehiculoRegistrado.bloque('fa-user', 'Propietario actual', [
            d('Nombre', v.propietario, {ancho: true}), d('Documento', v.documento), d('Celular', v.telefono), d('Otro celular', v.otro_celular),
            d('Correo', v.email, {ancho: true}), d('Otro correo', v.otro_correo, {ancho: true}), d('Dirección', v.direccion, {ancho: true}), d('Ciudad de residencia', v.ciudad_propietario),
        ].concat(esEmpresa ? [d('Dueño de la empresa', v.propietario_empresa_nombre, {ancho: true}),
            d('Cédula del dueño', v.propietario_empresa_documento)] : []));
        var registro = vehiculoRegistrado.bloque('fa-clipboard-list', 'Registro y cotizaciones', [
            d('Zona de circulación', v.ciudad), d('Registrado', f(v.created_at)),
            d('Cotizaciones realizadas', v.cotizaciones || 0), d('Última cotización', f(v.ultima_cotizacion) || 'Aún no cotizado'),
        ], 'vr-bloque-compacto vr-bloque-ancho2');

        var cargando = '<span class="vr-sin-dato"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</span>';
        var resumen = '<section class="vr-resumen" data-id="' + v.id + '">' + cargando + '</section>';
        var seguimiento = '<section class="vr-seguimiento" data-id="' + v.id + '"><div class="vr-seguimiento-cabecera"><h6 class="vr-bloque-titulo mb-0">' +
            '<span class="vr-icono"><i class="fa-solid fa-clock-rotate-left"></i></span> Seguimiento por año</h6></div>' +
            '<div class="vr-seguimiento-cuerpo">' + cargando + '</div></section>';
        return '<div class="vr-detalle">' + cabecera + resumen + '<div class="vr-bloques">' + vehiculo + tecnica + propietario + valores + registro + '</div>' + seguimiento + '</div>';
    },

    // Pólizas elegidas, cotizaciones por año (ciudad y propietario de ese año) y cambios de estado/propietario/ciudad.
    cargarSeguimiento: function (id, fila) {
        var $caja = $('.vr-seguimiento[data-id="' + id + '"] .vr-seguimiento-cuerpo');
        var $resumen = $('.vr-resumen[data-id="' + id + '"]');
        $.ajax({url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken}, data: {action: 'historial', id: id}})
            .done(function (r) {
                if (r.error) { $caja.html('<span class="text-danger">' + vehiculoRegistrado.esc(r.error) + '</span>'); $resumen.remove(); return; }
                $resumen.html(vehiculoRegistrado.resumen(r.resumen, fila));
                $caja.html(vehiculoRegistrado.seguimiento(r));
                enable_tooltip();
            })
            .fail(function () { $caja.html('<span class="text-danger">No se pudo cargar el seguimiento.</span>'); $resumen.remove(); });
    },

    // Ficha: en qué va el vehículo, su póliza vigente con las cuotas, la última cotización y qué se puede hacer.
    resumen: function (r, v) {
        var e = vehiculoRegistrado.esc, f = vehiculoRegistrado.fecha, din = vehiculoRegistrado.dinero;
        var ficha = vehiculoRegistrado.ficha;
        var etapa = '<div class="vr-resumen-etapa">' + Etapa.chip(r.etapa) + '<span>' + e(r.etapa.detalle || '') + '</span>' +
            '<small>' + e(r.etapa.ayuda) + '</small></div>';

        var poliza;
        if (r.poliza) {
            var p = r.poliza, d = p.dias_para_vencer;
            var vence = d <= 30 ? '<span class="vr-chip vr-chip-alerta"><i class="fa-solid fa-bell"></i> ' + (d === 0 ? 'vence hoy' : 'vence en ' + d + ' d') + '</span>'
                : '<span class="vr-chip vr-chip-info">faltan ' + d + ' días</span>';
            var cuotas = '';
            if (p.numero_cuotas > 1) {
                var pct = Math.round(100 * p.cuotas_pagadas / p.numero_cuotas);
                cuotas = '<div class="vr-cuotas"><div class="vr-cuotas-barra"><span style="width:' + pct + '%"></span></div>' +
                    '<small>' + p.cuotas_pagadas + ' de ' + p.numero_cuotas + ' cuotas pagadas' +
                    (p.proxima_cuota ? ' · próxima: <b>' + f(p.proxima_cuota.fecha) + '</b> por ' + din(p.proxima_cuota.valor) : '') + '</small>' +
                    (p.cuotas_atrasadas ? ' <span class="vr-chip vr-chip-peligro">' + p.cuotas_atrasadas + ' atrasada' + (p.cuotas_atrasadas > 1 ? 's' : '') + '</span>' : '') + '</div>';
            } else {
                cuotas = '<small class="vr-resumen-sub">De contado · pagar antes de ' + f(p.fecha_pago) + '</small>';
            }
            poliza = '<div class="vr-resumen-caja vr-resumen-ok"><h6><i class="fa-solid fa-shield-halved"></i> Póliza vigente</h6>' +
                '<div class="vr-resumen-titulo">' + e(p.aseguradora) + (p.plan ? ' <small>· ' + e(p.plan) + '</small>' : '') + '</div>' +
                '<div class="vr-resumen-sub">Vence el <b>' + f(p.fecha_renovacion) + '</b> ' + vence + '</div>' +
                '<div class="vr-resumen-sub">Prima <b>' + din(p.prima_total) + '</b> · ' + e(p.forma_pago) + (p.numero_poliza ? ' · Nº ' + e(p.numero_poliza) : '') + '</div>' +
                '<div class="vr-resumen-sub">Asesor: ' + e(p.asesor) + ' · Tomador: ' + e(p.tomador) + '</div>' + cuotas + '</div>';
        } else {
            var anterior = r.etapa.poliza ? 'Última: ' + e(r.etapa.poliza.aseguradora) + ', venció el ' + e(r.etapa.poliza.vence) : 'Nunca ha tomado póliza con nosotros.';
            poliza = '<div class="vr-resumen-caja"><h6><i class="fa-solid fa-shield-halved"></i> Póliza vigente</h6>' +
                '<div class="vr-resumen-titulo text-muted">Sin póliza vigente</div><div class="vr-resumen-sub">' + anterior + '</div></div>';
        }

        var ronda;
        if (r.ronda) {
            ronda = '<div class="vr-resumen-caja"><h6><i class="fa-solid fa-scale-balanced"></i> Última cotización</h6>' +
                '<div class="vr-resumen-titulo">' + f(r.ronda.fecha) + ' <small>· ' + e(r.ronda.ciudad) + '</small></div>' +
                '<div class="vr-resumen-sub">' + r.ronda.con_valor + ' aseguradora' + (r.ronda.con_valor !== 1 ? 's' : '') + ' con valor de ' + r.ronda.consultadas + ' consultada' + (r.ronda.consultadas !== 1 ? 's' : '') + '</div>' +
                (r.ronda.mejor ? '<div class="vr-resumen-sub">Más económica: <b>' + e(r.ronda.mejor.aseguradora) + '</b> por <b>' + din(r.ronda.mejor.valor) + '</b></div>' : '') + '</div>';
        } else {
            ronda = '<div class="vr-resumen-caja"><h6><i class="fa-solid fa-scale-balanced"></i> Última cotización</h6><div class="vr-resumen-titulo text-muted">Aún no cotizado</div></div>';
        }

        var acciones = [];
        if (ficha.cotizar && !(v.estado && v.estado.bloqueado)) {
            acciones.push('<a class="btn btn-sm btn-primary rounded-pill" href="' + ficha.cotizar + '?placa=' + encodeURIComponent(v.placa) + '"><i class="fa-solid fa-plus"></i> Nueva cotización</a>');
        }
        if (ficha.solicitudes) {
            acciones.push('<a class="btn btn-sm btn-outline-primary rounded-pill" href="' + ficha.solicitudes + '?buscar=' + encodeURIComponent(v.placa) + '"><i class="fa-solid fa-list-check"></i> Ver en Solicitudes</a>');
        }
        if (ficha.polizas && r.etapa.poliza) {
            acciones.push('<a class="btn btn-sm btn-outline-primary rounded-pill" href="' + ficha.polizas + '?buscar=' + encodeURIComponent(v.placa) + '"><i class="fa-solid fa-file-shield"></i> Ver pólizas</a>');
        }
        if (vrPermisos.cambiarEstado) {
            acciones.push('<button type="button" class="btn btn-sm btn-outline-warning rounded-pill vr-btn-estado" data-id="' + v.id + '" data-placa="' + e(v.placa) + '">' +
                '<i class="fa-solid fa-car-burst"></i> Marcar vendido, siniestrado…</button>');
        }
        return etapa + '<div class="vr-resumen-grid">' + poliza + ronda + '</div>' + (acciones.length ? '<div class="vr-resumen-acciones">' + acciones.join('') + '</div>' : '');
    },

    seguimiento: function (r) {
        var e = vehiculoRegistrado.esc, f = vehiculoRegistrado.fecha, din = vehiculoRegistrado.dinero;
        var polizas = r.polizas.length ? '<div class="vr-tabla-caja"><table class="vr-tabla"><thead><tr><th>Vence</th><th>Aseguradora</th><th>Ciudad</th><th>Tomador</th>' +
            '<th>Asesor</th><th class="text-end">Prima</th><th>Pago</th></tr></thead><tbody>' +
            r.polizas.map(function (p) {
                var nombre = vrPermisos.verPolizas ? '<a href="/policies/polizas/' + p.id + '/editar/">' + e(p.aseguradora) + '</a>' : e(p.aseguradora);
                var chip = '';
                if (p.estado.id === 'cancelada') {
                    chip = '<span class="vr-chip">Cancelada</span>';
                } else if (p.dias_para_vencer < 0) {
                    chip = '<span class="vr-chip vr-chip-peligro">Vencida</span>';
                } else if (p.dias_para_vencer <= 30) {
                    chip = '<span class="vr-chip vr-chip-alerta"><i class="fa-solid fa-bell"></i> Renovar: ' + p.dias_para_vencer + ' d</span>';
                } else {
                    chip = '<span class="vr-chip vr-chip-info">Vigente</span>';
                }
                var detalle = [p.plan ? (/^plan\b/i.test(p.plan) ? '' : 'Plan ') + e(p.plan) : '', p.numero_poliza ? 'Nº ' + e(p.numero_poliza) : ''].filter(Boolean).join(' · ');
                return '<tr' + (p.estado.id === 'cancelada' ? ' class="vr-cancelada"' : '') + '>' +
                    '<td class="text-nowrap"><b>' + (f(p.fecha_renovacion) || '—') + '</b><div>' + chip + '</div></td>' +
                    '<td><b>' + nombre + '</b>' + (detalle ? '<small>' + detalle + '</small>' : '') + '</td>' +
                    '<td class="vr-col-texto">' + e(p.ciudad) + '</td>' +
                    '<td class="vr-col-nombre">' + e(p.tomador) + '<small>' + e(p.documento) + '</small></td>' +
                    '<td class="vr-col-texto">' + e(p.asesor) + '</td>' +
                    '<td class="text-end text-nowrap"><b>' + din(p.prima_total) + '</b></td>' +
                    '<td class="text-nowrap"><b>' + e(p.forma_pago) + '</b><small>' + (p.numero_cuotas > 1 ? '1ª cuota: ' : 'Pagar antes de: ') + (f(p.fecha_pago) || '—') + '</small></td></tr>';
            }).join('') + '</tbody></table></div>' : '<span class="vr-sin-dato">Todavía no ha elegido ninguna póliza.</span>';
        var cotizaciones = r.cotizaciones.length ? '<div class="vr-tabla-caja"><table class="vr-tabla"><thead><tr><th>Año</th><th>Ciudad de circulación</th><th>Propietario</th>' +
            '<th class="text-center">Aseguradoras</th></tr></thead><tbody>' +
            r.cotizaciones.map(function (c) {
                return '<tr><td><b>' + c.anio + '</b></td><td class="vr-col-texto">' + c.ciudades.map(e).join(', ') + '</td><td class="vr-col-nombre">' + c.tomadores.map(e).join(', ') +
                    '</td><td class="text-center">' + c.aseguradoras + '</td></tr>';
            }).join('') + '</tbody></table></div>' : '<span class="vr-sin-dato">Sin cotizaciones.</span>';
        var eventos = r.eventos.length ? '<ul class="vr-eventos">' + r.eventos.map(function (ev) {
            return '<li><span class="vr-evento-fecha">' + e(ev.fecha) + '</span> <b>' + e(ev.tipo_display) + ':</b> ' + e(ev.anterior || '—') +
                ' <i class="fa-solid fa-arrow-right"></i> ' + e(ev.nuevo) + (ev.nota ? ' <small class="text-muted">(' + e(ev.nota) + ')</small>' : '') +
                (ev.usuario ? ' <small class="text-muted">· ' + e(ev.usuario) + '</small>' : '') + '</li>';
        }).join('') + '</ul>' : '<span class="vr-sin-dato">Sin cambios registrados.</span>';
        return '<div class="vr-seguimiento-grid"><div><h6 class="vr-sub">Pólizas elegidas</h6>' + polizas + '</div>' +
            '<div><h6 class="vr-sub">Cotizaciones por año</h6>' + cotizaciones + '</div>' +
            '<div><h6 class="vr-sub">Cambios de estado, propietario y ciudad</h6>' + eventos + '</div></div>';
    },

    list: function () {
        var tabla = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            responsive: {details: false},  // oculta columnas si no caben; todo el detalle va en el «+»
            order: [[1, 'asc']],
            search: {search: busquedaInicial()},
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: {'action': 'search'},
                dataSrc: function (json) {
                    vehiculoRegistrado.filas = json;
                    vehiculoRegistrado.pintarFiltros();
                    return json;
                }
            },
            columns: [
                {data: null, orderable: false, searchable: false, defaultContent: '', responsivePriority: 1},
                {data: "placa", responsivePriority: 1},
                {data: "propietario", responsivePriority: 2},
                {data: "etapa", responsivePriority: 2},
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
                        var estado = row.estado && row.estado.bloqueado ? '<br><span class="badge bg-warning text-dark">' + vehiculoRegistrado.esc(row.estado.name) + '</span>' : '';
                        return '<b>' + vehiculoRegistrado.esc(data) + '</b>' + cero + estado;
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
                    targets: [3],
                    render: function (data, type) {
                        return type === 'display' ? Etapa.chip(data, true) : data.nombre + ' ' + (data.detalle || '');
                    }
                },
                {
                    targets: [4, 5, 6, 8, 9, 11],
                    render: function (data, type) {
                        return type === 'display' ? vehiculoRegistrado.vacio(data) : (data || '');
                    }
                },
                {
                    targets: [7, 12],
                    class: 'text-center',
                    render: function (data, type) {
                        return type === 'display' ? vehiculoRegistrado.vacio(data) : (data || '');
                    }
                },
                {
                    targets: [10],
                    class: 'text-end',
                    render: function (data, type) {
                        if (data == null) {
                            return type === 'display' ? '<span class="text-muted">—</span>' : 0;
                        }
                        return type === 'display' ? vehiculoRegistrado.dinero(data) : data;
                    }
                },
                {targets: [13], class: 'text-center'},
            ],
            initComplete: function () {
                enable_tooltip();
                // Desde el buscador global (?abrir=ID): se abre la ficha de ese vehículo.
                var abrir = new URLSearchParams(location.search).get('abrir');
                if (abrir) {
                    tabla.rows().every(function () {
                        if (String(this.data().id) === abrir) {
                            var $boton = $(this.node()).find('button.vr-mas');
                            if ($boton.length) {
                                $boton.trigger('click');
                                this.node().scrollIntoView({behavior: 'smooth', block: 'start'});
                            }
                        }
                    });
                }
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
                vehiculoRegistrado.cargarSeguimiento(fila.data().id, fila.data());
                $boton.closest('tr').addClass('vr-abierta');
                $boton.attr('aria-expanded', 'true').find('i').attr('class', 'fa-solid fa-minus');
                enable_tooltip();
            }
        });

        // Marcar el vehículo como vendido, siniestrado… (para volver a cotizarlo se reactiva desde «Nueva solicitud»).
        var modalEstado = document.getElementById('modalEstado') ? new bootstrap.Modal(document.getElementById('modalEstado')) : null;
        var estadoId = null;
        $('#data tbody').on('click', 'button.vr-btn-estado', function () {
            estadoId = $(this).data('id');
            $('#estadoPlaca').text($(this).data('placa'));
            $('#estadoFecha').val(new Date().toISOString().slice(0, 10));
            $('#estadoNota').val('');
            modalEstado.show();
        });
        $('#btnGuardarEstado').on('click', function () {
            var $b = $(this).prop('disabled', true);
            $.ajax({url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
                    data: {action: 'estado', id: estadoId, estado: $('#estadoNuevo').val(), fecha: $('#estadoFecha').val(), nota: $('#estadoNota').val()}})
                .done(function (r) {
                    if (r.error) { return message_error(r.error); }
                    modalEstado.hide();
                    toastr.success('Estado actualizado: ' + r.name);
                    tabla.ajax.reload(null, false);
                })
                .fail(function () { message_error('No se pudo cambiar el estado'); })
                .always(function () { $b.prop('disabled', false); });
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

$.fn.dataTable.ext.search.push(function (settings, datos, indice) {
    if (settings.nTable.id !== 'data' || vehiculoRegistrado.etapa === 'todas') { return true; }
    var fila = settings.aoData[indice]._aData;
    return fila.etapa && fila.etapa.id === vehiculoRegistrado.etapa;
});

$(function () {
    toastr.options = {closeButton: true, progressBar: true, positionClass: 'toast-top-right', timeOut: 3500};
    try { vehiculoRegistrado.ficha = JSON.parse(document.getElementById('vrFicha').textContent); } catch (e) { vehiculoRegistrado.ficha = {}; }
    vehiculoRegistrado.etapa = new URLSearchParams(location.search).get('etapa') || 'todas';
    vehiculoRegistrado.list();

    $('#filtrosEtapa').on('click', '.btn', function () {
        vehiculoRegistrado.etapa = $(this).data('etapa');
        var params = new URLSearchParams(location.search);
        if (vehiculoRegistrado.etapa === 'todas') { params.delete('etapa'); } else { params.set('etapa', vehiculoRegistrado.etapa); }
        params.delete('abrir');
        history.replaceState(null, '', '?' + params.toString());
        vehiculoRegistrado.pintarFiltros();
        $('#data').DataTable().draw();
    });

});

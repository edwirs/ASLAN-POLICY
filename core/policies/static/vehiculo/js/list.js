var vehiculo = {
    recarga: null,
    etapa: 'todas',
    filas: [],

    fecha: function (iso) {
        if (!iso) { return null; }
        var p = String(iso).slice(0, 10).split('-');
        return p[2] + '/' + p[1] + '/' + p[0];
    },

    // Botones de filtro por etapa con su conteo (se recalculan cada vez que llegan los datos).
    pintarFiltros: function () {
        var conteo = {todas: vehiculo.filas.length};
        vehiculo.filas.forEach(function (v) { conteo[v.etapa.id] = (conteo[v.etapa.id] || 0) + 1; });
        $('#filtrosEtapa .btn').each(function () {
            var id = $(this).data('etapa'), n = conteo[id] || 0;
            $(this).find('.badge').text(n);
            $(this).toggleClass('vacio', n === 0 && id !== vehiculo.etapa);
            $(this).toggleClass('btn-primary', id === vehiculo.etapa).toggleClass('btn-outline-secondary', id !== vehiculo.etapa);
        });
    },

    list: function () {
        $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            responsive: true,
            order: [[4, 'desc']],
            search: {search: busquedaInicial()},
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search'
                },
                dataSrc: function (json) {
                    vehiculo.filas = json;
                    vehiculo.pintarFiltros();
                    return json;
                }
            },
            // Mismo diseño en computador y tableta: Placa, Cliente, Etapa y Acciones siempre a la vista; Ciudad, Última
            // cotización y Resultado por aseguradora siempre en el detalle del «+» ('none'). En el celular (menos de 1024 px)
            // Cliente y Etapa pasan al «+» si no caben, para que la tabla no se salga de la pantalla.
            columns: [
                {data: "placa"},
                {data: "tomador.names", className: 'min-tablet-l', responsivePriority: 3},
                {data: "zona_circulacion", className: 'none'},
                {data: "etapa", className: 'min-tablet-l', responsivePriority: 2},
                {data: "ultima_cotizacion"},
                {data: "proceso"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [0],
                    className: 'all',
                    render: function (data, type, row) {
                        var descripcion = [row.marca, row.clase, row.modelo].filter(Boolean).join(' ');
                        if (type !== 'display') {
                            return data + ' ' + descripcion;
                        }
                        var html = '<b class="sol-placa">' + Etapa.esc(data) + '</b>' + (row.es_cero_km ? ' <span class="badge bg-info">0 km</span>' : '');
                        return html + (descripcion ? '<small class="d-block text-muted">' + Etapa.esc(descripcion) + '</small>' : '');
                    }
                },
                {
                    targets: [1],
                    render: function (data, type, row) {
                        var t = row.tomador || {};
                        var doc = ((t.document_type && t.document_type.abbreviation) || '') + ' ' + (t.dni || '');
                        if (type !== 'display') {
                            return data + ' ' + (t.dni || '') + ' ' + (t.mobile || '') + ' ' + (t.phone || '') + ' ' + (t.email || '') + ' ' + (t.email_secundario || '');
                        }
                        var contacto = [t.mobile ? '<i class="fa-solid fa-mobile-screen"></i> ' + Etapa.esc(t.mobile) : '',
                            t.phone ? '<i class="fa-solid fa-mobile-screen"></i> ' + Etapa.esc(t.phone) : ''].filter(Boolean).join(' · ');
                        return '<div>' + Etapa.esc(data) + '</div><small class="text-muted d-block">' + Etapa.esc(doc.trim()) +
                            (contacto ? ' · ' + contacto : '') + '</small>' + (t.email ? '<small class="text-muted d-block">' + Etapa.esc([t.email, t.email_secundario].filter(Boolean).join(' · ')) + '</small>' : '');
                    }
                },
                {
                    targets: [3],
                    render: function (data, type) {
                        if (type !== 'display') {
                            return data.nombre + ' ' + (data.detalle || '');
                        }
                        return Etapa.chip(data, true);
                    }
                },
                {
                    targets: [4],
                    className: 'none text-nowrap',
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data || '';
                        }
                        var registrado = '<small class="text-muted d-block">Registrado: ' + vehiculo.fecha(row.created_at) + '</small>';
                        return (data ? '<b>' + vehiculo.fecha(data) + '</b>' : '<span class="text-muted">Sin cotizar</span>') + registrado;
                    }
                },
                {
                    targets: [5],
                    className: 'none',
                    orderable: false,
                    render: function (data, type, row) {
                        return vehiculo.chips(data);
                    }
                },
                {
                    targets: [6],
                    className: 'all text-center text-nowrap',
                    orderable: false,
                    render: function (data, type, row) {
                        // Solo icono; el texto va como tooltip (igual que en el módulo de Aseguradoras).
                        var atributos = 'data-id="' + data + '" data-placa="' + Etapa.esc(row.placa) + '" data-bs-toggle="tooltip"';
                        var botones = '<button type="button" class="btn btn-primary btn-sm rounded-pill btn-ver-proceso" ' + atributos +
                            ' title="Ver proceso" aria-label="Ver proceso"><i class="fa-solid fa-list-check"></i></button>';
                        if ($('#vehiculoPermisos').data('comparar') === 1) {
                            botones += ' <button type="button" class="btn btn-success btn-sm rounded-pill btn-comparativo" ' + atributos +
                                ' title="Realizar comparativo" aria-label="Realizar comparativo"><i class="fa-solid fa-scale-balanced"></i></button>';
                        }
                        var hayValores = (row.proceso && row.proceso.ok > 0) || row.tiene_valor_externo;
                        if ($('#vehiculoPermisos').data('poliza') === 1 && hayValores) {
                            // «El cliente eligió»: solo si ya hay algún valor cotizado para elegir.
                            botones += ' <button type="button" class="btn btn-info btn-sm rounded-pill btn-convertir" ' + atributos +
                                ' title="El cliente eligió: convertir en póliza" aria-label="Convertir en póliza"><i class="fa-solid fa-file-signature"></i></button>';
                            if (row.etapa.id === 'esperando') {
                                botones += ' <button type="button" class="btn btn-outline-secondary btn-sm rounded-pill btn-no-compro" ' + atributos +
                                    ' title="El cliente no compró" aria-label="El cliente no compró"><i class="fa-solid fa-user-xmark"></i></button>';
                            } else if (row.etapa.id === 'no_compro') {
                                botones += ' <button type="button" class="btn btn-outline-secondary btn-sm rounded-pill btn-deshacer-no-compro" ' + atributos +
                                    ' title="Deshacer «no compró» (vuelve a esperar decisión)" aria-label="Deshacer no compró"><i class="fa-solid fa-rotate-left"></i></button>';
                            }
                        }
                        return botones;
                    }
                },
            ],
            drawCallback: function (settings) {
                $('.tooltip').remove();
                enable_tooltip();
                // Mientras alguna solicitud siga cotizando, el listado se refresca solo.
                clearTimeout(vehiculo.recarga);
                var hayEnCurso = vehiculo.filas.some(function (v) { return v.proceso && v.proceso.curso > 0; });
                if (hayEnCurso) {
                    vehiculo.recarga = setTimeout(function () {
                        $('#data').DataTable().ajax.reload(null, false);
                    }, 6000);
                }
            },
            initComplete: function (settings, json) {
                enable_tooltip();
            }
        });
    },

    // Una pastilla por aseguradora con el estado de su última cotización.
    chips: function (proceso) {
        if (!proceso || proceso.estado === 'sin_cotizar') {
            return '<span class="badge bg-secondary">Sin cotizar</span>';
        }
        return '<div class="proceso-resumen">' + proceso.detalle.map(function (d) {
            var aviso = d.estado_bot === 'error' && (d.error_tipo === 'no_cotizable' || d.error_tipo === 'saturado' || d.error_tipo === 'clave_vencida');
            var clase = d.estado_bot === 'completado' ? 'ok' : (aviso ? 'aviso' : (['pendiente', 'en_proceso', 'esperando_confirmacion'].indexOf(d.estado_bot) !== -1 ? 'curso' : 'error'));
            var icono = clase === 'ok' ? 'fa-check' : (clase === 'aviso' ? (d.error_tipo === 'clave_vencida' ? 'fa-key' : 'fa-ban') : (clase === 'curso' ? 'fa-spinner fa-spin' : 'fa-xmark'));
            return '<span class="proceso-chip ' + clase + '"><i class="fa-solid ' + icono + '"></i> ' + Etapa.esc(d.aseguradora) + '</span>';
        }).join('') + '</div>';
    }
};

// ---------------------------------------------------------------------------
// «Ver proceso»: estado en vivo de la solicitud, con el detalle de cada
// aseguradora y el botón para reenviar solo a la que falló.
// ---------------------------------------------------------------------------
var procesoVista = {
    modal: null,
    vehiculoId: null,
    poll: null,

    abrir: function (id, placa) {
        this.vehiculoId = id;
        $('#procesoPlaca').text(placa);
        $('#procesoContenido').html('<div class="text-center text-muted py-4"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div>');
        this.modal.show();
        this.refrescar();
    },

    refrescar: function () {
        var self = this;
        clearTimeout(self.poll);
        var url = $('#modalProceso').data('proceso-url').replace('/0/', '/' + self.vehiculoId + '/');
        $.getJSON(url).done(function (data) {
            if (data.error) {
                $('#procesoContenido').html('<div class="alert alert-warning">' + ProcesoCotizacion.esc(data.error) + '</div>');
                return;
            }
            $('#procesoTomador').text(data.tomador);
            if (!data.cotizaciones.length) {
                $('#procesoContenido').html('<div class="alert alert-secondary">Esta solicitud aún no se ha enviado a ninguna aseguradora.</div>');
            } else {
                ProcesoCotizacion.render($('#procesoContenido').addClass('pc-lista'), data.cotizaciones);
            }
            if (data.en_curso && $('#modalProceso').hasClass('show')) {
                self.poll = setTimeout(function () { self.refrescar(); }, 3000);
            }
        });
    }
};

// Filtro por etapa: solo afecta la tabla de solicitudes.
$.fn.dataTable.ext.search.push(function (settings, datos, indice) {
    if (settings.nTable.id !== 'data' || vehiculo.etapa === 'todas') { return true; }
    var fila = settings.aoData[indice]._aData;
    return fila.etapa && fila.etapa.id === vehiculo.etapa;
});

$(function () {
    toastr.options = {closeButton: true, progressBar: true, positionClass: 'toast-top-right', timeOut: 3500};
    var inicial = new URLSearchParams(location.search).get('etapa');
    if (inicial) { vehiculo.etapa = inicial; }
    vehiculo.list();

    $('#filtrosEtapa').on('click', '.btn', function () {
        vehiculo.etapa = $(this).data('etapa');
        var params = new URLSearchParams(location.search);
        if (vehiculo.etapa === 'todas') { params.delete('etapa'); } else { params.set('etapa', vehiculo.etapa); }
        history.replaceState(null, '', '?' + params.toString());
        vehiculo.pintarFiltros();
        $('#data').DataTable().draw();
    });

    // «El cliente no compró»: se elige el motivo; la placa sigue activa y se puede volver a cotizar.
    var modalNoCompro = document.getElementById('modalNoCompro') ? new bootstrap.Modal(document.getElementById('modalNoCompro')) : null;
    var noComproId = null;
    $('#data').on('click', '.btn-no-compro', function () {
        $('.tooltip').remove();
        noComproId = $(this).data('id');
        $('#noComproPlaca').text($(this).data('placa'));
        $('#noComproMotivo').val('');
        $('#noComproNota').val('');
        modalNoCompro.show();
    });
    var decision = function (datos, mensaje) {
        return $.ajax({url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken}, data: datos})
            .done(function (r) {
                if (r.error) { return message_error(r.error); }
                if (modalNoCompro) { modalNoCompro.hide(); }
                toastr.success(mensaje);
                $('#data').DataTable().ajax.reload(null, false);
            })
            .fail(function () { message_error('No se pudo guardar la decisión del cliente'); });
    };
    $('#btnGuardarNoCompro').on('click', function () {
        if (!$('#noComproMotivo').val()) { return message_error('Elige el motivo por el que el cliente no compró.'); }
        var $b = $(this).prop('disabled', true);
        decision({action: 'no_compro', id: noComproId, motivo: $('#noComproMotivo').val(), nota: $('#noComproNota').val()}, 'Registrado: el cliente no compró')
            .always(function () { $b.prop('disabled', false); });
    });
    $('#data').on('click', '.btn-deshacer-no-compro', function () {
        $('.tooltip').remove();
        decision({action: 'deshacer_no_compro', id: $(this).data('id')}, 'Listo: vuelve a «Esperando decisión»');
    });

    procesoVista.modal = new bootstrap.Modal(document.getElementById('modalProceso'));

    $('#data').on('click', '.btn-ver-proceso', function () {
        procesoVista.abrir($(this).data('id'), $(this).data('placa'));
    });

    // «Realizar comparativo»: primero pregunta si se agregan valores de aseguradoras sin bot.
    $('#data').on('click', '.btn-comparativo', function () {
        var fila = $('#data').DataTable().row($(this).closest('tr')).data() || {};
        comparativoModales.abrirPregunta($(this).data('id'), $(this).data('placa'), fila.externas_faltantes,
            $('#vehiculoPermisos').data('registrar') === 1, fila.valor_manual_ids, fila.soat_valor, fila.soat_vencimiento);
    });

    // Convertir la solicitud en póliza: se elige la opción que escogió el cliente y listo.
    $('#data').on('click', '.btn-convertir', function () {
        $('.tooltip').remove();
        convertirPoliza.abrir($(this).data('id'), {alTerminar: function () { $('#data').DataTable().ajax.reload(null, false); }});
    });

    // Reenviar solo a la aseguradora que falló.
    $('#procesoContenido').on('click', '.pc-reintentar', function () {
        var $boton = $(this).prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin"></i> Reenviando...');
        ProcesoCotizacion.reintentar($('#modalProceso').data('reintentar-url'), csrftoken, $boton.data('id')).done(function (response) {
            if (response.error) {
                $boton.prop('disabled', false).html('<i class="fa-solid fa-rotate-right"></i> Reenviar');
                toastr.error(response.error);
                return;
            }
            procesoVista.refrescar();
        }).fail(function () {
            $boton.prop('disabled', false).html('<i class="fa-solid fa-rotate-right"></i> Reenviar');
            toastr.error('No se pudo reenviar la solicitud. Intenta nuevamente.');
        });
    });

    // Valor cotizado a mano desde «Ver proceso»: se refresca la tarjeta (y el listado al cerrar).
    $(document).on('valorManual:guardado', function () { procesoVista.refrescar(); });

    // Al cerrar el modal se detiene el seguimiento y se actualiza el listado.
    $('#modalProceso').on('hidden.bs.modal', function () {
        clearTimeout(procesoVista.poll);
        $('#data').DataTable().ajax.reload(null, false);
    });
});

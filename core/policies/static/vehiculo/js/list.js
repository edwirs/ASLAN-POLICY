var vehiculo = {
    recarga: null,

    list: function () {
        $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            order: [[5, 'desc']],
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {
                    'X-CSRFToken': csrftoken
                },
                data: {
                    'action': 'search'
                },
                dataSrc: ""
            },
            columns: [
                {data: "placa"},
                {data: "tomador.text"},
                {data: "tomador.dni"},
                {data: "zona_circulacion"},
                {data: "tomador.email"},
                {data: "created_at"},
                {data: "proceso"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [-2],
                    class: 'text-center',
                    orderable: false,
                    render: function (data, type, row) {
                        return vehiculo.chips(data);
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center text-nowrap',
                    orderable: false,
                    render: function (data, type, row) {
                        // Solo icono; el texto va como tooltip (igual que en el módulo de Aseguradoras).
                        var atributos = 'data-id="' + data + '" data-placa="' + ProcesoCotizacion.esc(row.placa) + '" data-bs-toggle="tooltip"';
                        var botones = '<button type="button" class="btn btn-primary btn-sm rounded-pill btn-ver-proceso" ' + atributos +
                            ' title="Ver proceso" aria-label="Ver proceso"><i class="fa-solid fa-list-check"></i></button>';
                        if ($('#vehiculoPermisos').data('comparar') === 1) {
                            botones += ' <button type="button" class="btn btn-success btn-sm rounded-pill btn-comparativo" ' + atributos +
                                ' title="Realizar comparativo" aria-label="Realizar comparativo"><i class="fa-solid fa-scale-balanced"></i></button>';
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
                var hayEnCurso = settings.json && settings.json.some(function (v) { return v.proceso && v.proceso.curso > 0; });
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
            return '<span class="proceso-chip ' + clase + '"><i class="fa-solid ' + icono + '"></i> ' + ProcesoCotizacion.esc(d.aseguradora) + '</span>';
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

$(function () {
    vehiculo.list();

    procesoVista.modal = new bootstrap.Modal(document.getElementById('modalProceso'));

    $('#data').on('click', '.btn-ver-proceso', function () {
        procesoVista.abrir($(this).data('id'), $(this).data('placa'));
    });

    // «Realizar comparativo»: primero pregunta si se agregan valores de aseguradoras sin bot.
    $('#data').on('click', '.btn-comparativo', function () {
        var fila = $('#data').DataTable().row($(this).closest('tr')).data() || {};
        comparativoModales.abrirPregunta($(this).data('id'), $(this).data('placa'), fila.externas_faltantes,
            $('#vehiculoPermisos').data('registrar') === 1);
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

    // Al cerrar el modal se detiene el seguimiento y se actualiza el listado.
    $('#modalProceso').on('hidden.bs.modal', function () {
        clearTimeout(procesoVista.poll);
        $('#data').DataTable().ajax.reload(null, false);
    });
});

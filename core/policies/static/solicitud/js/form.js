$(function () {

    $('select[name="zona_circulacion"]').select2({
        language: 'es',
        theme: 'bootstrap4',
        placeholder: 'Selecciona una ciudad',
        width: '100%'
    });

    $('select[name="document_type"]').select2({
        language: 'es',
        theme: 'bootstrap4',
        placeholder: 'Selecciona un tipo de documento',
        width: '100%'
    });

    var $form = $('#frmSolicitud');
    var $btn = $('#btnSubmitSolicitud');
    var $errors = $('#frmSolicitudErrors');
    var lookupUrl = $form.data('lookup-url');
    var cotizarUrl = $form.data('cotizar-url');
    var estadoUrl = $form.data('estado-url');
    var reintentarUrl = $form.data('reintentar-url');
    var defaultDocumentType = $('select[name="document_type"]').val();
    var pollCotizaciones = null;
    var aseguradorasSeleccionadas = [];
    var aseguradorasModal = new bootstrap.Modal(document.getElementById('modalAseguradoras'));
    var ceroKmModal = new bootstrap.Modal(document.getElementById('modalCeroKm'));
    var datosCeroKmModal = new bootstrap.Modal(document.getElementById('modalDatosCeroKm'));
    var seleccionPlacaModal = new bootstrap.Modal(document.getElementById('modalSeleccionPlaca'));

    toastr.options = {
        closeButton: true,
        progressBar: true,
        positionClass: 'toast-top-right',
        timeOut: 3000
    };

    $('input[name="placa"]').on('input', function () {
        $(this).val($(this).val().toUpperCase());
    });

    // Al salir de Cédula o Placa, se busca si ya existe el registro y, de
    // haberlo, se autocompleta el resto del formulario con lo guardado.
    $('input[name="dni"]').on('blur', function () {
        consultarRegistro('dni', $(this).val());
    });
    $('input[name="placa"]').on('blur', function () {
        consultarRegistro('placa', $(this).val());
    });

    function consultarRegistro(tipo, valor) {
        valor = (valor || '').trim();
        if (!valor || !lookupUrl) {
            return;
        }
        $.ajax({
            url: lookupUrl,
            type: 'GET',
            data: {tipo: tipo, valor: valor},
            dataType: 'json',
            success: function (response) {
                if (response.found) {
                    aplicarDatosEncontrados(response);
                }
            }
        });
    }

    function aplicarDatosEncontrados(data) {
        if (data.document_type_id) {
            $('select[name="document_type"]').val(data.document_type_id).trigger('change');
        }
        if (data.dni) {
            $('input[name="dni"]').val(data.dni);
        }
        if (data.placa) {
            $('input[name="placa"]').val(data.placa);
        }
        $('input[name="names"]').val(data.names || '');
        $('input[name="birthdate"]').val(data.birthdate || '');
        $('input[name="email"]').val(data.email || '');
        if (data.zona_circulacion_id) {
            $('select[name="zona_circulacion"]').val(data.zona_circulacion_id).trigger('change');
        }

        toastr.success('Datos cargados exitosamente');

        // El tomador tiene más de un vehículo registrado: se le pregunta
        // cuál placa cargar en vez de adivinar una.
        if (data.vehiculos && data.vehiculos.length > 1) {
            mostrarSeleccionPlaca(data.vehiculos);
        }
    }

    function mostrarSeleccionPlaca(vehiculos) {
        var $lista = $('#listaPlacasEncontradas').empty();
        vehiculos.forEach(function (v) {
            $('<button type="button" class="placa-choice-btn"></button>')
                .html('<span><i class="fa-solid fa-hashtag"></i>' + v.placa + '</span><span class="placa-choice-city">' + v.zona_circulacion + '</span>')
                .on('click', function () {
                    $('input[name="placa"]').val(v.placa);
                    $('select[name="zona_circulacion"]').val(v.zona_circulacion_id).trigger('change');
                    seleccionPlacaModal.hide();
                })
                .appendTo($lista);
        });
        seleccionPlacaModal.show();
    }

    // El formulario no se envía directo: primero se elige con qué aseguradoras
    // cotizar, luego se pregunta si es 0 km, y solo con esas respuestas se hace
    // el submit real.
    $form.on('submit', function (e) {
        e.preventDefault();
        actualizarContadorAseguradoras();
        aseguradorasModal.show();
    });

    function seleccionadas() {
        return $('#listaAseguradoras .aseg-switch:checked').map(function () { return $(this).val(); }).get();
    }

    function actualizarContadorAseguradoras() {
        var total = $('#listaAseguradoras .aseg-switch').length;
        var marcadas = seleccionadas().length;
        $('#asegContador').text(marcadas + ' de ' + total + ' seleccionadas');
        $('#asegToggleTodas').text(marcadas === total ? 'Quitar todas' : 'Seleccionar todas');
        $('#btnAsegContinuar').prop('disabled', marcadas === 0);
    }

    $('#listaAseguradoras').on('change', '.aseg-switch', actualizarContadorAseguradoras);

    $('#asegToggleTodas').on('click', function (e) {
        e.preventDefault();
        var todas = seleccionadas().length === $('#listaAseguradoras .aseg-switch').length;
        $('#listaAseguradoras .aseg-switch').prop('checked', !todas);
        actualizarContadorAseguradoras();
    });

    $('#btnAsegContinuar').on('click', function () {
        aseguradorasSeleccionadas = seleccionadas();
        if (!aseguradorasSeleccionadas.length) {
            return;
        }
        $('#modalAseguradoras').one('hidden.bs.modal', function () { ceroKmModal.show(); });
        aseguradorasModal.hide();
    });

    $('#btnCeroKmSi').on('click', function () { responderCeroKm(true); });
    $('#btnCeroKmNo').on('click', function () { responderCeroKm(false); });

    function responderCeroKm(esCeroKm) {
        $('#id_es_cero_km').val(esCeroKm ? 'true' : 'false');
        $('#modalCeroKm').one('hidden.bs.modal', function () {
            if (esCeroKm) {
                abrirDatosCeroKm();
            } else {
                // Un vehículo usado no lleva estos datos: los bots los
                // obtienen del portal de cada aseguradora por la placa.
                $('#id_codigo_fasecolda').val('');
                $('#id_valor_comercial').val('');
                enviarSolicitud();
            }
        });
        ceroKmModal.hide();
    }

    // 0 km: sin historial por placa, así que se piden aquí el código Fasecolda
    // y el valor comercial antes de enviar la solicitud.
    function abrirDatosCeroKm() {
        $('#datosCeroKmError').addClass('d-none').empty();
        $('#inputFasecolda').val($('#id_codigo_fasecolda').val());
        $('#inputValorComercial').val(formatearValorComercial($('#id_valor_comercial').val()));
        datosCeroKmModal.show();
        $('#modalDatosCeroKm').one('shown.bs.modal', function () { $('#inputFasecolda').trigger('focus'); });
    }

    function formatearValorComercial(valor) {
        var digitos = String(valor || '').replace(/\D/g, '');
        return digitos ? Number(digitos).toLocaleString('es-CO') : '';
    }

    $('#inputFasecolda').on('input', function () {
        $(this).val($(this).val().replace(/\D/g, ''));
        $('#datosCeroKmError').addClass('d-none');
    });
    $('#inputValorComercial').on('input', function () {
        $(this).val(formatearValorComercial($(this).val()));
        $('#datosCeroKmError').addClass('d-none');
    });

    $('#btnDatosCeroKmVolver').on('click', function () {
        datosCeroKmModal.hide();
    });

    $('#btnDatosCeroKmContinuar').on('click', function () {
        var fasecolda = $('#inputFasecolda').val().trim();
        var valor = $('#inputValorComercial').val().replace(/\D/g, '');
        var $error = $('#datosCeroKmError');
        if (!/^\d{5,10}$/.test(fasecolda)) {
            $error.removeClass('d-none').text('Ingresa un código Fasecolda válido (solo números).');
            return;
        }
        if (!valor || Number(valor) <= 0) {
            $error.removeClass('d-none').text('Ingresa el valor comercial del vehículo.');
            return;
        }
        $('#id_codigo_fasecolda').val(fasecolda);
        $('#id_valor_comercial').val(valor);
        $('#modalDatosCeroKm').one('hidden.bs.modal', enviarSolicitud);
        datosCeroKmModal.hide();
    });

    function enviarSolicitud() {
        $errors.addClass('d-none').empty();
        $btn.prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin"></i> Enviando...');

        $.ajax({
            url: $form.attr('action') || window.location.href,
            type: 'POST',
            data: new FormData($form[0]),
            processData: false,
            contentType: false,
            dataType: 'json',
            headers: {'X-CSRFToken': csrftoken},
            success: function (response) {
                if (response.hasOwnProperty('error')) {
                    showErrors(response.error);
                } else {
                    showSuccess(response);
                }
            },
            error: function () {
                showErrors('Ocurrió un error inesperado al enviar la solicitud. Intenta nuevamente.');
            },
            complete: function () {
                $btn.prop('disabled', false).html('<i class="fa-solid fa-magnifying-glass-dollar"></i> Cotizar ahora');
            }
        });
    }

    function showErrors(error) {
        var message = error;
        if (typeof error === 'object') {
            var parts = [];
            $.each(error, function (field, msgs) {
                parts.push((Array.isArray(msgs) ? msgs.join(', ') : msgs));
            });
            message = parts.join('<br>');
        }
        $errors.removeClass('d-none').html(message);
    }

    function showSuccess(vehiculo) {
        var tomador = vehiculo.tomador || {};
        var html = '';
        html += '<div><span>Tomador</span><b>' + (tomador.text || '') + '</b></div>';
        html += '<div><span>Placa</span><b>' + (vehiculo.placa || '') + '</b></div>';
        html += '<div><span>Ciudad</span><b>' + (vehiculo.zona_circulacion || '') + '</b></div>';
        html += '<div><span>0 kilómetros</span><b>' + (vehiculo.es_cero_km ? 'Sí' : 'No') + '</b></div>';
        $('#quoteSuccessSummary').html(html);

        $form.fadeOut(150, function () {
            $('#quoteSuccessState').fadeIn(200).css('display', 'block');
            iniciarCotizacionAutomatica(vehiculo.id);
        });
    }

    // ------------------------------------------------------------------
    // Cotización automática (bots): se lanza apenas se registra la
    // solicitud y se muestra, aseguradora por aseguradora, el avance en vivo,
    // el resultado o el error explicado (con botón para reenviar solo a la
    // que falló). El dibujo de cada tarjeta vive en proceso.js.
    // ------------------------------------------------------------------

    var idsCotizaciones = [];
    var $resultados = $('#quoteBotResults');

    function iniciarCotizacionAutomatica(vehiculoId) {
        clearInterval(pollCotizaciones);
        idsCotizaciones = [];
        $resultados.addClass('d-none').empty();
        $('#quoteBotLoading').css('display', 'block');

        if (!cotizarUrl || !vehiculoId) {
            return;
        }

        $.ajax({
            url: cotizarUrl,
            type: 'POST',
            data: {vehiculo_id: vehiculoId, eligio_aseguradoras: 1, aseguradoras: aseguradorasSeleccionadas},
            traditional: true,
            dataType: 'json',
            headers: {'X-CSRFToken': csrftoken},
            success: function (response) {
                if (response.error || !response.cotizaciones || !response.cotizaciones.length) {
                    mostrarErrorCotizando(response.error);
                    return;
                }
                idsCotizaciones = response.cotizaciones.map(function (c) { return c.id; });
                monitorearCotizaciones();
            },
            error: function () {
                mostrarErrorCotizando('No se pudo iniciar la cotización automática.');
            }
        });
    }

    function consultarEstado() {
        $.ajax({
            url: estadoUrl,
            type: 'GET',
            data: {ids: idsCotizaciones.join(',')},
            dataType: 'json',
            success: function (response) {
                var cotizaciones = (response.cotizaciones || []).sort(function (a, b) { return a.id - b.id; });
                $resultados.removeClass('d-none').css('display', 'block');
                ProcesoCotizacion.render($resultados.addClass('pc-lista'), cotizaciones);
                if (ProcesoCotizacion.todasTerminaron(cotizaciones) && cotizaciones.length === idsCotizaciones.length) {
                    clearInterval(pollCotizaciones);
                    $('#quoteBotLoading').css('display', 'none');
                }
            },
            error: function () {
                // Un fallo puntual de red no debe romper el seguimiento: se reintenta en el próximo ciclo.
            }
        });
    }

    function monitorearCotizaciones() {
        clearInterval(pollCotizaciones);
        consultarEstado();
        pollCotizaciones = setInterval(consultarEstado, 3000);
    }

    // Reenviar la solicitud SOLO a la aseguradora cuya tarjeta falló.
    $resultados.on('click', '.pc-reintentar', function () {
        var $boton = $(this).prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin"></i> Reenviando...');
        var cotizacionId = $boton.data('id');
        ProcesoCotizacion.reintentar(reintentarUrl, csrftoken, cotizacionId).done(function (response) {
            if (response.error) {
                $boton.prop('disabled', false).html('<i class="fa-solid fa-rotate-right"></i> Reenviar');
                toastr.error(response.error);
                return;
            }
            idsCotizaciones = idsCotizaciones.map(function (id) { return id === cotizacionId ? response.cotizacion.id : id; });
            $('#quoteBotLoading').css('display', 'block');
            monitorearCotizaciones();
        }).fail(function () {
            $boton.prop('disabled', false).html('<i class="fa-solid fa-rotate-right"></i> Reenviar');
            toastr.error('No se pudo reenviar la solicitud. Intenta nuevamente.');
        });
    });

    function mostrarErrorCotizando(mensaje) {
        $('#quoteBotLoading').css('display', 'none');
        $resultados.removeClass('d-none').css('display', 'block')
            .html('<div class="alert alert-warning">' + ProcesoCotizacion.esc(mensaje || 'No se pudo iniciar la cotización automática.') + '</div>');
    }

    $('#btnNuevaSolicitud').on('click', function () {
        clearInterval(pollCotizaciones);
        $form[0].reset();
        $('#id_es_cero_km').val('false');
        $('#id_codigo_fasecolda, #id_valor_comercial, #inputFasecolda, #inputValorComercial').val('');
        $('select[name="zona_circulacion"]').val(null).trigger('change');
        $('select[name="document_type"]').val(defaultDocumentType).trigger('change');
        $('#quoteSuccessState').fadeOut(150, function () {
            $form.fadeIn(200).css('display', 'block');
        });
    });

});

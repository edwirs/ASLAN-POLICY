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

    // Cédula y nombre del dueño de la empresa: solo se piden (opcionales) cuando el tomador es NIT.
    function mostrarPropietarioEmpresa() {
        var esNit = /\bNIT\b/i.test($('select[name="document_type"] option:selected').text());
        $('#filaPropietarioEmpresa').toggleClass('d-none', !esNit);
        if (!esNit) {
            $('input[name="propietario_documento"], input[name="propietario_nombre"]').val('');
        }
    }
    $('select[name="document_type"]').on('change', mostrarPropietarioEmpresa);
    mostrarPropietarioEmpresa();

    // Otro celular y otro correo: solo se ven si el asesor indica que el cliente tiene más datos de contacto.
    var $masContacto = $('input[name="mas_contacto"]');
    function mostrarMasContacto() {
        var activo = $masContacto.is(':checked');
        $('#filaMasContacto').toggleClass('d-none', !activo);
        if (!activo) {
            $('input[name="phone"], input[name="email_secundario"]').val('');
        }
    }
    $masContacto.on('change', mostrarMasContacto);
    mostrarMasContacto();
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
        aplicarEstadoPlaca(null);  // el aviso de la placa anterior deja de aplicar hasta consultar la nueva
    });
    // En el paso 3 la placa se puede escribir o cambiar: solo se revisa si está bloqueada y su ciudad de
    // circulación. Los datos del tomador ya se confirmaron en el paso 2 y no se pisan.
    $('input[name="placa"]').on('blur', function () {
        var placa = $(this).val().trim();
        if (!placa || !lookupUrl) {
            return;
        }
        $.getJSON(lookupUrl, {tipo: 'placa', valor: placa}).done(function (data) {
            aplicarEstadoPlaca(data.found ? data.estado_placa : null);
            if (data.found && data.zona_circulacion_id && !$('select[name="zona_circulacion"]').val()) {
                $('select[name="zona_circulacion"]').val(data.zona_circulacion_id).trigger('change');
            }
        });
    });

    // ------------------------------------------------------------------
    // Asistente: 1 consulta › 2 tomador › 3 vehículo
    // ------------------------------------------------------------------
    var pasoActual = 1;

    function irAPaso(paso) {
        pasoActual = paso;
        $('.qw-panel').removeClass('activo').filter('[data-paso="' + paso + '"]').addClass('activo');
        $('.qw-paso-ind').each(function () {
            var n = Number($(this).data('paso'));
            $(this).toggleClass('activo', n === paso).toggleClass('hecho', n < paso);
        });
        if (paso === 3) {
            pintarResumenTomador();
        }
        var tarjeta = $('.quote-request-card')[0];
        if (tarjeta && tarjeta.getBoundingClientRect().top < 0) {
            tarjeta.scrollIntoView({behavior: 'smooth', block: 'start'});
        }
        setTimeout(function () {
            var foco = {1: '#qwBuscarValor', 2: 'input[name="names"]', 3: 'input[name="placa"]'}[paso];
            if (paso === 3 && !$('#qwCampoPlaca').is(':visible')) {
                return;
            }
            $(foco).trigger('focus');
        }, 320);
    }

    $form.on('click', '.qw-btn-atras', function () { irAPaso(Number($(this).data('ir'))); });
    $form.on('click', '[data-editar-tomador]', function () { irAPaso(2); });
    // La placa cargada en la consulta se ve en el resumen; «Cambiar» abre el campo para escribir otra.
    var editandoPlaca = false;
    $form.on('click', '[data-cambiar-placa]', function () {
        editandoPlaca = true;
        pintarResumenTomador();
        $('input[name="placa"]').trigger('focus').select();
    });

    // Paso 1: consultar por cédula o placa.
    var $buscar = $('#qwBuscarValor');

    function tipoConsulta() {
        return $('input[name="qw_tipo"]:checked').val();
    }

    $('input[name="qw_tipo"]').on('change', function () {
        var porPlaca = tipoConsulta() === 'placa';
        $buscar.toggleClass('qw-placa', porPlaca).attr('placeholder', porPlaca ? 'ABC123' : 'Número de documento')
            .attr('maxlength', porPlaca ? 10 : 20).val('').trigger('focus');
        $('#qwBuscarIcono').attr('class', porPlaca ? 'fa-solid fa-car' : 'fa-solid fa-id-card');
        $('#qwConsultaError').addClass('d-none');
    });

    $buscar.on('input', function () {
        if (tipoConsulta() === 'placa') {
            $(this).val($(this).val().toUpperCase().replace(/\s/g, ''));
        }
        $('#qwConsultaError').addClass('d-none');
    }).on('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            consultar();
        }
    });
    $('#btnConsultar').on('click', consultar);

    function limpiarTomador() {
        $('input[name="dni"], input[name="names"], input[name="birthdate"], input[name="email"], input[name="mobile"], ' +
          'input[name="phone"], input[name="email_secundario"], input[name="propietario_documento"], ' +
          'input[name="propietario_nombre"], input[name="placa"]').val('');
        $('select[name="document_type"]').val(defaultDocumentType).trigger('change');
        $('select[name="zona_circulacion"]').val(null).trigger('change');
        $masContacto.prop('checked', false);
        mostrarMasContacto();
        aplicarEstadoPlaca(null);
        $errors.addClass('d-none').empty();
        editandoPlaca = false;
    }

    function consultar() {
        var tipo = tipoConsulta();
        var valor = $buscar.val().trim();
        var $error = $('#qwConsultaError');
        if (!valor) {
            $error.removeClass('d-none').text(tipo === 'placa' ? 'Escribe la placa a consultar.' : 'Escribe el número de documento a consultar.');
            $buscar.trigger('focus');
            return;
        }
        var $boton = $('#btnConsultar').prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin"></i> Consultando...');
        $.getJSON(lookupUrl, {tipo: tipo, valor: valor}).done(function (data) {
            limpiarTomador();
            if (tipo === 'placa') {
                $('input[name="placa"]').val(valor.toUpperCase());
            } else {
                $('input[name="dni"]').val(valor);
            }
            if (data.found) {
                aplicarDatosEncontrados(data);
                mostrarAvisoCliente(true, data.names);
            } else {
                mostrarAvisoCliente(false, null, tipo);
            }
            irAPaso(2);
            if (data.found && data.vehiculos && data.vehiculos.length > 1) {
                mostrarSeleccionPlaca(data.vehiculos);
            }
        }).fail(function () {
            $error.removeClass('d-none').text('No se pudo consultar en este momento. Intenta nuevamente.');
        }).always(function () {
            $boton.prop('disabled', false).html('<i class="fa-solid fa-magnifying-glass"></i> Consultar');
        });
    }

    function mostrarAvisoCliente(encontrado, nombre, tipo) {
        var html = encontrado
            ? '<i class="fa-solid fa-circle-check"></i><div><b>Cliente registrado: ' + ProcesoCotizacion.esc(nombre || '') + '</b>' +
              '<small>Cargamos sus datos. Revisa que estén al día y continúa.</small></div>'
            : '<i class="fa-solid fa-user-plus"></i><div><b>Cliente nuevo</b><small>' +
              (tipo === 'placa' ? 'No encontramos esa placa registrada.' : 'No encontramos ese documento registrado.') +
              ' Completa los datos del tomador.</small></div>';
        $('#qwAvisoCliente').removeClass('d-none encontrado nuevo').addClass(encontrado ? 'encontrado' : 'nuevo').html(html);
    }

    // Paso 2 › 3: se revisan los datos obligatorios del tomador antes de seguir.
    $('#btnPaso2Siguiente').on('click', function () {
        if (validarTomador()) {
            irAPaso(3);
        }
    });

    function validarTomador() {
        if (!$('select[name="document_type"]').val()) {
            toastr.warning('Selecciona el tipo de documento.');
            return false;
        }
        var campos = ['dni', 'names', 'birthdate', 'email', 'mobile', 'phone', 'email_secundario'];
        for (var i = 0; i < campos.length; i++) {
            var el = $form.find('[name="' + campos[i] + '"]')[0];
            if (el && !el.checkValidity()) {
                el.reportValidity();
                return false;
            }
        }
        var nacimiento = $('input[name="birthdate"]').val();
        if (nacimiento && nacimiento > new Date().toISOString().slice(0, 10)) {
            toastr.warning('La fecha de nacimiento no puede ser futura.');
            $('input[name="birthdate"]').trigger('focus');
            return false;
        }
        var celulares = ['mobile', 'phone'];
        for (var j = 0; j < celulares.length; j++) {
            var digitos = ($form.find('[name="' + celulares[j] + '"]').val() || '').replace(/\D/g, '').replace(/^57(?=\d{10}$)/, '');
            if (digitos && digitos.length !== 10) {
                toastr.warning('El celular debe tener 10 dígitos.');
                $form.find('[name="' + celulares[j] + '"]').trigger('focus');
                return false;
            }
        }
        return true;
    }

    function pintarResumenTomador() {
        var nombre = $('input[name="names"]').val().trim();
        var iniciales = nombre.split(/\s+/).filter(Boolean).slice(0, 2).map(function (p) { return p[0]; }).join('').toUpperCase();
        var tipo = $('select[name="document_type"] option:selected').text().replace(/^.*\((.*)\)$/, '$1');
        var detalle = [tipo + ' ' + $('input[name="dni"]').val().trim(), $('input[name="email"]').val().trim()].filter(Boolean).join(' · ');
        var placa = $('input[name="placa"]').val().trim();
        // Con placa cargada solo se pide la ciudad; sin placa (cliente sin vehículos) o al pulsar «Cambiar», también la placa.
        var pedirPlaca = !placa || editandoPlaca;
        $('#qwCampoPlaca').toggleClass('d-none', !pedirPlaca);
        $('#qwCampoZona').toggleClass('col-md-12', !pedirPlaca).toggleClass('col-md-6', pedirPlaca);
        var bloquePlaca = (placa && !editandoPlaca)
            ? '<span class="qw-resumen-placa"><small>Placa</small><span class="qw-placa-chip">' + ProcesoCotizacion.esc(placa) + '</span>' +
              '<button type="button" class="qw-link" data-cambiar-placa><i class="fa-solid fa-arrows-rotate"></i> Cambiar</button></span>'
            : '';
        $('#qwResumenTomador').html(
            '<span class="qw-resumen-avatar">' + ProcesoCotizacion.esc(iniciales || '?') + '</span>' +
            '<span class="qw-resumen-datos"><b>' + ProcesoCotizacion.esc(nombre) + '</b><small>' + ProcesoCotizacion.esc(detalle) + '</small></span>' +
            bloquePlaca +
            '<button type="button" class="qw-link" data-editar-tomador><i class="fa-solid fa-pen"></i> Editar</button>');
    }

    // Desde la ficha del vehículo («Nueva cotización») llega con ?placa=: se consulta esa placa de una vez.
    var placaInicial = (new URLSearchParams(location.search).get('placa') || '').trim().toUpperCase();
    if (placaInicial) {
        $('#qwTipoPlaca').prop('checked', true).trigger('change');
        $buscar.val(placaInicial);
        consultar();
    } else {
        setTimeout(function () { $buscar.trigger('focus'); }, 200);
    }

    // ------------------------------------------------------------------
    // Placa marcada (vendido, siniestrado…): se avisa y se bloquea «Cotizar ahora» hasta reactivarla.
    // ------------------------------------------------------------------
    var placaBloqueada = false;

    function aplicarEstadoPlaca(estado) {
        placaBloqueada = !!(estado && estado.bloqueado);
        $('#avisoPlaca').toggleClass('d-none', !placaBloqueada);
        $btn.prop('disabled', placaBloqueada);
        if (!placaBloqueada) {
            return;
        }
        $('#avisoPlacaTexto').text(estado.aviso || 'La placa no está activa.');
        var puede = $form.data('puede-reactivar') === 1;
        $('#avisoPlacaReactivar').toggleClass('d-none', !puede);
        $('#avisoPlacaSinPermiso').toggleClass('d-none', puede);
        $('#notaReactivar').val('');
    }

    $('#btnReactivarPlaca').on('click', function () {
        var $boton = $(this).prop('disabled', true);
        $.ajax({
            url: $form.data('reactivar-url'),
            type: 'POST',
            data: {placa: $('input[name="placa"]').val(), nota: $('#notaReactivar').val()},
            dataType: 'json',
            headers: {'X-CSRFToken': csrftoken}
        }).done(function (response) {
            aplicarEstadoPlaca(response.estado_placa);
            toastr.success('Placa reactivada: ya puedes cotizarla.');
        }).fail(function (xhr) {
            toastr.error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo reactivar la placa.');
        }).always(function () {
            $boton.prop('disabled', false);
        });
    });

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
        $('input[name="mobile"]').val(data.mobile || '');
        $masContacto.prop('checked', !!(data.phone || data.email_secundario));
        mostrarMasContacto();
        $('input[name="phone"]').val(data.phone || '');
        $('input[name="email_secundario"]').val(data.email_secundario || '');
        $('input[name="propietario_documento"]').val(data.propietario_documento || '');
        $('input[name="propietario_nombre"]').val(data.propietario_nombre || '');
        if (data.estado_placa) {
            aplicarEstadoPlaca(data.estado_placa);
        }
        if (data.zona_circulacion_id) {
            $('select[name="zona_circulacion"]').val(data.zona_circulacion_id).trigger('change');
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
                    aplicarEstadoPlaca(v.estado_placa);
                    editandoPlaca = false;
                    if (pasoActual === 3) {
                        pintarResumenTomador();
                    }
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
        if (pasoActual !== 3) {
            return;  // Enter en otro paso no envía: se avanza con los botones
        }
        if (placaBloqueada) {
            return;
        }
        var placa = $('input[name="placa"]')[0];
        if (!placa.checkValidity()) {
            editandoPlaca = true;
            pintarResumenTomador();
            placa.reportValidity();
            return;
        }
        if (!$('select[name="zona_circulacion"]').val()) {
            toastr.warning('Selecciona la ciudad de circulación del vehículo.');
            $('select[name="zona_circulacion"]').select2('open');
            return;
        }
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
                    if (response.estado_placa) {
                        aplicarEstadoPlaca(response.estado_placa);
                    }
                } else {
                    showSuccess(response);
                }
            },
            error: function () {
                showErrors('Ocurrió un error inesperado al enviar la solicitud. Intenta nuevamente.');
            },
            complete: function () {
                $btn.prop('disabled', placaBloqueada).html('<i class="fa-solid fa-magnifying-glass-dollar"></i> Cotizar ahora');
            }
        });
    }

    function showErrors(error) {
        var message = error;
        if (typeof error === 'object') {
            var parts = [];
            $.each(error, function (field, msgs) {
                // Cada error con el nombre del campo, porque puede ser de un paso anterior (ej. el correo del tomador).
                var etiqueta = $.trim($form.find('[name="' + field + '"]').closest('.quote-field-group').find('label').first()
                    .clone().children('small').remove().end().text());
                parts.push((etiqueta ? '<b>' + ProcesoCotizacion.esc(etiqueta) + ':</b> ' : '') +
                    ProcesoCotizacion.esc(Array.isArray(msgs) ? msgs.join(', ') : msgs));
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

    // Valor cotizado a mano: se vuelve a pintar el estado para que la tarjeta lo muestre.
    $(document).on('valorManual:guardado', function () { consultarEstado(); });

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
        limpiarTomador();
        $('#qwAvisoCliente').addClass('d-none');
        $('#qwTipoDni').prop('checked', true).trigger('change');
        $('#quoteSuccessState').fadeOut(150, function () {
            $form.fadeIn(200).css('display', 'block');
            irAPaso(1);
        });
    });

});

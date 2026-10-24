/* Dibuja el estado de la cotización con cada aseguradora (en curso, completada
   o con error explicado) y envía el reintento a UNA aseguradora. Lo usan el
   formulario de Nueva Cotización y el botón «Ver proceso» del listado. */
var ProcesoCotizacion = (function () {

    var FINALES = ['completado', 'error', 'cancelado'];

    var ICONO_TIPO = {
        autenticacion: 'fa-key',
        timeout: 'fa-hourglass-end',
        datos: 'fa-pen-to-square',
        portal: 'fa-triangle-exclamation',
        interrumpida: 'fa-plug-circle-xmark',
        no_cotizable: 'fa-ban',
        saturado: 'fa-hourglass-half',
        clave_vencida: 'fa-key',
        inesperado: 'fa-bug'
    };

    function esc(texto) {
        return $('<div>').text(texto == null ? '' : String(texto)).html();
    }

    function dinero(valor) {
        return '$' + Number(valor || 0).toLocaleString('es-CO', {maximumFractionDigits: 0});
    }

    function terminada(c) {
        return FINALES.indexOf(c.estado_bot) !== -1;
    }

    function todasTerminaron(cotizaciones) {
        return cotizaciones.length > 0 && cotizaciones.every(terminada);
    }

    function filaDatos(c) {
        if (!c.datos || !c.datos.length) {
            return '';
        }
        var filas = c.datos.map(function (d) {
            return '<div><span>' + esc(d.etiqueta) + '</span><b>' + esc(d.valor) + '</b></div>';
        }).join('');
        return '<details class="pc-detalle"><summary>Datos con los que se cotizó</summary>' +
            '<div class="pc-datos">' + filas + '</div></details>';
    }

    function cuerpoCompletado(c) {
        var destacado = c.plan_destacado || 'Premium';
        var html = '<div class="pc-prima">' + dinero(c.prima_total) + ' <small>' + esc(destacado) + '</small></div>';
        if (c.planes && c.planes.length) {
            html += '<ul class="pc-planes">' + c.planes.map(function (p) {
                var principal = String(p.nombre).toLowerCase() === String(destacado).toLowerCase() ? ' class="pc-plan-principal"' : '';
                return '<li' + principal + '><span>' + esc(p.nombre) + '</span><b>' + dinero(p.prima) + '</b></li>';
            }).join('') + '</ul>';
        }
        if (c.porcentaje_descuento !== null && c.porcentaje_descuento !== undefined) {
            html += '<div class="pc-chip"><i class="fa-solid fa-tag"></i> Descuento de la aseguradora: ' +
                esc(c.porcentaje_descuento) + '%</div>';
        }
        if (c.nota) {
            html += '<div class="pc-nota">' + esc(c.nota) + '</div>';
        }
        return html + filaDatos(c);
    }

    function cuerpoEnCurso(c) {
        var paso = c.paso ? 'Paso actual: <b>' + esc(c.paso) + '</b>' : 'Iniciando…';
        return '<div class="pc-paso"><i class="fa-solid fa-spinner fa-spin"></i> ' + paso + '</div>';
    }

    // El bot está pausado esperando algo que solo una persona puede hacer.
    function cuerpoEspera(c) {
        var html = '<div class="pc-tipo pc-tipo-espera"><i class="fa-solid fa-hand"></i> Falta un paso tuyo</div>' +
            '<div class="pc-mensaje">' + esc(c.mensaje_espera || 'La aseguradora necesita una verificación.') + '</div>';
        if (c.verificacion === 'codigo') {
            html += '<button type="button" class="btn btn-sm btn-warning pc-abrir-codigo" data-id="' + c.id + '">' +
                '<i class="fa-solid fa-key"></i> Escribir el código</button>';
        }
        return html + '<div class="pc-paso"><i class="fa-solid fa-spinner fa-spin"></i> Esperando…</div>';
    }

    // Modal del código de 6 dígitos que la aseguradora envía al celular (ej. Mapfre). Una sola para todas las tarjetas.
    var verificacion = {id: null, modal: null, descartadas: {}, ultimas: []};

    function urlVerificacion() {
        return (window.PROCESO_URLS || {}).verificacion;
    }

    function digitos() {
        return $('#modalCodigoVerificacion .pc-digito').map(function () { return $(this).val(); }).get().join('');
    }

    function construirModalCodigo() {
        if (document.getElementById('modalCodigoVerificacion')) { return; }
        var cajas = '';
        for (var i = 0; i < 6; i++) {
            cajas += '<input type="text" inputmode="numeric" maxlength="1" autocomplete="one-time-code" class="pc-digito" aria-label="Dígito ' + (i + 1) + '">';
        }
        $('body').append(
            '<div class="modal fade" id="modalCodigoVerificacion" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">' +
            '<div class="modal-header"><h5 class="modal-title"><i class="fa-solid fa-shield-halved"></i> Código de verificación <span class="pc-cod-aseguradora"></span></h5>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button></div>' +
            '<div class="modal-body text-center"><p class="pc-cod-mensaje mb-3"></p><div class="pc-digitos">' + cajas + '</div>' +
            '<div class="pc-cod-error text-danger mt-2" role="alert"></div></div>' +
            '<div class="modal-footer"><button type="button" class="btn btn-outline-danger btn-sm pc-cod-cancelar"><i class="fa-solid fa-xmark"></i> Cancelar cotización</button>' +
            '<button type="button" class="btn btn-primary pc-cod-validar" disabled><i class="fa-solid fa-check"></i> Validar código</button></div>' +
            '</div></div></div>');
        var $m = $('#modalCodigoVerificacion');
        verificacion.modal = new bootstrap.Modal($m[0]);
        $m.on('hidden.bs.modal', function () {
            if (verificacion.id) { verificacion.descartadas[verificacion.id] = true; }  // no se reabre sola en cada refresco
            verificacion.id = null;
        });
        $m.on('shown.bs.modal', function () { $m.find('.pc-digito').first().trigger('focus'); });
        $m.on('input', '.pc-digito', function () {
            var d = this.value.replace(/\D/g, '').slice(-1);
            this.value = d;
            if (d) { $(this).next('.pc-digito').trigger('focus'); }
            $m.find('.pc-cod-validar').prop('disabled', digitos().length !== 6);
            $m.find('.pc-cod-error').text('');
        });
        $m.on('keydown', '.pc-digito', function (e) {
            if (e.key === 'Backspace' && !this.value) { $(this).prev('.pc-digito').trigger('focus').val(''); }
            if (e.key === 'Enter' && digitos().length === 6) { $m.find('.pc-cod-validar').trigger('click'); }
        });
        $m.on('paste', '.pc-digito', function (e) {
            var texto = ((e.originalEvent.clipboardData || window.clipboardData).getData('text') || '').replace(/\D/g, '').slice(0, 6);
            if (!texto) { return; }
            e.preventDefault();
            $m.find('.pc-digito').each(function (i) { this.value = texto.charAt(i) || ''; });
            $m.find('.pc-cod-validar').prop('disabled', texto.length !== 6);
            $m.find('.pc-digito').eq(Math.min(texto.length, 5)).trigger('focus');
        });
        $m.on('click', '.pc-cod-validar', function () {
            var $b = $(this).prop('disabled', true);
            enviarVerificacion({codigo: digitos()}).done(function () {
                verificacion.descartadas[verificacion.id] = true;
                verificacion.modal.hide();
            }).fail(function (xhr) {
                $m.find('.pc-cod-error').text((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo enviar el código. Intenta de nuevo.');
                $b.prop('disabled', false);
            });
        });
        $m.on('click', '.pc-cod-cancelar', function () {
            enviarVerificacion({cancelar: 1}).always(function () { verificacion.modal.hide(); });
        });
    }

    function enviarVerificacion(datos) {
        return $.ajax({
            url: urlVerificacion(), type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
            data: $.extend({cotizacion_id: verificacion.id}, datos)
        });
    }

    function abrirModalCodigo(c) {
        if (!urlVerificacion()) { return; }
        construirModalCodigo();
        var $m = $('#modalCodigoVerificacion');
        verificacion.id = c.id;
        $m.find('.pc-cod-aseguradora').text('· ' + c.aseguradora + ' (' + c.placa + ')');
        $m.find('.pc-cod-mensaje').text(c.mensaje_espera || 'Escribe el código de 6 dígitos que llegó al celular registrado.');
        $m.find('.pc-digito').val('');
        $m.find('.pc-cod-error').text('');
        $m.find('.pc-cod-validar').prop('disabled', true);
        verificacion.modal.show();
    }

    // Cada refresco: abre la modal cuando un bot pide el código y la cierra si ya no hace falta.
    function revisarVerificaciones(cotizaciones) {
        verificacion.ultimas = cotizaciones;
        var pide = cotizaciones.filter(function (c) { return c.estado_bot === 'esperando_confirmacion' && c.verificacion === 'codigo'; });
        if (verificacion.id && !pide.some(function (c) { return c.id === verificacion.id; })) {
            var abierta = verificacion.id;
            verificacion.id = null;
            verificacion.descartadas[abierta] = true;
            if (verificacion.modal) { verificacion.modal.hide(); }
        }
        var nueva = pide.filter(function (c) { return !verificacion.descartadas[c.id]; })[0];
        if (nueva && !verificacion.id) { abrirModalCodigo(nueva); }
    }

    // Botón de la tarjeta: vuelve a abrir la modal si el asesor la había cerrado.
    $(document).on('click', '.pc-abrir-codigo', function () {
        delete verificacion.descartadas[$(this).data('id')];
        revisarVerificaciones(verificacion.ultimas || []);
    });

    function cuerpoError(c) {
        var html = '<div class="pc-tipo pc-tipo-' + esc(c.error_tipo) + '">' +
            '<i class="fa-solid ' + (ICONO_TIPO[c.error_tipo] || 'fa-circle-exclamation') + '"></i> ' +
            esc(c.error_tipo_display || 'Error') + '</div>';
        html += '<div class="pc-mensaje">' + esc(c.mensaje || 'No se pudo completar la cotización.') + '</div>';
        if (c.paso) {
            html += '<div class="pc-paso-fallo"><i class="fa-solid fa-location-dot"></i> Se detuvo en: <b>' + esc(c.paso) + '</b></div>';
        }
        if (c.accion) {
            html += '<div class="pc-accion"><b>Qué hacer:</b> ' + esc(c.accion) + '</div>';
        }
        html += filaDatos(c);
        if (c.detalle_tecnico && !esAviso(c)) {
            html += '<details class="pc-detalle"><summary>Detalle técnico (para soporte)</summary>' +
                '<pre>' + esc(c.detalle_tecnico) + '</pre></details>';
        }
        if (c.clave_pendiente && c.url_credencial) {
            html += '<a class="btn btn-sm btn-warning pc-clave-link" href="' + esc(c.url_credencial) + '">' +
                '<i class="fa-solid fa-key"></i> Actualizar contraseña de ' + esc(c.aseguradora) + '</a>';
        }
        if (c.puede_reintentar) {
            html += '<button type="button" class="btn btn-sm pc-reintentar" data-id="' + c.id + '">' +
                '<i class="fa-solid fa-rotate-right"></i> Reenviar a ' + esc(c.aseguradora) + '</button>';
        }
        return html;
    }

    var ETIQUETA_AVISO = {no_cotizable: 'No cotiza', saturado: 'Portal saturado', clave_vencida: 'Cambiar contraseña'};
    var ETIQUETA = {completado: 'Completada', error: 'Con error', cancelado: 'Cancelada'};

    // «La aseguradora no cotiza este caso» (ya asegurado, modelo no admitido...) no es una
    // falla: se muestra como advertencia.
    function esAviso(c) {
        return c.estado_bot === 'error' && (c.error_tipo === 'no_cotizable' || c.error_tipo === 'saturado' || c.error_tipo === 'clave_vencida');
    }

    function tarjeta(c) {
        var clase, etiqueta, cuerpo;
        if (c.estado_bot === 'completado') {
            clase = 'pc-ok'; etiqueta = ETIQUETA.completado; cuerpo = cuerpoCompletado(c);
        } else if (esAviso(c)) {
            clase = 'pc-aviso'; etiqueta = ETIQUETA_AVISO[c.error_tipo] || 'Aviso'; cuerpo = cuerpoError(c);
        } else if (c.estado_bot === 'esperando_confirmacion') {
            clase = 'pc-espera'; etiqueta = 'Necesita tu ayuda'; cuerpo = cuerpoEspera(c);
        } else if (terminada(c)) {
            clase = 'pc-error'; etiqueta = ETIQUETA[c.estado_bot]; cuerpo = cuerpoError(c);
        } else {
            clase = 'pc-curso'; etiqueta = 'Cotizando…'; cuerpo = cuerpoEnCurso(c);
        }
        var intento = c.intento > 1 ? ' <span class="pc-intento">intento ' + c.intento + '</span>' : '';
        return '<div class="pc-card ' + clase + '" data-id="' + c.id + '">' +
            '<div class="pc-cabecera"><span class="pc-aseguradora">' + esc(c.aseguradora) + intento + '</span>' +
            '<span class="pc-estado">' + etiqueta + '</span></div>' + cuerpo + '</div>';
    }

    function render($contenedor, cotizaciones) {
        // Los <details> abiertos por el asesor no deben cerrarse en cada refresco.
        var abiertos = {};
        $contenedor.find('.pc-card').each(function () {
            abiertos[$(this).data('id')] = $(this).find('details[open]').map(function () {
                return $(this).find('summary').text();
            }).get();
        });
        $contenedor.html(cotizaciones.map(tarjeta).join(''));
        revisarVerificaciones(cotizaciones);
        $contenedor.find('.pc-card').each(function () {
            var previos = abiertos[$(this).data('id')] || [];
            $(this).find('details').each(function () {
                if (previos.indexOf($(this).find('summary').text()) !== -1) {
                    $(this).attr('open', true);
                }
            });
        });
    }

    // Devuelve la promesa del POST; el llamador decide qué refrescar.
    function reintentar(url, csrf, cotizacionId) {
        return $.ajax({
            url: url,
            type: 'POST',
            data: {cotizacion_id: cotizacionId},
            dataType: 'json',
            headers: {'X-CSRFToken': csrf}
        });
    }

    return {
        FINALES: FINALES,
        esc: esc,
        dinero: dinero,
        terminada: terminada,
        esAviso: esAviso,
        todasTerminaron: todasTerminaron,
        tarjeta: tarjeta,
        render: render,
        reintentar: reintentar
    };
})();

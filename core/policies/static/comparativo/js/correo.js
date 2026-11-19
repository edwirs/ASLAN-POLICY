function ajustarMarco(marco) {
    // El alto del marco sigue al correo (también cuando terminan de cargar las imágenes o se abre la ventana).
    function medir() {
        try { marco.style.height = Math.max(420, marco.contentDocument.documentElement.scrollHeight + 10) + 'px'; } catch (e) { /* sin acceso */ }
    }
    medir();
    try { [].forEach.call(marco.contentDocument.images, function (img) { img.addEventListener('load', medir); }); } catch (e) { /* sin acceso */ }
    setTimeout(medir, 350);
}
// «Armar correo» del comparativo: trae el correo armado con la plantilla, lo muestra para revisarlo y lo envía.
var correoCotizacion = (function () {
    var $modal, url, soloDiferencias = false, plantillaId = null, horario = {en_horario: true};

    function esc(t) { return $('<div>').text(t == null ? '' : t).html(); }

    function pintar(r) {
        var $sel = $('#pcPlantilla').empty();
        (r.plantillas || []).forEach(function (p) {
            $sel.append($('<option>').val(p.id).text(p.nombre + (p.predeterminada ? ' (predeterminada)' : '')));
        });
        $sel.val(r.plantilla_id);
        $('#pcFilaPlantilla').toggle((r.plantillas || []).length > 1);
        $('#pcDe').text(r.de || 'Sin cuenta de envío');
        $('#pcPara').val(r.para);
        $('#pcCc').val(r.cc);
        $('#pcAsunto').val(r.asunto);
        $('#pcFilaAdjunto').toggle(!!r.adjunto);
        pintarCotizaciones(r.cotizaciones || []);
        $('#pcAdjunto').attr('href', r.pdf_url).find('span').text(r.adjunto);
        horario = r.horario || {en_horario: true};
        var avisoHorario = horario.en_horario ? '' : '<div class="pc-aviso"><i class="fa-solid fa-clock"></i> Fuera del horario hábil (' +
            esc(horario.texto) + '): el correo quedará programado y sale el <b>' + esc(horario.siguiente) + '</b></div>';
        $('#pcCorreoAvisos').html(avisoHorario + (r.avisos || []).map(function (a) {
            return '<div class="pc-aviso"><i class="fa-solid fa-triangle-exclamation"></i> ' + esc(a) + '</div>';
        }).join(''));
        pintarEnviados(r.enviados || []);
        $('#pcEnviar').prop('disabled', !r.puede_enviar).html(horario.en_horario
            ? '<i class="fa-solid fa-paper-plane"></i> Enviar correo' : '<i class="fa-solid fa-clock"></i> Programar envío');
        document.getElementById('pcCorreoMarco').srcdoc = r.html;
        plantillaId = r.plantilla_id;
    }

    // Últimos correos de la placa: enviados, con error, cancelados y los programados (que se pueden cancelar).
    function pintarEnviados(lista) {
        $('#pcEnviados').html(lista.length ? '<i class="fa-solid fa-clock-rotate-left"></i> Correos de esta placa: ' + lista.map(function (e) {
            if (e.estado === 'programado') {
                return '<span class="pc-chip">Programado</span> sale el <b>' + esc(e.programado) + '</b> a ' + esc(e.para) +
                    (e.por ? ' · ' + esc(e.por) : '') + ' <a href="#" class="pc-cancelar-correo text-danger" data-id="' + e.id + '">Cancelar</a>';
            }
            var chip = e.estado === 'error' ? ' <span class="pc-chip pc-chip-alerta">No se envió</span>'
                : e.estado === 'cancelado' ? ' <span class="pc-chip">Cancelado</span>' : e.estado === 'enviando' ? ' <span class="pc-chip">Enviando…</span>' : '';
            return '<b>' + esc(e.fecha) + '</b> a ' + esc(e.para) + chip + (e.por ? ' · ' + esc(e.por) : '');
        }).join(' &nbsp;|&nbsp; ') : '');
    }

    // Las 2 más baratas del ranking y su PDF: el que bajó el bot del portal o el que sube el asesor (valores manuales,
    // o cuando el bot no pudo traerlo). `tipo` + `ref_id` dicen de dónde es: 'manual' (valor manual) o 'bot' (cotización).
    function pintarCotizaciones(lista) {
        $('#pcCotizaciones').toggleClass('d-none', !lista.length);
        $('#pcCotizacionesLista').html(lista.map(function (c) {
            var origen = c.manual ? 'valor manual' : (c.tiene_pdf ? 'cotizado por el bot · PDF del portal' : 'cotizado por el bot · el bot no trajo el PDF');
            // Aseguradora actual fuera de las 2 más baratas: su renovación se adjunta solo si el asesor sube el PDF.
            if (c.renovacion) { origen = 'aseguradora actual · renovación (opcional: se adjunta solo si sube el PDF)'; }
            var cabeza = '<span class="pc-cot-pos">' + c.posicion + '</span><span class="pc-cot-datos"><b>' + esc(c.aseguradora) +
                '</b><small>' + esc(c.valor_fmt) + ' · ' + origen + '</small></span>';
            var datos = ' data-tipo="' + c.tipo + '" data-id="' + c.ref_id + '"';
            var acciones;
            if (c.tiene_pdf) {
                var ver = url + (c.tipo === 'bot' ? '?portal_pdf=' : '?cotizacion_pdf=') + c.ref_id;
                acciones = '<a class="pc-adjunto" target="_blank" rel="noopener" href="' + ver + '" title="Ver el PDF que se adjunta">' +
                    '<i class="fa-solid fa-file-pdf"></i> ' + esc(c.archivo) + '</a>' +
                    '<button type="button" class="btn btn-sm btn-outline-secondary rounded-pill pc-cot-subir"' + datos + ' title="Cambiar el PDF">' +
                    '<i class="fa-solid fa-arrows-rotate"></i></button>' +
                    '<button type="button" class="btn btn-sm btn-outline-danger rounded-pill pc-cot-quitar"' + datos + ' data-nombre="' + esc(c.aseguradora) + '" title="Quitar el PDF">' +
                    '<i class="fa-solid fa-trash-can"></i></button>';
            } else {
                acciones = '<button type="button" class="btn btn-sm ' + (c.renovacion ? 'btn-outline-primary' : 'btn-primary') + ' rounded-pill pc-cot-subir"' + datos + '>' +
                    '<i class="fa-solid fa-upload"></i> ' + (c.renovacion ? 'Adjuntar PDF de la renovación' : 'Adjuntar PDF de la cotización') + '</button>';
            }
            return '<div class="pc-cot' + (c.tiene_pdf || c.renovacion ? '' : ' pc-cot-falta') + '">' + cabeza + '<span class="pc-cot-acciones">' + acciones + '</span></div>';
        }).join(''));
    }

    function cotizacionManual(datos, mensajeError) {
        $.LoadingOverlay('show');
        return $.ajax({url: url, type: 'POST', headers: {'X-CSRFToken': csrftoken}, dataType: 'json',
                       data: datos, processData: !(datos instanceof FormData), contentType: datos instanceof FormData ? false : undefined})
            .done(function (r) {
                if (r.error) { message_error(r.error); return; }
                pintarCotizaciones(r.cotizaciones || []);
                // El aviso «Falta adjuntar…» se quita o aparece según lo que quedó.
                var faltan = (r.cotizaciones || []).filter(function (c) { return !c.tiene_pdf && !c.renovacion; });
                $('#pcCorreoAvisos .pc-aviso').filter(function () { return /Falta adjuntar el PDF/.test($(this).text()); }).toggle(faltan.length > 0);
            })
            .fail(function (xhr) { message_error((xhr.responseJSON && xhr.responseJSON.error) || mensajeError); })
            .always(function () { $.LoadingOverlay('hide'); });
    }

    function cargar(id) {
        $.LoadingOverlay('show');
        $.getJSON(url, {plantilla: id || '', solo_diferencias: soloDiferencias ? '1' : ''})
            .done(function (r) {
                if (r.error) { message_error(r.error); bootstrap.Modal.getOrCreateInstance($modal[0]).hide(); return; }
                pintar(r);
            })
            .fail(function (xhr) { message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo armar el correo.'); })
            .always(function () { $.LoadingOverlay('hide'); });
    }

    function enviar() {
        var para = $('#pcPara').val().trim();
        if (!para) { message_error('Escriba al menos un correo en «Para».'); return; }
        var programar = !horario.en_horario;
        Swal.fire({icon: 'question', title: programar ? '¿Programar el correo?' : '¿Enviar el correo?',
            html: 'Para <b>' + esc(para) + '</b>' + ($('#pcCc').val().trim() ? '<br>CC ' + esc($('#pcCc').val()) : '') +
                (programar ? '<br><br>Fuera del horario hábil: sale el <b>' + esc(horario.siguiente) + '</b>' : ''),
            showCancelButton: true, confirmButtonText: programar ? 'Sí, programar' : 'Sí, enviar', cancelButtonText: 'Revisar'}).then(function (res) {
            if (!res.isConfirmed) { return; }
            $.LoadingOverlay('show', {text: programar ? 'Generando el PDF y programando…' : 'Generando el PDF y enviando…'});
            $.ajax({url: url, type: 'POST', headers: {'X-CSRFToken': csrftoken}, dataType: 'json',
                data: {plantilla: plantillaId, para: para, cc: $('#pcCc').val(), asunto: $('#pcAsunto').val(), solo_diferencias: soloDiferencias ? '1' : ''}})
                .done(function (r) {
                    if (r.error) { message_error(r.error); return; }
                    bootstrap.Modal.getOrCreateInstance($modal[0]).hide();
                    Swal.fire({icon: 'success', title: r.programado ? 'Correo programado' : 'Correo enviado', text: r.mensaje});
                })
                .fail(function (xhr) { message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo enviar el correo.'); })
                .always(function () { $.LoadingOverlay('hide'); });
        });
    }

    $(function () {
        $modal = $('#modalCorreo');
        if (!$modal.length) { return; }
        url = $modal.data('url');
        $('#pcPlantilla').on('change', function () { cargar(this.value); });
        $('#pcEnviar').on('click', enviar);
        $('#pcEnviados').on('click', '.pc-cancelar-correo', function (e) {
            e.preventDefault();
            var id = $(this).data('id');
            Swal.fire({icon: 'warning', title: '¿Cancelar el correo programado?', text: 'No se enviará al cliente.',
                showCancelButton: true, confirmButtonText: 'Sí, cancelar', cancelButtonText: 'No', confirmButtonColor: '#dc3545'}).then(function (res) {
                if (!res.isConfirmed) { return; }
                $.ajax({url: url, type: 'POST', headers: {'X-CSRFToken': csrftoken}, dataType: 'json', data: {action: 'cancelar_correo', id: id}})
                    .done(function (r) { if (r.error) { message_error(r.error); return; } pintarEnviados(r.enviados || []); toastr.success('Correo programado cancelado.'); })
                    .fail(function (xhr) { message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo cancelar el correo.'); });
            });
        });
        var subiendo = null;
        $('#pcCotizacionesLista').on('click', '.pc-cot-subir', function () {
            subiendo = {tipo: $(this).data('tipo'), id: $(this).data('id')};
            $('#pcCotizacionArchivo').val('').trigger('click');
        });
        $('#pcCotizacionArchivo').on('change', function () {
            var archivo = this.files[0];
            if (!archivo || !subiendo) { return; }
            var datos = new FormData();
            datos.append('action', 'subir_cotizacion');
            datos.append('tipo', subiendo.tipo);
            datos.append('ref_id', subiendo.id);
            datos.append('archivo', archivo);
            cotizacionManual(datos, 'No se pudo adjuntar el PDF.');
        });
        $('#pcCotizacionesLista').on('click', '.pc-cot-quitar', function () {
            var datos = {action: 'quitar_cotizacion', tipo: $(this).data('tipo'), ref_id: $(this).data('id')};
            Swal.fire({icon: 'question', title: '¿Quitar el PDF?', text: 'Ya no se adjuntará la cotización de ' + $(this).data('nombre') + '.',
                showCancelButton: true, confirmButtonText: 'Sí, quitar', cancelButtonText: 'Cancelar'}).then(function (res) {
                if (res.isConfirmed) { cotizacionManual(datos, 'No se pudo quitar el PDF.'); }
            });
        });
        $('#pcCorreoMarco').on('load', function () { ajustarMarco(this); });
        $modal.on('shown.bs.modal', function () { ajustarMarco(document.getElementById('pcCorreoMarco')); });
    });

    return {
        abrir: function (opciones) {
            soloDiferencias = !!(opciones && opciones.soloDiferencias);
            bootstrap.Modal.getOrCreateInstance($modal[0]).show();
            cargar(null);
        }
    };
})();

// «El cliente eligió esta → conviértala en póliza». Uso: convertirPoliza.abrir(vehiculoId, {aseguradoraId, alTerminar}).
var convertirPoliza = {
    modal: null,
    datos: null,
    vehiculoId: null,
    opciones: {},

    esc: function (t) { return $('<div>').text(t == null ? '' : String(t)).html(); },
    dinero: function (v) { return '$' + Number(v || 0).toLocaleString('es-CO', {maximumFractionDigits: 0}); },

    abrir: function (vehiculoId, config) {
        var self = this;
        config = config || {};
        self.vehiculoId = vehiculoId;
        self.alTerminar = config.alTerminar;
        self.modal = self.modal || new bootstrap.Modal(document.getElementById('modalConvertir'));
        $('#cvPlaca').text('');
        $('#cvResumen').text('');
        $('#cvPie').show();
        $('#cvConvertir').prop('disabled', true);
        $('#cvCuerpo').html('<div class="text-center text-muted py-4"><i class="fa-solid fa-spinner fa-spin"></i> Cargando opciones…</div>');
        self.modal.show();
        $.getJSON($('#modalConvertir').data('url'), {vehiculo: vehiculoId}).done(function (d) {
            self.datos = d;
            $('#cvPlaca').text(d.placa);
            self.pintar(config.aseguradoraId);
        }).fail(function (xhr) {
            $('#cvCuerpo').html('<div class="alert alert-danger">' + self.esc((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudieron cargar las opciones.') + '</div>');
        });
    },

    pintar: function (aseguradoraId) {
        var self = this, d = self.datos, e = self.esc, html = '', primera = null, preferida = null;
        self.opciones = {};
        html += '<p class="mb-2">Tomador: <b>' + e(d.tomador) + '</b>. Elige la opción que escogió el cliente; lo demás se copia de la cotización.</p>';
        if (d.vigente) {
            html += '<div class="alert alert-warning py-2 small"><i class="fa-solid fa-triangle-exclamation"></i> Esta placa ya tiene una póliza vigente con <b>' +
                e(d.vigente.aseguradora) + '</b> hasta el ' + d.vigente.vence + '.</div>';
        }
        if (!d.opciones.length) {
            $('#cvCuerpo').html(html + '<div class="alert alert-secondary mb-0">Esta solicitud todavía no tiene valores cotizados para elegir.</div>');
            return;
        }
        d.opciones.forEach(function (g) {
            html += '<div class="cv-grupo"><h6 class="cv-grupo-titulo">' + g.posicion + ' · ' + e(g.aseguradora) + '</h6><div class="cv-opciones">';
            g.opciones.forEach(function (o) {
                self.opciones[o.id] = $.extend({aseguradora: g.aseguradora}, o);
                var barata = g.posicion === 1 && o.comparado;
                if (!primera && barata) { primera = o.id; }
                if (!preferida && aseguradoraId && g.aseguradora_id === aseguradoraId && o.comparado) { preferida = o.id; }
                html += '<label class="cv-opcion"><input type="radio" name="cvOpcion" value="' + e(o.id) + '">' +
                    '<div class="cv-plan">' + (o.plan ? e(o.plan) : 'Valor final') + '</div><div class="cv-valor">' + self.dinero(o.valor) + '</div>' +
                    (barata ? '<span class="cv-marca cv-barata"><i class="fa-solid fa-trophy"></i> Más económica</span>' : (o.comparado && g.opciones.length > 1 ? '<span class="cv-marca cv-comparado">Valor del comparativo</span>' : '')) +
                    '</label>';
            });
            html += '</div></div>';
        });
        var cuotas = '<option value="1">Totalidad (un solo pago)</option>';
        for (var n = 2; n <= d.max_cuotas; n++) { cuotas += '<option value="' + n + '">' + n + ' cuotas mensuales</option>'; }
        var asesores = '<option value="">Seleccione…</option>' + d.asesores.map(function (a) {
            return '<option value="' + a.id + '"' + (a.id === d.asesor_id ? ' selected' : '') + '>' + e(a.nombre) + '</option>';
        }).join('');
        html += '<div class="cv-datos row g-2">' +
            '<div class="col-md-4"><label class="form-label fw-bold small" for="cvCuotas">Forma de pago</label><select class="form-select" id="cvCuotas">' + cuotas + '</select></div>' +
            '<div class="col-md-4"><label class="form-label fw-bold small" for="cvFechaPago">Fecha de pago <span class="text-danger">*</span></label><input type="date" class="form-control" id="cvFechaPago">' +
            '<small class="text-muted">Máxima o de la 1ª cuota.</small></div>' +
            '<div class="col-md-4"><label class="form-label fw-bold small" for="cvRenovacion">Vence (renovación)</label><input type="date" class="form-control" id="cvRenovacion" value="' + d.fecha_renovacion + '"></div>' +
            '<div class="col-md-6"><label class="form-label fw-bold small" for="cvAsesor">Asesor <span class="text-danger">*</span></label><select class="form-select" id="cvAsesor">' + asesores + '</select></div>' +
            '<div class="col-md-6"><label class="form-label fw-bold small" for="cvNumero">Número de póliza</label><input type="text" class="form-control" id="cvNumero" maxlength="50" placeholder="Opcional (se puede poner después)"></div>' +
            '</div>';
        $('#cvCuerpo').html(html);
        var elegir = preferida || primera || Object.keys(self.opciones)[0];
        $('#cvCuerpo input[name="cvOpcion"]').filter(function () { return this.value === elegir; }).prop('checked', true);
        self.actualizar();
    },

    actualizar: function () {
        var o = this.opciones[$('#cvCuerpo input[name="cvOpcion"]:checked').val()];
        $('#cvCuerpo .cv-opcion').each(function () { $(this).toggleClass('activa', $(this).find('input').is(':checked')); });
        if (o && o.cuotas && !this._cuotasTocadas) { $('#cvCuotas').val(o.cuotas); }
        var n = Number($('#cvCuotas').val()) || 1;
        var listo = !!(o && $('#cvFechaPago').val() && $('#cvAsesor').val());
        $('#cvConvertir').prop('disabled', !listo);
        $('#cvResumen').html(o ? 'Se registrará: <b>' + this.esc(o.aseguradora) + (o.plan ? ' · ' + this.esc(o.plan) : '') + '</b> · ' + this.dinero(o.valor) +
            ' · ' + (n > 1 ? n + ' cuotas de ~' + this.dinero(o.valor / n) : 'un solo pago') +
            (!$('#cvFechaPago').val() ? ' · <span class="text-danger fw-bold">falta la fecha de pago</span>' : '') +
            (!$('#cvAsesor').val() ? ' · <span class="text-danger fw-bold">falta el asesor</span>' : '') : '');
    },

    convertir: function () {
        var self = this, $b = $('#cvConvertir').prop('disabled', true);
        $.ajax({
            url: $('#modalConvertir').data('url'), type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
            data: {
                vehiculo: self.vehiculoId, opcion: $('#cvCuerpo input[name="cvOpcion"]:checked').val(), numero_cuotas: $('#cvCuotas').val(),
                fecha_pago: $('#cvFechaPago').val(), fecha_renovacion: $('#cvRenovacion').val(), asesor: $('#cvAsesor').val(), numero_poliza: $('#cvNumero').val()
            }
        }).done(function (r) {
            $('#cvPie').hide();
            $('#cvCuerpo').html('<div class="text-center py-3"><div class="fs-1 text-success"><i class="fa-solid fa-circle-check"></i></div>' +
                '<h5 class="fw-bold">¡Póliza registrada!</h5><p class="mb-3">' + self.esc(r.resumen) + '</p>' +
                '<a class="btn btn-outline-primary rounded-pill" href="' + r.url + '"><i class="fa-solid fa-file-shield"></i> Ver la póliza y sus cuotas</a> ' +
                '<button type="button" class="btn btn-secondary rounded-pill" data-bs-dismiss="modal">Cerrar</button></div>');
            if (typeof self.alTerminar === 'function') { self.alTerminar(r); }
        }).fail(function (xhr) {
            $b.prop('disabled', false);
            message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo registrar la póliza.');
        });
    }
};

$(function () {
    $(document).on('change input', '#cvCuerpo input[name="cvOpcion"], #cvFechaPago, #cvAsesor', function () { convertirPoliza.actualizar(); });
    $(document).on('change', '#cvCuotas', function () { convertirPoliza._cuotasTocadas = true; convertirPoliza.actualizar(); });
    $(document).on('click', '#cvConvertir', function () { convertirPoliza.convertir(); });
    $('#modalConvertir').on('hidden.bs.modal', function () { convertirPoliza._cuotasTocadas = false; });
});

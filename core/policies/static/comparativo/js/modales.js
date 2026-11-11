// Modales del comparativo: pregunta «¿desea agregar valores?» y captura de valores de aseguradoras sin bot.
var comparativoModales = {
    pregunta: null,
    valores: null,
    guardarUrl: null,
    comparativoUrl: null,

    init: function () {
        var self = this;
        var $m2 = $('#modalValores');
        if (!$m2.length) {
            return;
        }
        self.valores = new bootstrap.Modal($m2[0]);
        var elPregunta = document.getElementById('modalPregunta');
        self.pregunta = elPregunta ? new bootstrap.Modal(elPregunta) : null;
        self.guardarUrl = $m2.data('guardar-url');
        self.comparativoUrl = $m2.data('comparativo-url');
        self.soatUrl = $('#modalPregunta').data('soat-url');

        // Primero se guarda el SOAT (si cambió) y luego se sigue: al comparativo, o a registrar valores.
        $('#cmpNoAgregar').on('click', function () {
            var $b = $(this).prop('disabled', true);
            self.guardarSoat().done(function () {
                if (self.soloSoat) { location.reload(); } else { location.href = self.comparativoUrl; }
            }).fail(function () { $b.prop('disabled', false); });
        });
        $('#cmpSiAgregar').on('click', function () {
            var $b = $(this).prop('disabled', true);
            self.guardarSoat().done(function () {
                $b.prop('disabled', false);
                self.pregunta.hide();
                self.abrirValores();
            }).fail(function () { $b.prop('disabled', false); });
        });
        $('#cmpSoatValor').on('input', function () {
            var digitos = this.value.replace(/\D/g, '');
            this.value = digitos ? digitos.replace(/\B(?=(\d{3})+(?!\d))/g, '.') : '';
        });
        $('#cmpSoatFecha').on('input change', function () { self.pintarDias(); });
        $('#cmpOtra').on('click', function () { self.agregarFila(true); });
        $('#cmpFilas').on('click', '.cmp-quitar', function () {
            $(this).closest('.cmp-fila').remove();
            if (!$('#cmpFilas .cmp-fila').length) {
                self.agregarFila(true);
            }
            self.refrescar();
        });
        $('#cmpFilas').on('change', '.cmp-aseguradora', function () { self.refrescar(); });
        // Clic en una pendiente: la pone en una fila vacía (o en una nueva) y lleva el cursor a su valor.
        $('#cmpPendientes').on('click', '.cmp-pend-chip', function () {
            var id = String($(this).data('id'));
            var $vacia = $('#cmpFilas .cmp-aseguradora').filter(function () { return !this.value; }).first();
            if (!$vacia.length) { self.agregarFila(false); $vacia = $('#cmpFilas .cmp-aseguradora').last(); }
            $vacia.val(id);
            self.refrescar();
            $vacia.closest('.cmp-fila').find('.cmp-valor').trigger('focus');
        });
        // Miles con punto mientras se escribe: 1234567 → 1.234.567
        $('#cmpFilas').on('input', '.cmp-valor', function () {
            var digitos = this.value.replace(/\D/g, '');
            this.value = digitos ? digitos.replace(/\B(?=(\d{3})+(?!\d))/g, '.') : '';
        });
        $('#cmpAceptar').on('click', function () { self.guardar($(this)); });
    },

    // Desde el listado: se conoce la solicitud por la fila donde se hizo clic.
    // `faltantes`: [{id, nombre}] de las aseguradoras sin ningún valor para esta placa (ni del bot ni a mano). Si no
    // falta ninguna (o el usuario no puede registrar valores) la pregunta de valores no aparece.
    // `permitidas`: ids de las aseguradoras a las que se les puede registrar valor en esta solicitud (las sin bot y
    // las con bot que no trajeron valor). En la página del comparativo la lista ya viene filtrada (null).
    // Siempre se abre: arriba el SOAT del vehículo; abajo, solo si faltan aseguradoras sin bot, la pregunta de valores.
    abrirPregunta: function (id, placa, faltantes, puedeRegistrar, permitidas, soatValor, soatVencimiento) {
        this.permitidas = permitidas || null;
        this.soloSoat = false;
        this.establecer(id, placa);
        var preguntar = !!(puedeRegistrar && faltantes && faltantes.length);
        // El SOAT ya registrado (valor y fecha, sin vencer) no se vuelve a pedir: se corrige con «Editar» en el comparativo.
        var hoy = new Date(), hoyTxt = hoy.getFullYear() + '-' + ('0' + (hoy.getMonth() + 1)).slice(-2) + '-' + ('0' + hoy.getDate()).slice(-2);
        var soatListo = !!(soatValor && soatVencimiento && soatVencimiento >= hoyTxt);
        if (soatListo && !preguntar) {
            location.href = this.comparativoUrl;
            return;
        }
        $('#modalPregunta .cmp-soat').prop('hidden', soatListo);
        $('#cmpSeccionValores').toggleClass('cmp-sin-borde', soatListo);
        this.faltantes = preguntar ? faltantes : [];
        $('#cmpFaltantes').text(preguntar ? 'Sin valor todavía: ' + faltantes.map(function (f) { return f.nombre; }).join(', ') + '.' : '');
        $('#cmpSeccionValores').prop('hidden', !preguntar);
        $('#cmpSiAgregar').prop('hidden', !preguntar);
        $('#cmpNoAgregar span').text('Ver comparativo');
        this.cargarSoat(soatValor, soatVencimiento);
        this.pregunta.show();
    },

    // Desde la página del comparativo: solo el SOAT; al guardar se recarga para verlo en la ficha.
    abrirSoat: function (placa, soatValor, soatVencimiento) {
        this.soloSoat = true;
        $('#modalPregunta .cmp-soat').prop('hidden', false);
        $('.cmp-placa').text(placa || '');
        $('#cmpSeccionValores, #cmpSiAgregar').prop('hidden', true);
        $('#cmpNoAgregar span').text('Guardar');
        this.cargarSoat(soatValor, soatVencimiento);
        this.pregunta.show();
    },

    cargarSoat: function (valor, vencimiento) {
        var texto = valor ? String(valor).replace(/\B(?=(\d{3})+(?!\d))/g, '.') : '';
        $('#cmpSoatValor').val(texto);
        $('#cmpSoatFecha').val(vencimiento || '');
        this.soatInicial = texto + '|' + (vencimiento || '');
        this.pintarDias();
    },

    // Días que le quedan al SOAT desde hoy, mientras se escribe la fecha.
    pintarDias: function () {
        var $d = $('#cmpSoatDias'), fecha = $('#cmpSoatFecha').val();
        if (!fecha) { $d.prop('hidden', true); return; }
        var p = fecha.split('-'), hoy = new Date();
        var vence = new Date(+p[0], +p[1] - 1, +p[2]);
        var base = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
        var dias = Math.round((vence - base) / 86400000);
        var clase = dias < 0 ? 'vencido' : dias <= 30 ? 'pronto' : 'ok';
        var texto = dias < 0 ? 'SOAT vencido hace ' + (-dias) + (dias === -1 ? ' día' : ' días')
            : dias === 0 ? 'El SOAT vence hoy' : 'Le quedan ' + dias + (dias === 1 ? ' día' : ' días') + ' de vigencia';
        $d.attr('class', 'cmp-soat-dias ' + clase).html('<i class="fa-regular fa-calendar-check"></i> ' + texto).prop('hidden', false);
    },

    guardarSoat: function () {
        var valor = $('#cmpSoatValor').val(), fecha = $('#cmpSoatFecha').val();
        var listo = $.Deferred();
        if (valor + '|' + fecha === this.soatInicial || !this.soatUrl) {
            return listo.resolve().promise();
        }
        $.ajax({
            url: this.soatUrl, type: 'POST', headers: {'X-CSRFToken': csrftoken}, dataType: 'json',
            data: {soat_valor: valor.replace(/\D/g, ''), soat_vencimiento: fecha}
        }).done(function () { listo.resolve(); }).fail(function (xhr) {
            toastr.error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo guardar el SOAT. Intenta nuevamente.');
            listo.reject();
        });
        return listo.promise();
    },

    establecer: function (id, placa) {
        var $m2 = $('#modalValores');
        this.guardarUrl = $m2.data('guardar-url-plantilla') ? $m2.data('guardar-url-plantilla').replace('/0/', '/' + id + '/') : this.guardarUrl;
        this.comparativoUrl = $m2.data('comparativo-url-plantilla') ? $m2.data('comparativo-url-plantilla').replace('/0/', '/' + id + '/') : this.comparativoUrl;
        var $m1 = $('#modalPregunta');
        this.soatUrl = $m1.data('soat-url-plantilla') ? $m1.data('soat-url-plantilla').replace('/0/', '/' + id + '/') : $m1.data('soat-url');
        $('.cmp-placa').text(placa || '');
    },

    // `faltantes`: [{id, nombre}] de las aseguradoras sin ningún valor (sin bot que nadie informó y con bot que falló).
    abrirValores: function () {
        $('#cmpFilas').empty();
        if ($('#cmpPlantilla').length) {
            this.agregarFila(true);   // ya con la primera pendiente elegida
        }
        this.refrescar();
        this.valores.show();
    },

    agregarFila: function (elegirPendiente) {
        var $fila = $(document.getElementById('cmpPlantilla').content.cloneNode(true));
        var permitidas = this.permitidas;
        if (permitidas) {
            $fila.find('.cmp-aseguradora option').each(function () {
                if (this.value && permitidas.indexOf(parseInt(this.value, 10)) === -1) { $(this).remove(); }
            });
        }
        $('#cmpFilas').append($fila);
        if (elegirPendiente) {
            var siguiente = this.pendientes()[0];
            var $select = $('#cmpFilas .cmp-aseguradora').last();
            if (siguiente && $select.find('option[value="' + siguiente.id + '"]').length) { $select.val(String(siguiente.id)); }
        }
        this.refrescar();
    },

    elegidas: function () {
        return $('#cmpFilas .cmp-aseguradora').map(function () { return this.value; }).get().filter(Boolean);
    },

    // Las que todavía no tienen valor y no están elegidas en ninguna fila.
    pendientes: function () {
        var elegidas = this.elegidas();
        return (this.faltantes || []).filter(function (f) { return elegidas.indexOf(String(f.id)) === -1; });
    },

    // Una aseguradora elegida en una fila no aparece en las listas de las otras; y se actualiza la línea de pendientes.
    refrescar: function () {
        var $selects = $('#cmpFilas .cmp-aseguradora');
        $selects.each(function () {
            var propia = this.value;
            var otras = $selects.not(this).map(function () { return this.value; }).get().filter(Boolean);
            $(this).find('option').each(function () {
                var ocultar = !!this.value && this.value !== propia && otras.indexOf(this.value) !== -1;
                this.hidden = ocultar;
                this.disabled = ocultar;
            });
        });
        var $caja = $('#cmpPendientes');
        if (!(this.faltantes || []).length) { $caja.prop('hidden', true); return; }
        var pendientes = this.pendientes();
        if (!pendientes.length) {
            $caja.attr('class', 'cmp-pendientes listo').html('<i class="fa-solid fa-circle-check"></i> Ya están todas las aseguradoras que faltaban.').prop('hidden', false);
            return;
        }
        var chips = pendientes.map(function (f) {
            return '<span class="cmp-pend-chip" role="button" data-id="' + f.id + '"><i class="fa-solid fa-plus"></i> ' + $('<div>').text(f.nombre).html() + '</span>';
        }).join('');
        $caja.attr('class', 'cmp-pendientes').html('<b><i class="fa-solid fa-hourglass-half"></i> Pendientes por agregar valor:</b>' + chips).prop('hidden', false);
    },

    guardar: function ($boton) {
        var self = this, filas = [], error = null;
        $('#cmpFilas .cmp-fila').each(function (i) {
            var aseguradora = $(this).find('.cmp-aseguradora').val();
            var valor = $(this).find('.cmp-valor').val().replace(/\D/g, '');
            if (!aseguradora && !valor) {
                return;  // fila vacía: se ignora
            }
            if (!aseguradora) { error = 'Elige la aseguradora de la fila ' + (i + 1); return false; }
            if (!valor || parseInt(valor, 10) <= 0) { error = 'Escribe un valor mayor que cero en la fila ' + (i + 1); return false; }
            filas.push({aseguradora: aseguradora, valor: valor});
        });
        if (!error && !filas.length) {
            error = 'Elige una aseguradora e indica su valor';
        }
        if (!error) {
            var repetidas = filas.map(function (f) { return f.aseguradora; });
            if (repetidas.some(function (a, i) { return repetidas.indexOf(a) !== i; })) {
                error = 'Hay una aseguradora repetida: registra un solo valor por aseguradora';
            }
        }
        if (error) {
            toastr.error(error);
            return;
        }
        $boton.prop('disabled', true);
        $.ajax({
            url: self.guardarUrl,
            type: 'POST',
            headers: {'X-CSRFToken': csrftoken},
            data: {valores: JSON.stringify(filas)},
            dataType: 'json'
        }).done(function (response) {
            location.href = response.url || self.comparativoUrl;
        }).fail(function (xhr) {
            $boton.prop('disabled', false);
            toastr.error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudieron guardar los valores. Intenta nuevamente.');
        });
    }
};

$(function () {
    comparativoModales.init();
});

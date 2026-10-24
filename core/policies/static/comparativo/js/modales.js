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

        $('#cmpNoAgregar').on('click', function () {
            location.href = self.comparativoUrl;
        });
        $('#cmpSiAgregar').on('click', function () {
            self.pregunta.hide();
            self.abrirValores();
        });
        $('#cmpOtra').on('click', function () { self.agregarFila(); });
        $('#cmpFilas').on('click', '.cmp-quitar', function () {
            $(this).closest('.cmp-fila').remove();
            if (!$('#cmpFilas .cmp-fila').length) {
                self.agregarFila();
            }
        });
        // Miles con punto mientras se escribe: 1234567 → 1.234.567
        $('#cmpFilas').on('input', '.cmp-valor', function () {
            var digitos = this.value.replace(/\D/g, '');
            this.value = digitos ? digitos.replace(/\B(?=(\d{3})+(?!\d))/g, '.') : '';
        });
        $('#cmpAceptar').on('click', function () { self.guardar($(this)); });
    },

    // Desde el listado: se conoce la solicitud por la fila donde se hizo clic.
    // `faltantes`: nombres de las aseguradoras sin bot que aún no tienen valor para esta placa. Si no falta ninguna
    // (o el usuario no puede registrar valores) no hay nada que preguntar: se abre el comparativo directamente.
    abrirPregunta: function (id, placa, faltantes, puedeRegistrar) {
        this.establecer(id, placa);
        if (!puedeRegistrar || !faltantes || !faltantes.length) {
            location.href = this.comparativoUrl;
            return;
        }
        this.faltantes = faltantes;
        $('#cmpFaltantes').text('Faltan los valores de: ' + faltantes.join(', ') + '.');
        this.pregunta.show();
    },

    establecer: function (id, placa) {
        var $m2 = $('#modalValores');
        this.guardarUrl = $m2.data('guardar-url-plantilla') ? $m2.data('guardar-url-plantilla').replace('/0/', '/' + id + '/') : this.guardarUrl;
        this.comparativoUrl = $m2.data('comparativo-url-plantilla') ? $m2.data('comparativo-url-plantilla').replace('/0/', '/' + id + '/') : this.comparativoUrl;
        $('.cmp-placa').text(placa || '');
    },

    abrirValores: function () {
        $('#cmpFilas').empty();
        if ($('#cmpPlantilla').length) {
            this.agregarFila();
            // Se deja elegida la primera aseguradora que aún no tiene valor.
            var $primera = $('#cmpFilas .cmp-aseguradora').first();
            var faltante = (this.faltantes || [])[0];
            if (faltante) {
                var opcion = $primera.find('option').filter(function () { return $(this).text() === faltante; }).val();
                if (opcion) { $primera.val(opcion); }
            }
        }
        this.valores.show();
    },

    agregarFila: function () {
        var $fila = $(document.getElementById('cmpPlantilla').content.cloneNode(true));
        $('#cmpFilas').append($fila);
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

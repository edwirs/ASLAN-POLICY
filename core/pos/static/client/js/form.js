var input_birthdate;

$(function () {
    input_birthdate = $('input[name="birthdate"]');

    input_birthdate.datetimepicker({
        useCurrent: false,
        format: 'YYYY-MM-DD',
        locale: 'es',
        keepOpen: false,
        maxDate: new Date()
    });

    // Inicializa Select2 para todos los selects con la clase, incluyendo document_type, gender y municipality
    $('.select2').select2({
        language: 'es',
        theme: 'bootstrap4'
    });

    // Forzar el funcionamiento de las pestañas de AdminLTE/Bootstrap de forma global
    $(document).on('click', '#client-tabs a', function (e) {
        e.preventDefault();
        $(this).tab('show');
    });

    // 1. Seleccionar NIT por defecto al cargar (si está vacío)
    var selectDocType = $('select[name="document_type"]');
    if (selectDocType.length && !selectDocType.val()) {
        selectDocType.find('option').each(function () {
            if ($(this).text().toUpperCase().includes('NIT')) {
                selectDocType.val($(this).val()).trigger('change');
                return false;
            }
        });
    }

    // 2. Seleccionar género "Masculino" por defecto
    var selectGender = $('select[name="gender"]');
    if (selectGender.length && !selectGender.val()) {
        selectGender.val('male').trigger('change');
    }

    // Función para calcular el Dígito de Verificación (DV) por Módulo 11 (DIAN Colombia)
    function calculateDV(dni) {
        if (!dni || isNaN(dni)) return '';
        
        var vpri = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71];
        var x = 0;
        var y = 0;
        var z = dni.length;

        for (var i = 0; i < z; i++) {
            y = parseInt(dni.substr(i, 1));
            x += (y * vpri[z - i - 1]);
        }

        var y = x % 11;
        return (y > 1) ? (11 - y) : y;
    }

    // Aplicar el atributo readonly al campo DV para que no sea editable manualmente
    var inputDv = $('input[name="dv"]');
    inputDv.attr('readonly', true);

    // Evento para calcular automáticamente el DV al salir del campo DNI (blur o tabular)
    var inputDni = $('input[name="dni"]');
    inputDni.on('blur', function () {
        var dniValue = $(this).val().trim();
        if (dniValue !== '') {
            var calculatedDv = calculateDV(dniValue);
            inputDv.val(calculatedDv);
        } else {
            inputDv.val('');
        }
    });

    // Botón "Consultar en DIAN": autocompleta nombres/razón social y correo
    // consultando la identificación ante la DIAN (vía Factus). Solo se habilita
    // cuando hay algo escrito en el campo de identificación.
    var btnConsultDian = $('#btnConsultDian');

    function toggleConsultDianButton() {
        btnConsultDian.prop('disabled', inputDni.val().trim() === '');
    }
    inputDni.on('input keyup change', toggleConsultDianButton);
    toggleConsultDianButton();

    btnConsultDian.on('click', function () {
        var dni = inputDni.val().trim();
        if (dni === '') return;

        $.ajax({
            url: '/pos/client/consult_dian/',
            type: 'POST',
            headers: {'X-CSRFToken': csrftoken},
            data: {
                document_type: selectDocType.val(),
                dni: dni
            },
            dataType: 'json',
            beforeSend: function () {
                btnConsultDian.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Consultando...');
            },
            success: function (data) {
                if (data.error) {
                    return message_error(data.error);
                }
                if (data.name) {
                    $('input[name="names"]').val(data.name);
                }
                if (data.email) {
                    $('input[name="email"]').val(data.email);
                }
                alert_sweetalert({
                    'type': 'success',
                    'message': 'Datos consultados exitosamente en la DIAN',
                    'timer': 1500,
                    'callback': function () {}
                });
            },
            error: function () {
                message_error('Ocurrió un error al consultar en la DIAN');
            },
            complete: function () {
                btnConsultDian.html('<i class="fas fa-id-card"></i> Consultar en DIAN');
                toggleConsultDianButton();
            }
        });
    });

    // Función para manejar la visibilidad, clases y valores según si es NIT o no
    function evaluateDocumentType() {
        var selectedText = selectDocType.find('option:selected').text().toUpperCase();
        
        var dvInputWrapper = inputDv.closest('.input-group-append');
        var namesContainer = $('#container-names');
        var commercialNameContainer = $('#container-commercial');
        var personTypeContainer = $('select[name="person_type"]').closest('.form-group');
        var taxRespContainer = $('select[name="tax_responsibility"]').closest('.form-group');

        if (selectedText.includes('NIT')) {
            dvInputWrapper.show();
            $('#row-propietario-empresa').show();
            commercialNameContainer.show();
            personTypeContainer.show();
            taxRespContainer.show();
            namesContainer.removeClass('col-lg-12').addClass('col-lg-6');
            
            // Si ya hay un DNI escrito al cambiar a NIT, calcula el DV de inmediato
            if (inputDni.val().trim() !== '') {
                inputDv.val(calculateDV(inputDni.val().trim()));
            }
        } else {
            dvInputWrapper.hide();
            $('#row-propietario-empresa').hide();
            $('input[name="propietario_documento"], input[name="propietario_nombre"]').val('');
            commercialNameContainer.hide();
            personTypeContainer.hide();
            taxRespContainer.hide();
            
            inputDv.val('');
            $('input[name="commercial_name"]').val('');
            namesContainer.removeClass('col-lg-6').addClass('col-lg-12');

            var selectPersonType = $('select[name="person_type"]');
            selectPersonType.val('natural').trigger('change');

            var selectTaxResp = $('select[name="tax_responsibility"]');
            selectTaxResp.val('no_responsable').trigger('change');
        }
    }

    evaluateDocumentType();

    // Otro celular y otro correo: solo se ven si el cliente tiene más datos de contacto. Al apagarlo se borran.
    function evaluarMasContacto() {
        var activo = $('#chkMasContacto').is(':checked');
        $('#row-mas-contacto').toggle(activo);
        if (!activo) {
            $('input[name="phone"], input[name="email_secundario"]').val('');
        }
    }
    $('#chkMasContacto').on('change', evaluarMasContacto);
    evaluarMasContacto();

    selectDocType.on('change', function () {
        evaluateDocumentType();
    });

    // 3. Lógica para añadir contactos adicionales con validación de SweetAlert2
    $('#add-contact').on('click', function () {
        var totalForms = $('input[name$="-TOTAL_FORMS"]');
        
        if (!totalForms.length) {
            var defaultPrefix = 'clientcontact_set';
            var initialCount = $('#contacts-container .contact-row:visible').length;
            
            $('<input>').attr({
                type: 'hidden',
                name: defaultPrefix + '-TOTAL_FORMS',
                id: 'id_' + defaultPrefix + '-TOTAL_FORMS',
                value: initialCount
            }).appendTo('#frmForm');
            
            totalForms = $('input[name$="-TOTAL_FORMS"]');
        }

        // VALIDACIÓN: Verificar si hay una fila anterior visible y si le faltan Nombres o Correo
        var visibleRows = $('#contacts-container .contact-row:visible');
        if (visibleRows.length > 0) {
            var lastRow = visibleRows.last();
            var nameInput = lastRow.find('input[name*="-names"]');
            var emailInput = lastRow.find('input[name*="-email"]');

            if (nameInput.val().trim() === '' || emailInput.val().trim() === '') {
                Swal.fire({
                    title: '¡Atención!',
                    text: 'Por favor complete los campos de "Nombres" y "Correo" del contacto actual antes de añadir uno nuevo.',
                    icon: 'warning',
                    confirmButtonText: 'Entendido',
                    confirmButtonColor: '#007bff'
                }).then(() => {
                    nameInput.focus();
                });
                return;
            }
        }

        var formCount = parseInt(totalForms.val());
        var totalFormsName = totalForms.attr('name');
        var prefix = totalFormsName.replace('-TOTAL_FORMS', '');
        
        var template = $('#contact-template').html();
        
        if (!template) {
            console.error("No se encontró el elemento con ID #contact-template.");
            return;
        }

        var compiledHtml = template.replace(/__prefix__/g, formCount);
        
        if (prefix !== 'clientcontact_set') {
            compiledHtml = compiledHtml.replace(/clientcontact_set/g, prefix);
        }
        
        $('#contacts-container').append(compiledHtml);
        totalForms.val(formCount + 1);
    });

    // 4. Lógica para eliminar una fila de contacto dinámicamente
    $(document).on('click', '.remove-contact', function () {
        var row = $(this).closest('.contact-row');
        
        var idInput = row.find('input[name*="-id"]');
        var deleteCheckbox = row.find('input[name*="-DELETE"]');

        if (idInput.val() && idInput.val() !== '') {
            deleteCheckbox.prop('checked', true);
            row.hide();
        } else {
            row.remove();
        }
    });

    // Validaciones de teclas permitidas
    $('input[name="names"]')
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'letters'});
        });

    $('input[name="dni"]')
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });

    $('input[name="mobile"]')
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'numbers'});
        });
});
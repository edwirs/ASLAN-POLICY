var wizardState = {
    service_type: null,
    service_type_code: null,
    client: null,
    clients: []
};

function showStep(n) {
    $('.wizard-panel').addClass('d-none');
    $('#panel-step-' + n).removeClass('d-none');
    $('.wizard-step-indicator').each(function () {
        var step = parseInt($(this).data('step'));
        $(this).removeClass('active completed');
        if (step === n) {
            $(this).addClass('active');
        } else if (step < n) {
            $(this).addClass('completed');
        }
    });
}

function loadClients() {
    $.ajax({
        url: pathname,
        type: 'POST',
        headers: {'X-CSRFToken': csrftoken},
        data: {action: 'get_clients', service_type: wizardState.service_type},
        dataType: 'json',
        beforeSend: function () {
            loading({'text': 'Cargando clientes...'});
        },
        success: function (response) {
            if (response.hasOwnProperty('error')) {
                message_error(response.error);
                return;
            }
            wizardState.clients = response;
            var select = $('#select-client');
            select.empty().append('<option value="">---------</option>');
            response.forEach(function (c) {
                select.append('<option value="' + c.id + '">' + c.text + '</option>');
            });
            select.val('').trigger('change');
        },
        error: function (jqXHR, textStatus, errorThrown) {
            message_error(errorThrown + ' ' + textStatus);
        },
        complete: function () {
            $.LoadingOverlay('hide');
        }
    });
}

function loadRates() {
    $.ajax({
        url: pathname,
        type: 'POST',
        headers: {'X-CSRFToken': csrftoken},
        data: {action: 'get_client_rates', client: wizardState.client},
        dataType: 'json',
        beforeSend: function () {
            loading({'text': 'Cargando servicios...'});
        },
        success: function (response) {
            if (response.hasOwnProperty('error')) {
                message_error(response.error);
                return;
            }
            var container = $('#rates-list').empty();
            if (response.length === 0) {
                container.append('<div class="text-muted p-3">Este cliente no tiene servicios/tarifas configuradas. Puede asignarlas en Servicios &gt; Servicios por entidad.</div>');
            }
            response.forEach(function (rate) {
                var productName = rate.product.short_name || rate.product.name;
                var checkboxId = 'rate-' + rate.id;
                var item = $(
                    '<div class="list-group-item">' +
                    '<div class="d-flex justify-content-between align-items-center">' +
                    '<div class="form-check">' +
                    '<input type="checkbox" class="form-check-input rate-checkbox" id="' + checkboxId + '" value="' + rate.id + '" data-price="' + rate.price + '">' +
                    '<label class="form-check-label" for="' + checkboxId + '">' + productName + '</label>' +
                    '</div>' +
                    '<span class="fw-bold">' + formatCurrency(rate.price) + '</span>' +
                    '</div>' +
                    '<div class="mt-2">' +
                    '<input type="text" class="form-control form-control-sm rate-auth-input" placeholder="Número de autorización (opcional)">' +
                    '</div>' +
                    '</div>'
                );
                container.append(item);
            });
            updateRatesTotal();
        },
        error: function (jqXHR, textStatus, errorThrown) {
            message_error(errorThrown + ' ' + textStatus);
        },
        complete: function () {
            $.LoadingOverlay('hide');
        }
    });
}

function formatCurrency(value) {
    return new Intl.NumberFormat('es-CO', {
        style: 'currency',
        currency: 'COP',
        minimumFractionDigits: 0
    }).format(value);
}

function updateRatesTotal() {
    var total = 0;
    $('.rate-checkbox:checked').each(function () {
        total += parseFloat($(this).data('price'));
    });
    $('#rates-total').text(formatCurrency(total));
}

function saveReception() {
    var deceasedName = $('#deceased_name').val().trim();
    if (!wizardState.service_type || !wizardState.client) {
        message_error('Debe seleccionar el tipo de servicio y el cliente');
        return;
    }
    if (!deceasedName) {
        message_error('El nombre del fallecido es obligatorio');
        showStep(3);
        return;
    }

    var formData = new FormData();
    formData.append('action', 'save');
    formData.append('service_type', wizardState.service_type);
    formData.append('client', wizardState.client);
    formData.append('contact_1_name', $('#contact_1_name').val());
    formData.append('contact_1_phone', $('#contact_1_phone').val());
    formData.append('contact_2_name', $('#contact_2_name').val());
    formData.append('contact_2_phone', $('#contact_2_phone').val());
    formData.append('authorized_by', $('#authorized_by').val());
    formData.append('deceased_name', deceasedName);
    formData.append('deceased_document', $('#deceased_document').val());
    formData.append('death_certificate_number', $('#death_certificate_number').val());
    formData.append('death_city', $('#death_city').val());
    formData.append('death_place', $('#death_place').val());
    formData.append('final_destination_city', $('#final_destination_city').val());
    formData.append('disposition_type', $('#disposition_type').val());
    $('.rate-checkbox:checked').each(function () {
        var authInput = $(this).closest('.list-group-item').find('.rate-auth-input');
        formData.append('rate_ids[]', $(this).val());
        formData.append('authorization_numbers[]', authInput.val() || '');
    });

    $.ajax({
        url: pathname,
        type: 'POST',
        headers: {'X-CSRFToken': csrftoken},
        data: formData,
        processData: false,
        contentType: false,
        dataType: 'json',
        beforeSend: function () {
            loading({'text': 'Guardando...'});
        },
        success: function (response) {
            if (response.hasOwnProperty('error')) {
                message_error(response.error);
                return;
            }
            alert_sweetalert({
                'type': 'success',
                'message': 'Recepción registrada correctamente',
                'timer': 2000,
                'callback': function () {
                    location.href = serviceReceptionListUrl;
                }
            });
        },
        error: function (jqXHR, textStatus, errorThrown) {
            message_error(errorThrown + ' ' + textStatus);
        },
        complete: function () {
            $.LoadingOverlay('hide');
        }
    });
}

$(function () {
    $('.select2').select2({
        language: 'es',
        theme: 'bootstrap4'
    });

    showStep(1);

    $(document).on('click', '.service-type-card', function () {
        $('.service-type-card').removeClass('selected');
        $(this).addClass('selected');
        wizardState.service_type = $(this).data('id');
        wizardState.service_type_code = $(this).data('code');
        $('#btn-step1-next').prop('disabled', false);
    });

    $('#btn-step1-next').on('click', function () {
        $('#step2-type-label').text($('.service-type-card.selected h5').text());
        $('#select-client').val('').trigger('change');
        $('#client-preview').addClass('d-none');
        $('#agreement-contacts').addClass('d-none');
        $('#btn-step2-next').prop('disabled', true);
        showStep(2);
        loadClients();
    });

    $('#select-client').on('change', function () {
        var clientId = $(this).val();
        wizardState.client = clientId || null;

        if (!clientId) {
            $('#client-preview').addClass('d-none');
            $('#agreement-contacts').addClass('d-none');
            $('#btn-step2-next').prop('disabled', true);
            return;
        }

        var client = wizardState.clients.find(function (c) {
            return String(c.id) === String(clientId);
        });

        if (client) {
            $('#preview-name').val(client.names || '');
            $('#preview-dni').val(client.dni || '');
            $('#preview-phone').val(client.mobile || '');
            $('#preview-email').val(client.email || '');
            $('#client-preview').removeClass('d-none');
        }

        if (wizardState.service_type_code === 'agreement') {
            $('#agreement-contacts').removeClass('d-none');
        } else {
            $('#agreement-contacts').addClass('d-none');
        }

        $('#btn-step2-next').prop('disabled', false);
    });

    $('#btn-step2-next').on('click', function () {
        showStep(3);
    });

    $('#btn-step3-next').on('click', function () {
        var deceasedName = $('#deceased_name').val().trim();
        if (!deceasedName) {
            message_error('El nombre del fallecido es obligatorio');
            return;
        }
        showStep(4);
        loadRates();
    });

    $(document).on('change', '.rate-checkbox', updateRatesTotal);

    $(document).on('click', '.btn-wizard-prev', function () {
        showStep(parseInt($(this).data('prev')));
    });

    $('#btn-save').on('click', saveReception);
});

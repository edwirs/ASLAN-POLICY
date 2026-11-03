// Plantillas de correo: activar/inactivar plantillas, probar cuentas y subir o quitar firmas.
$(function () {
    function enviar(datos, ok, archivo) {
        $.LoadingOverlay('show');
        $.ajax({
            url: window.location.pathname, type: 'POST', headers: {'X-CSRFToken': csrftoken},
            data: datos, dataType: 'json',
            processData: !archivo, contentType: archivo ? false : 'application/x-www-form-urlencoded; charset=UTF-8'
        }).done(function (r) {
            if (r.error) { message_error(r.error); return; }
            ok(r);
        }).fail(function (xhr) {
            message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo completar la acción.');
        }).always(function () { $.LoadingOverlay('hide'); });
    }

    $('.pc-estado').on('change', function () {
        var $c = $(this);
        enviar({action: 'plantilla_estado', id: $c.data('id'), activar: $c.is(':checked')}, function () {}, false);
    });

    $('.pc-probar').on('click', function () {
        var id = $(this).data('id');
        enviar({action: 'cuenta_probar', id: id}, function (r) {
            Swal.fire({icon: r.ok ? 'success' : 'error', title: r.ok ? 'La cuenta funciona' : 'La cuenta no funciona', text: r.mensaje})
                .then(function () { location.reload(); });
        }, false);
    });

    $('.pc-firma-archivo').on('change', function () {
        if (!this.files.length) { return; }
        var datos = new FormData();
        datos.append('action', 'firma_guardar');
        datos.append('usuario', $(this).data('usuario') || '');
        datos.append('imagen', this.files[0]);
        enviar(datos, function () { location.reload(); }, true);
    });

    $('.pc-firma-quitar').on('click', function () {
        var usuario = $(this).data('usuario') || '';
        Swal.fire({icon: 'question', title: '¿Quitar la firma?', text: 'Los correos llevarán la firma de texto.', showCancelButton: true,
            confirmButtonText: 'Sí, quitar', cancelButtonText: 'Cancelar'}).then(function (r) {
            if (r.isConfirmed) { enviar({action: 'firma_quitar', usuario: usuario}, function () { location.reload(); }, false); }
        });
    });
});

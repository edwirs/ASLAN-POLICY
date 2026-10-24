var asesor = {
    esc: function (texto) {
        return $('<div>').text(texto == null ? '' : String(texto)).html();
    },

    vacio: function (valor) {
        return valor ? asesor.esc(valor) : '<span class="text-muted">—</span>';
    },

    list: function () {
        $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: {'action': 'search'},
                dataSrc: ""
            },
            columns: [
                {data: "nombres"},
                {data: "tipo"},
                {data: "empresa"},
                {data: "correo"},
                {data: "porcentaje_comision"},
                {data: "is_active"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [0],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + row.documento;
                        }
                        var acceso = row.usuario ? ' <i class="fa-solid fa-user-check text-success" data-bs-toggle="tooltip" title="Entra al sistema como «' + asesor.esc(row.usuario) + '»"></i>' : '';
                        return '<b>' + asesor.esc(data) + '</b>' + acceso + '<br><small class="text-muted">' + asesor.esc(row.documento) + '</small>';
                    }
                },
                {
                    targets: [1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return row.tipo_display;
                        }
                        return data === 'externo'
                            ? '<span class="badge rounded-pill bg-warning text-dark"><i class="fa-solid fa-handshake"></i> Externo</span>'
                            : '<span class="badge rounded-pill bg-secondary"><i class="fa-solid fa-house-user"></i> Interno</span>';
                    }
                },
                {
                    targets: [2],
                    render: function (data, type) {
                        return type === 'display' ? asesor.vacio(data) : (data || '');
                    }
                },
                {
                    targets: [3],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + row.telefono;
                        }
                        return '<div>' + asesor.esc(data) + '</div><small class="text-muted">' + asesor.esc(row.telefono) + '</small>';
                    }
                },
                {
                    targets: [4],
                    class: 'text-center',
                    render: function (data, type) {
                        return type === 'display' ? '<b>' + Number(data).toLocaleString('es-CO', {maximumFractionDigits: 2}) + ' %</b>' : data;
                    }
                },
                {
                    targets: [5],
                    class: 'text-center',
                    orderable: false,
                    render: function (data, type, row) {
                        // Un solo botón que dice el estado; al hacer clic cambia al contrario.
                        var etiqueta = data ? '<i class="fas fa-check"></i> Activo' : '<i class="fas fa-ban"></i> Inactivo';
                        if (!puedeEditar) {
                            return '<span class="badge rounded-pill ' + (data ? 'bg-success' : 'bg-secondary') + '">' + etiqueta + '</span>';
                        }
                        return '<button type="button" class="btn btn-sm rounded-pill btn-estado ' + (data ? 'btn-success' : 'btn-outline-secondary') + '" rel="toggle"' +
                            ' data-activar="' + (data ? 'false' : 'true') + '" data-id="' + row.id + '" data-nombre="' + asesor.esc(row.nombres) + '"' +
                            ' data-bs-toggle="tooltip" title="' + (data ? 'Clic para inactivar' : 'Clic para activar') + '">' + etiqueta + '</button>';
                    }
                },
                {
                    targets: [6],
                    class: 'text-center',
                    orderable: false,
                    render: function (data) {
                        return puedeEditar
                            ? '<a href="' + pathname + data + '/editar/" data-bs-toggle="tooltip" title="Editar asesor" class="btn btn-warning btn-sm rounded-pill"><i class="fas fa-edit"></i></a>'
                            : '<span class="text-muted">—</span>';
                    }
                },
            ],
            initComplete: function () {
                enable_tooltip();
            }
        });
    }
};

$(function () {
    toastr.options = {closeButton: true, progressBar: true, positionClass: 'toast-top-right', timeOut: '3500'};
    asesor.list();

    $('#data tbody').off().on('click', 'button[rel="toggle"]', function () {
        $('.tooltip').remove();
        var activar = $(this).data('activar') === true || $(this).data('activar') === 'true';
        var id = $(this).data('id');
        var nombre = $(this).data('nombre');
        dialog_action({
            'content': activar
                ? '¿Activar a ' + nombre + '?'
                : '¿Inactivar a ' + nombre + '? Conserva su historial, pero dejará de poder usarse.',
            'success': function () {
                $.ajax({
                    url: pathname,
                    type: 'POST',
                    headers: {'X-CSRFToken': csrftoken},
                    data: {action: 'toggle', id: id, activar: activar},
                    dataType: 'json',
                    success: function (data) {
                        if (data.error) {
                            return message_error(data.error);
                        }
                        toastr.success(nombre + (activar ? ' activado' : ' inactivado'));
                        asesor.list();
                    },
                    error: function () {
                        message_error('Ocurrió un error al cambiar el estado del asesor');
                    }
                });
            },
            'cancel': function () {}
        });
    });
});

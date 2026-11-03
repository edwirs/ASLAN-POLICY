var aseguradora = {
    list: function () {
        $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            // En pantallas angostas las columnas menos importantes pasan al «+» en vez de salirse de la tarjeta.
            responsive: true,
            paging: false,
            searching: false,
            info: false,
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: {'action': 'search'},
                dataSrc: ""
            },
            columns: [
                {data: "name", responsivePriority: 1},
                {data: "portal_url", responsivePriority: 5},
                {data: "username", responsivePriority: 4},
                {data: "completa", responsivePriority: 3},
                {data: "is_active", responsivePriority: 2},
                {data: "id", responsivePriority: 1},
            ],
            columnDefs: [
                {
                    targets: [0],
                    render: function (data, type, row) {
                        var bot = row.tiene_bot ? '' : ' <span class="badge bg-secondary">Sin bot</span>';
                        return '<b>' + aseguradora.esc(data) + '</b>' + bot;
                    }
                },
                {
                    // Solo el dominio, en una pastilla del mismo ancho para todas; la dirección completa va en el tooltip.
                    targets: [1],
                    className: 'ase-col-portal',
                    render: function (data, type) {
                        if (type !== 'display') { return data || ''; }
                        if (!data) { return '<span class="text-muted">—</span>'; }
                        var dominio = data.replace(/^https?:\/\//i, '').split('/')[0].replace(/^www\./i, '');
                        return '<a class="ase-portal" href="' + aseguradora.esc(data) + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" title="' +
                            aseguradora.esc(data) + '"><i class="fa-solid fa-arrow-up-right-from-square"></i><span>' + aseguradora.esc(dominio) + '</span></a>';
                    }
                },
                {
                    targets: [2],
                    render: function (data) {
                        return data ? aseguradora.esc(data) : '<span class="text-muted">—</span>';
                    }
                },
                {
                    targets: [3],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (!row.tiene_bot) {
                            return '<span class="badge rounded-pill bg-secondary" title="Se cotiza por terceros; no necesita datos de acceso">No aplica</span>';
                        }
                        if (row.clave_pendiente) {
                            return '<span class="badge rounded-pill bg-danger" title="El portal pidió cambiar la contraseña' +
                                (row.clave_detectada ? ' (detectado el ' + aseguradora.esc(row.clave_detectada) + ')' : '') +
                                '. Cámbiala en el portal y actualízala aquí; mientras tanto no se cotiza con esta aseguradora.">' +
                                '<i class="fas fa-key"></i> Cambiar contraseña</span>';
                        }
                        if (data) {
                            return '<span class="badge rounded-pill bg-success"><i class="fas fa-check"></i> Completos</span>';
                        }
                        return '<span class="badge rounded-pill bg-warning text-dark" title="Falta: ' + aseguradora.esc(row.faltantes.join(', ')) + '">Faltan datos</span>';
                    }
                },
                {
                    targets: [4],
                    class: 'text-center',
                    orderable: false,
                    render: function (data, type, row) {
                        // Un solo botón que dice el estado; al hacer clic cambia al contrario.
                        var etiqueta = data ? '<i class="fas fa-check"></i> Activa' : '<i class="fas fa-ban"></i> Inactiva';
                        if (!puedeEditar) {
                            return '<span class="badge rounded-pill ' + (data ? 'bg-success' : 'bg-secondary') + '">' + etiqueta + '</span>';
                        }
                        return '<button type="button" class="btn btn-sm rounded-pill btn-estado ' + (data ? 'btn-success' : 'btn-outline-secondary') + '" rel="toggle"' +
                            ' data-activar="' + (data ? 'false' : 'true') + '" data-id="' + row.id + '" data-nombre="' + aseguradora.esc(row.name) + '"' +
                            ' data-bs-toggle="tooltip" title="' + (data ? 'Clic para inactivar' : 'Clic para activar') + '">' + etiqueta + '</button>';
                    }
                },
                {
                    // Botones en una sola fila (nunca uno encima del otro): primero editar, luego coberturas.
                    targets: [5],
                    className: 'text-center text-nowrap',
                    orderable: false,
                    render: function (data, type, row) {
                        var botones = '';
                        if (puedeEditar) {
                            botones += '<a href="' + pathname + data + '/editar/" data-bs-toggle="tooltip" title="' +
                                (row.clave_pendiente ? 'Actualizar la contraseña' : 'Editar datos de acceso') + '" class="btn btn-warning btn-sm rounded-pill"><i class="fas fa-edit"></i></a>';
                        }
                        botones += '<a href="' + pathname + data + '/coberturas/" data-bs-toggle="tooltip" title="Ver coberturas" class="btn btn-info btn-sm rounded-pill"><i class="fas fa-shield-halved"></i></a>';
                        if (puedeEditar && row.clave_pendiente) {
                            botones += '<button type="button" rel="clave_resuelta" data-id="' + data + '" data-nombre="' + aseguradora.esc(row.name) +
                                '" data-bs-toggle="tooltip" title="Quitar el aviso sin cambiar la contraseña (falsa alarma)" class="btn btn-outline-secondary btn-sm rounded-pill"><i class="fas fa-unlock"></i></button>';
                        }
                        return '<div class="ase-acciones">' + botones + '</div>';
                    }
                },
            ],
            initComplete: function () {
                enable_tooltip();
            }
        });
    },

    esc: function (texto) {
        return $('<div>').text(texto == null ? '' : String(texto)).html();
    }
};

$(function () {
    toastr.options = {closeButton: true, progressBar: true, positionClass: 'toast-top-right', timeOut: '3500'};
    aseguradora.list();

    $('#data tbody')
        .off()
        .on('click', 'button[rel="clave_resuelta"]', function () {
            $('.tooltip').remove();
            var id = $(this).data('id');
            var nombre = $(this).data('nombre');
            dialog_action({
                'content': '¿Quitar el aviso de cambio de contraseña de ' + nombre + '? Úsalo solo si fue una falsa alarma o si ya la cambiaste: ' +
                    'los bots volverán a intentar entrar al portal con la contraseña guardada.',
                'success': function () {
                    $.ajax({
                        url: pathname,
                        type: 'POST',
                        headers: {'X-CSRFToken': csrftoken},
                        data: {action: 'clave_resuelta', id: id},
                        dataType: 'json',
                        success: function (data) {
                            if (data.error) {
                                return message_error(data.error);
                            }
                            toastr.success('Aviso quitado en ' + nombre);
                            aseguradora.list();
                        },
                        error: function () {
                            message_error('No se pudo quitar el aviso');
                        }
                    });
                },
                'cancel': function () {}
            });
        })
        .on('click', 'button[rel="toggle"]', function () {
            $('.tooltip').remove();
            var activar = $(this).data('activar') === true || $(this).data('activar') === 'true';
            var id = $(this).data('id');
            var nombre = $(this).data('nombre');
            dialog_action({
                'content': activar
                    ? '¿Activar ' + nombre + '? Volverá a incluirse en las cotizaciones nuevas.'
                    : '¿Inactivar ' + nombre + '? Dejará de incluirse en las cotizaciones nuevas (las que ya están en curso no se interrumpen).',
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
                            toastr.success(nombre + (activar ? ' activada' : ' inactivada'));
                            aseguradora.list();
                        },
                        error: function () {
                            message_error('Ocurrió un error al cambiar el estado de la aseguradora');
                        }
                    });
                },
                'cancel': function () {}
            });
        });
});

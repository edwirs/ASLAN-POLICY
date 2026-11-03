var poliza = {
    filtro: 'todas',

    esc: function (texto) {
        return $('<div>').text(texto == null ? '' : String(texto)).html();
    },

    dinero: function (valor) {
        return '$' + Number(valor || 0).toLocaleString('es-CO', {maximumFractionDigits: 0});
    },

    dias: function (n) {
        return n + (n === 1 ? ' día' : ' días');
    },

    fecha: function (texto) {
        if (!texto) {
            return '—';
        }
        var p = String(texto).split('-');
        return p[2] + '/' + p[1] + '/' + p[0];
    },

    list: function () {
        $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            responsive: true,
            order: [[5, 'asc']],
            search: {search: busquedaInicial()},
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: function () {
                    return {action: 'search', filtro: poliza.filtro, asesor: $('#fAsesor').val(), aseguradora: $('#fAseguradora').val(), mes: $('#fMes').val()};
                },
                dataSrc: function (json) {
                    $.each(json.conteos || {}, function (filtro, n) {
                        var $b = $('[data-conteo="' + filtro + '"]').text(n);
                        $b.closest('.btn').toggleClass('vacio', n === 0 && filtro !== poliza.filtro);
                    });
                    return json.filas || [];
                }
            },
            columns: [
                {data: "placa"},
                {data: "tomador"},
                {data: "aseguradora"},
                {data: "asesor"},
                {data: "ciudad"},
                {data: "fecha_renovacion"},
                {data: "prima_total"},
                {data: "valor_comision"},
                {data: "forma_pago"},
                {data: "estado_comision"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [0],
                    className: 'all',  // siempre visible (no se esconde en el detalle)
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + (row.numero_poliza || '');
                        }
                        var numero = row.numero_poliza ? '<br><small class="text-muted">Nº ' + poliza.esc(row.numero_poliza) + '</small>' : '';
                        var origen = row.origen === 'importada' ? ' <i class="fa-solid fa-file-import text-muted" data-bs-toggle="tooltip" title="Importada del histórico"></i>' : '';
                        return '<b>' + poliza.esc(data) + '</b>' + origen + numero;
                    }
                },
                {
                    targets: [1],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + row.documento + ' ' + (row.celular || '') + ' ' + (row.otro_celular || '');
                        }
                        var contacto = [row.celular ? '<i class="fa-solid fa-mobile-screen"></i> ' + poliza.esc(row.celular) : '',
                            row.otro_celular ? '<i class="fa-solid fa-mobile-screen"></i> ' + poliza.esc(row.otro_celular) : ''].filter(Boolean).join(' · ');
                        return '<div>' + poliza.esc(data) + '</div><small class="text-muted d-block">' + poliza.esc(row.documento) + '</small>' +
                            (contacto ? '<small class="text-muted d-block">' + contacto + '</small>' : '');
                    }
                },
                {
                    targets: [2],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + row.plan;
                        }
                        return '<b>' + poliza.esc(data) + '</b>' + (row.plan ? '<br><small class="text-muted">' + (/^plan\b/i.test(row.plan) ? '' : 'Plan ') + poliza.esc(row.plan) + '</small>' : '');
                    }
                },
                {
                    targets: [5],
                    class: 'pz-vence',
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data;
                        }
                        var chip, d = row.dias_para_vencer;
                        if (row.estado.id === 'cancelada') {
                            chip = '<span class="pz-chip pz-chip-gris">Cancelada</span>';
                        } else if (d < 0) {
                            chip = '<span class="pz-chip pz-chip-vencida">Venció hace ' + poliza.dias(-d) + '</span>';
                        } else if (d <= diasAviso) {
                            chip = '<span class="pz-chip pz-chip-renovar"><i class="fa-solid fa-bell"></i> ' + (d === 0 ? 'Vence hoy' : 'Vence en ' + poliza.dias(d)) + '</span>';
                        } else {
                            chip = '<span class="pz-chip pz-chip-ok">Vigente · ' + poliza.dias(d) + '</span>';
                        }
                        return '<b>' + poliza.fecha(data) + '</b><div>' + chip + '</div>';
                    }
                },
                {
                    targets: [6],
                    class: 'text-end',
                    render: function (data, type) {
                        return type === 'display' ? poliza.dinero(data) : data;
                    }
                },
                {
                    targets: [7],
                    class: 'text-end',
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data;
                        }
                        var pct = row.porcentaje_comision != null ? '<br><small class="text-muted">' + row.porcentaje_comision.toLocaleString('es-CO') + ' %</small>' : '';
                        return poliza.dinero(data) + pct;
                    }
                },
                {
                    targets: [8],
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data + ' ' + row.fecha_pago;
                        }
                        var html = '<b>' + poliza.esc(data) + '</b>';
                        if (row.numero_cuotas > 1) {
                            var pct = Math.round(100 * row.cuotas_pagadas / row.numero_cuotas);
                            html += '<div class="pz-progreso" title="' + row.cuotas_pagadas + ' de ' + row.numero_cuotas + ' cuotas marcadas como pagadas"><span style="width:' + pct + '%"></span></div>' +
                                '<small class="text-muted d-block">' + row.cuotas_pagadas + ' de ' + row.numero_cuotas + ' pagadas</small>';
                            if (row.proxima_cuota) {
                                html += '<small class="text-muted d-block">Próxima: ' + poliza.fecha(row.proxima_cuota) + '</small>';
                            }
                        } else {
                            html += '<small class="text-muted d-block">Pagar antes de: ' + poliza.fecha(row.fecha_pago) + '</small>';
                        }
                        if (row.cuotas_atrasadas) {
                            html += '<span class="pz-chip pz-chip-vencida">' + row.cuotas_atrasadas + (row.cuotas_atrasadas > 1 ? ' cuotas atrasadas' : ' cuota atrasada') + '</span>';
                        }
                        return html;
                    }
                },
                {
                    targets: [9],
                    class: 'text-center',
                    render: function (data, type, row) {
                        if (type !== 'display') {
                            return data.name;
                        }
                        var chip = data.id === 'ok' ? '<span class="pz-chip pz-chip-ok">Confirmada</span>' : '<span class="pz-chip pz-chip-renovar">Pendiente</span>';
                        return chip + (row.fecha_pago_cartera ? '<small class="text-muted d-block">Pago: ' + poliza.fecha(row.fecha_pago_cartera) + '</small>' : '');
                    }
                },
                {
                    targets: [10],
                    className: 'all text-center text-nowrap',  // «all»: la columna de acciones nunca pasa al detalle
                    orderable: false,
                    render: function (data, type, row) {
                        var botones = '';
                        if (puedeEditar) {
                            botones += '<a href="' + pathname + data + '/editar/" class="btn btn-warning btn-sm rounded-pill" data-bs-toggle="tooltip" title="Ver / editar póliza y cuotas"><i class="fas fa-edit"></i></a> ';
                        }
                        if (puedeEliminar) {
                            botones += '<button type="button" class="btn btn-danger btn-sm rounded-pill" rel="delete" data-id="' + data + '" data-placa="' + poliza.esc(row.placa) +
                                '" data-bs-toggle="tooltip" title="Eliminar"><i class="fas fa-trash"></i></button>';
                        }
                        return botones || '<span class="text-muted">—</span>';
                    }
                },
            ],
            drawCallback: function () {
                $('.tooltip').remove();
                enable_tooltip();
            }
        });
    }
};

$(function () {
    toastr.options = {closeButton: true, progressBar: true, positionClass: 'toast-top-right', timeOut: '3500'};
    var inicial = new URLSearchParams(location.search).get('filtro');
    if (inicial) {
        poliza.filtro = inicial;
    }
    poliza.list();

    $('.pz-filtro').on('click', function () {
        poliza.filtro = $(this).data('filtro');
        $('.pz-filtro').removeClass('btn-primary').addClass('btn-outline-secondary');
        $(this).removeClass('btn-outline-secondary vacio').addClass('btn-primary');
        var params = new URLSearchParams(location.search);
        params.set('filtro', poliza.filtro);
        history.replaceState(null, '', '?' + params.toString());
        $('#data').DataTable().ajax.reload();
    });
    $('#fAsesor, #fAseguradora, #fMes').on('change', function () {
        $('#data').DataTable().ajax.reload();
    });
    $('#fLimpiar').on('click', function () {
        $('#fAsesor, #fAseguradora, #fMes').val('');
        $('#data').DataTable().search('').ajax.reload();
    });

    $('#data tbody').on('click', 'button[rel="delete"]', function () {
        $('.tooltip').remove();
        var id = $(this).data('id'), placa = $(this).data('placa');
        dialog_action({
            'content': '¿Eliminar la póliza de ' + placa + '? También se borran sus cuotas. No se puede deshacer.',
            'success': function () {
                $.ajax({
                    url: pathname, type: 'POST', headers: {'X-CSRFToken': csrftoken}, dataType: 'json',
                    data: {action: 'delete', id: id}
                }).done(function (data) {
                    if (data.error) {
                        return message_error(data.error);
                    }
                    toastr.success('Póliza eliminada');
                    poliza.list();
                }).fail(function () {
                    message_error('No se pudo eliminar la póliza');
                });
            },
            'cancel': function () {}
        });
    });
});

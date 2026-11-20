// Seguimiento de correos: la cola de envíos y su historial (pendiente de envío, enviado, error, cancelado), con las
// acciones que permita el perfil: cancelar, enviar ahora, corregir destinatarios, reprogramar y reintentar.
var correoSeguimiento = {
    filas: [],
    grupo: 'todos',
    tabla: null,
    modal: null,
    actual: null,
    permisos: {},

    esc: function (texto) {
        return $('<div>').text(texto == null ? '' : String(texto)).html();
    },

    // «2026-11-20 14:05» -> «20/11/2026 14:05»
    fecha: function (texto) {
        if (!texto) { return ''; }
        var m = String(texto).match(/^(\d{4})-(\d{2})-(\d{2})(.*)$/);
        return m ? m[3] + '/' + m[2] + '/' + m[1] + m[4] : texto;
    },

    fila: function (id) {
        return correoSeguimiento.filas.find(function (r) { return r.id === id; }) || null;
    },

    estado: function (r) {
        var html = '<span class="badge bg-' + r.color + (r.color === 'warning' ? ' text-dark' : '') + '">' + correoSeguimiento.esc(r.estado_nombre) + '</span>';
        if (r.estado === 'programado' && r.programado) {
            html += '<div class="cs-nota"><i class="fa-regular fa-clock"></i> Sale el ' + correoSeguimiento.esc(r.programado) + '</div>';
        } else if (r.estado === 'enviado' && r.enviado_en) {
            html += '<div class="cs-nota"><i class="fa-solid fa-check"></i> ' + correoSeguimiento.fecha(r.enviado_en) + '</div>';
        } else if (r.estado === 'error' && r.error_envio) {
            var corto = r.error_envio.split('\n')[0];
            html += '<div class="cs-nota cs-nota-error" title="' + correoSeguimiento.esc(r.error_envio) + '">' +
                correoSeguimiento.esc(corto.length > 90 ? corto.slice(0, 90) + '…' : corto) + '</div>';
        }
        return html;
    },

    // Acciones que aplican a este correo según su estado y el perfil. [accion, icono, texto, color del ícono]
    acciones: function (r) {
        var p = correoSeguimiento.permisos, lista = [];
        // Límite de correos por cotización (enviados + pendientes): al llegar, no se reenvía ni se reintenta.
        var lleno = r.envios >= r.max_envios, limite = 'No disponible: esta cotización ya tiene ' + r.max_envios + ' correos (el máximo).';
        if (r.estado === 'programado') {
            if (p.enviar_ahora) { lista.push(['enviar_ahora', 'fa-paper-plane', 'Enviar ahora', 'text-success']); }
            if (p.reprogramar) { lista.push(['reprogramar', 'fa-calendar-days', 'Reprogramar', 'text-primary']); }
            if (p.destinatarios) { lista.push(['destinatarios', 'fa-at', 'Corregir destinatarios', 'text-primary']); }
            if (p.cancelar) { lista.push(['cancelar', 'fa-ban', 'Cancelar envío', 'text-danger']); }
        } else if (r.estado === 'enviado') {
            // Si no se puede, se muestra en gris con el porqué (si no, parece falta de permiso).
            if (p.reenviar && !r.reenviable) { lista.push(['', 'fa-share', 'Reenviar', 'text-muted', 'No disponible: sus adjuntos ya no se guardan. Envíelo de nuevo desde el comparativo.']); }
            else if (p.reenviar && lleno) { lista.push(['', 'fa-share', 'Reenviar', 'text-muted', limite]); }
            else if (p.reenviar) { lista.push(['reenviar', 'fa-share', 'Reenviar', 'text-primary']); }
        } else if (r.estado === 'error') {
            if (p.reintentar && !r.sin_adjuntos && lleno) { lista.push(['', 'fa-rotate-right', 'Reintentar', 'text-muted', limite]); }
            else if (p.reintentar && !r.sin_adjuntos) { lista.push(['reintentar', 'fa-rotate-right', 'Reintentar', 'text-success']); }
            if (p.destinatarios) { lista.push(['destinatarios', 'fa-at', 'Corregir destinatarios', 'text-primary']); }
        }
        return lista;
    },

    // Botón «⋯» con el menú de acciones (igual que en Facturas electrónicas). En la ventana de detalle no repite «Ver».
    // Posición fija: la tabla oculta lo que se sale de ella y cortaba el menú de las últimas filas.
    menu: function (r, enDetalle) {
        var item = function (accion, icono, texto, color, motivo) {
            if (motivo) {  // acción que no aplica a este correo: en gris, sin clic, con la razón debajo
                return '<li><span class="dropdown-item disabled cs-item-no" aria-disabled="true"><i class="fa-solid ' + icono + ' ' + color +
                    '"></i><span>' + texto + '<small class="d-block">' + motivo + '</small></span></span></li>';
            }
            return '<li><a class="dropdown-item" href="#" data-accion="' + accion + '" data-id="' + r.id + '"><i class="fa-solid ' + icono +
                ' ' + color + '"></i>' + texto + '</a></li>';
        };
        var acciones = correoSeguimiento.acciones(r), html = function (a) { return item(a[0], a[1], a[2], a[3], a[4]); };
        var consulta = enDetalle ? [] : [item('ver', 'fa-eye', 'Ver correo', 'text-info')]
            .concat(csComparativo ? [item('comparativo', 'fa-scale-balanced', 'Abrir comparativo', 'text-secondary')] : []);
        // Grupos separados por una línea: consultar · acciones · cancelar (al final, en rojo).
        var grupos = [consulta, acciones.filter(function (a) { return a[0] !== 'cancelar'; }).map(html),
                      acciones.filter(function (a) { return a[0] === 'cancelar'; }).map(html)]
            .filter(function (g) { return g.length; });
        if (!grupos.length) { return ''; }
        var items = [grupos.map(function (g) { return g.join(''); }).join('<li><hr class="dropdown-divider"></li>')];
        var boton = enDetalle
            ? '<button class="btn btn-primary rounded-pill dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="fa-solid fa-gear"></i> Acciones</button>'
            : '<button class="btn btn-actions-dots" type="button" data-bs-toggle="dropdown" data-bs-popper-config=\'{"strategy":"fixed"}\' aria-expanded="false" aria-label="Acciones del correo"><i class="fas fa-ellipsis-h"></i></button>';
        return '<div class="dropdown d-inline-block">' + boton + '<ul class="dropdown-menu dropdown-menu-end actions-dropdown-menu">' + items.join('') + '</ul></div>';
    },

    pintarFiltros: function () {
        var conteo = {todos: correoSeguimiento.filas.length};
        correoSeguimiento.filas.forEach(function (r) { conteo[r.grupo] = (conteo[r.grupo] || 0) + 1; });
        $('#csFiltros .btn').each(function () {
            var id = $(this).data('grupo'), n = conteo[id] || 0, activo = id === correoSeguimiento.grupo;
            $(this).find('.badge').text(n);
            $(this).toggleClass('vacio', n === 0 && !activo).toggleClass('btn-primary', activo).toggleClass('btn-outline-secondary', !activo);
        });
    },

    list: function () {
        correoSeguimiento.tabla = $('#data').DataTable({
            autoWidth: false,
            destroy: true,
            deferRender: true,
            responsive: true,
            order: [[0, 'desc']],
            ajax: {
                url: pathname,
                type: 'POST',
                headers: {'X-CSRFToken': csrftoken},
                data: {action: 'search'},
                dataSrc: function (json) {
                    if (json.error) { message_error(json.error); return []; }
                    correoSeguimiento.filas = json;
                    correoSeguimiento.pintarFiltros();
                    return json;
                }
            },
            columns: [
                {data: 'creado', responsivePriority: 2},
                {data: 'placa', responsivePriority: 1},
                {data: 'cliente', responsivePriority: 4},
                {data: 'para', responsivePriority: 5},
                {data: 'envios', responsivePriority: 6, className: 'text-center'},
                {data: 'estado_nombre', responsivePriority: 1},
                {data: 'por', responsivePriority: 7},
                {data: null, orderable: false, searchable: false, responsivePriority: 3},
            ],
            columnDefs: [
                {targets: [0], render: function (data, type) { return type === 'display' ? correoSeguimiento.fecha(data) : data; }},
                {targets: [1], render: function (data, type) { return type === 'display' ? '<b>' + correoSeguimiento.esc(data) + '</b>' : data; }},
                {targets: [2, 6], render: function (data, type) { return type === 'display' ? correoSeguimiento.esc(data) : data; }},
                {
                    targets: [3],
                    render: function (data, type, row) {
                        if (type !== 'display') { return data + ' ' + (row.cc || ''); }
                        return correoSeguimiento.esc(data) + (row.cc ? '<div class="cs-nota">CC ' + correoSeguimiento.esc(row.cc) + '</div>' : '');
                    }
                },
                {
                    targets: [4],
                    render: function (data, type, row) {
                        if (type !== 'display') { return data; }
                        var lleno = data >= row.max_envios;
                        return '<span class="badge rounded-pill ' + (lleno ? 'bg-danger' : 'bg-secondary') + '" data-bs-toggle="tooltip" title="' +
                            (lleno ? 'Llegó al máximo: no se pueden enviar más correos de esta cotización' :
                             'Correos de esta cotización enviados o pendientes de envío (máximo ' + row.max_envios + ')') + '">' + data + ' de ' + row.max_envios + '</span>';
                    }
                },
                {
                    targets: [5],
                    render: function (data, type, row) { return type === 'display' ? correoSeguimiento.estado(row) : data + ' ' + (row.error_envio || ''); }
                },
                {
                    targets: [7],
                    className: 'text-center',
                    render: function (data, type, row) { return correoSeguimiento.menu(row, false); }
                },
            ],
            initComplete: function () { enable_tooltip(); }
        });
        correoSeguimiento.tabla.on('draw', function () { enable_tooltip(); });
    },

    recargar: function () {
        correoSeguimiento.tabla.ajax.reload(null, false);
    },

    dato: function (etiqueta, valor) {
        return '<div class="cs-dato"><dt>' + etiqueta + '</dt><dd>' + (valor ? valor : '<span class="text-muted">—</span>') + '</dd></div>';
    },

    detalle: function (id) {
        $.ajax({url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken}, data: {action: 'detalle', id: id}})
            .done(function (r) {
                if (r.error) { return message_error(r.error); }
                correoSeguimiento.actual = r;
                var e = correoSeguimiento.esc, d = correoSeguimiento.dato;
                $('#csDetallePlaca').text(r.placa);
                var html = '<dl class="cs-datos">' +
                    d('Estado', correoSeguimiento.estado(r)) +
                    d('Pedido el', correoSeguimiento.fecha(r.creado) + (r.por ? ' · ' + e(r.por) : '')) +
                    d('Sale desde', e(r.cuenta)) +
                    d('Para', e(r.para)) +
                    d('CC', e(r.cc)) +
                    d('Asunto', e(r.asunto)) +
                    d('Adjuntos', r.adjuntos.length ? r.adjuntos.map(function (a) { return '<span class="cs-adjunto"><i class="fa-regular fa-file-pdf"></i> ' + e(a) + '</span>'; }).join(' ') : '') +
                    d('Intentos de envío', r.intentos ? String(r.intentos) : '') +
                    '</dl>';
                if (r.estado === 'error' && r.error_envio) {
                    var ayuda = r.sin_adjuntos
                        ? 'Sus adjuntos ya se borraron (se guardan 3 días después de fallar): para volver a enviarlo, abre el comparativo y arma el correo de nuevo.'
                        : 'Si ya se corrigió la causa (por ejemplo, la contraseña de la cuenta o un correo mal escrito), usa «Reintentar». Sus adjuntos se guardan 3 días después de fallar.';
                    html += '<div class="alert alert-danger cs-error"><b><i class="fa-solid fa-triangle-exclamation"></i> Por qué no salió</b><pre>' + e(r.error_envio) + '</pre>' +
                        '<small>' + ayuda + '</small></div>';
                }
                if (r.estado === 'enviado') {
                    html += '<p class="cs-nota mb-3"><i class="fa-solid fa-circle-info"></i> ' + (r.reenviable
                        ? 'Si el cliente no lo encuentra (revise también spam), se puede reenviar igual hasta el ' + correoSeguimiento.fecha(r.reenviable_hasta) + '.'
                        : 'Ya no se puede reenviar igual: sus adjuntos no se guardaron (los correos enviados antes de esta actualización no los guardaban) o pasaron los 30 días. Ármalo de nuevo desde el comparativo.') + '</p>';
                }
                html += '<h6 class="cs-subtitulo">Correo tal como se armó</h6>';
                $('#csDetalleCuerpo').html(html).append($('<iframe class="cs-vista" title="Vista del correo" sandbox></iframe>').attr('srcdoc', r.html || '<p style="font-family:sans-serif;color:#888">Sin cuerpo guardado.</p>'));
                $('#csDetalleComparativo').prop('hidden', !csComparativo).attr('href', csComparativo.replace('/0/', '/' + r.vehiculo_id + '/'));
                $('#csDetalleAcciones').html(correoSeguimiento.menu(r, true));
                correoSeguimiento.modal.show();
            })
            .fail(function () { message_error('No se pudo cargar el correo.'); });
    },

    // Llama a la acción en el servidor; al terminar recarga la tabla y cierra las ventanas.
    enviar: function (accion, id, extra, $boton) {
        if ($boton) { $boton.prop('disabled', true); }
        $.ajax({url: pathname, type: 'POST', dataType: 'json', headers: {'X-CSRFToken': csrftoken},
                data: $.extend({action: accion, id: id}, extra || {})})
            .done(function (r) {
                if (r.error) { message_error(r.error); correoSeguimiento.recargar(); return; }
                toastr.success(r.mensaje || 'Listo');
                $('.modal.show').each(function () { bootstrap.Modal.getInstance(this).hide(); });
                correoSeguimiento.recargar();
            })
            .fail(function (xhr) { message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo completar la acción.'); })
            .always(function () { if ($boton) { $boton.prop('disabled', false); } });
    },

    confirmar: function (titulo, html, boton, color, alAceptar) {
        Swal.fire({title: titulo, html: html, icon: 'question', showCancelButton: true, confirmButtonText: boton,
                   cancelButtonText: 'No', confirmButtonColor: color})
            .then(function (res) { if (res.isConfirmed) { alAceptar(); } });
    },

    accion: function (accion, id) {
        var r = correoSeguimiento.fila(id) || (correoSeguimiento.actual && correoSeguimiento.actual.id === id ? correoSeguimiento.actual : null);
        if (!r) { return; }
        var e = correoSeguimiento.esc, quien = '<b>' + e(r.para) + '</b> (' + e(r.placa) + ')';
        if (accion === 'cancelar') {
            correoSeguimiento.confirmar('¿Cancelar este envío?', 'El correo a ' + quien + ' no saldrá.', 'Sí, cancelar envío', '#dc3545',
                function () { correoSeguimiento.enviar('cancelar', id); });
        } else if (accion === 'enviar_ahora') {
            correoSeguimiento.confirmar('¿Enviar ahora?', 'El correo a ' + quien + ' sale en este momento, sin esperar la hora programada' +
                (r.programado ? ' (' + e(r.programado) + ')' : '') + '.', 'Sí, enviar ahora', '#198754',
                function () { correoSeguimiento.enviar('enviar_ahora', id); });
        } else if (accion === 'reintentar') {
            var duda = /no se sabe si sali/i.test(r.error_envio || '')
                ? '<br><br><b>Ojo:</b> el envío anterior se interrumpió y pudo haber salido. Confirma con el cliente para no enviarlo dos veces.' : '';
            correoSeguimiento.confirmar('¿Reintentar el envío?', 'Se vuelve a enviar el mismo correo a ' + quien +
                '. Fuera del horario hábil queda pendiente para la siguiente hora hábil.' + duda, 'Sí, reintentar', '#198754',
                function () { correoSeguimiento.enviar('reintentar', id); });
        } else if (accion === 'reenviar') {
            correoSeguimiento.abrirReenvio(r);
        } else if (accion === 'destinatarios') {
            correoSeguimiento.editando = id;
            $('#csPara').val(r.para);
            $('#csCc').val(r.cc);
            bootstrap.Modal.getOrCreateInstance(document.getElementById('csModalDestinatarios')).show();
        } else if (accion === 'reprogramar') {
            correoSeguimiento.editando = id;
            $('#csMomento').val(r.programado_iso || '');
            bootstrap.Modal.getOrCreateInstance(document.getElementById('csModalReprogramar')).show();
        }
    }
};

// «Reenviar»: casillas con los correos registrados del cliente (puede tener dos) y los del envío anterior, marcadas
// las que recibieron el correo; y una casilla que habilita un campo para otro correo que indique el cliente.
correoSeguimiento.separar = function (texto) {
    return (texto || '').split(/[,;\s]+/).map(function (c) { return c.trim(); }).filter(Boolean);
};

correoSeguimiento.abrirReenvio = function (r) {
    var e = $.fn.dataTable.render.text().display, anteriores = correoSeguimiento.separar(r.para), vistos = {}, casillas = [];
    var agregar = function (correo, nota) {
        var clave = correo.toLowerCase();
        if (vistos[clave]) { return; }
        vistos[clave] = true;
        var marcado = anteriores.some(function (a) { return a.toLowerCase() === clave; }), n = casillas.length;
        casillas.push('<div class="form-check"><input class="form-check-input cs-re-correo" type="checkbox" id="csReC' + n + '" value="' + e(correo) + '"' +
            (marcado ? ' checked' : '') + '><label class="form-check-label" for="csReC' + n + '">' + e(correo) +
            (nota ? ' <small class="text-muted">(' + nota + ')</small>' : '') + '</label></div>');
    };
    (r.correos_cliente || []).forEach(function (c) { agregar(c, ''); });
    anteriores.forEach(function (c) { agregar(c, 'del envío anterior'); });
    correoSeguimiento.editando = r.id;
    $('#csRePlaca').text(r.placa);
    $('#csReCorreos').html(casillas.length ? casillas.join('')
        : '<p class="text-muted small mb-0">El cliente no tiene correos registrados: escriba el correo abajo.</p>');
    var sinCasillas = !casillas.length;
    $('#csReOtroCheck').prop('checked', sinCasillas);
    $('#csReOtro').val('').prop('disabled', !sinCasillas);
    $('#csReCc').val(r.cc);
    bootstrap.Modal.getOrCreateInstance(document.getElementById('csModalReenviar')).show();
};

correoSeguimiento.paraReenvio = function () {
    var para = $('#csReCorreos .cs-re-correo:checked').map(function () { return this.value; }).get();
    if ($('#csReOtroCheck').is(':checked')) { para = para.concat(correoSeguimiento.separar($('#csReOtro').val())); }
    return para;
};

$.fn.dataTable.ext.search.push(function (settings, datos, indice) {
    if (settings.nTable.id !== 'data' || correoSeguimiento.grupo === 'todos') { return true; }
    return settings.aoData[indice]._aData.grupo === correoSeguimiento.grupo;
});

$(function () {
    toastr.options = {closeButton: true, progressBar: true, positionClass: 'toast-top-right', timeOut: 4500};
    try { correoSeguimiento.permisos = JSON.parse(document.getElementById('csPermisos').textContent); } catch (e) { correoSeguimiento.permisos = {}; }
    correoSeguimiento.modal = new bootstrap.Modal(document.getElementById('csModalDetalle'));
    var inicial = new URLSearchParams(location.search).get('estado');
    if (inicial && $('#csFiltros .btn[data-grupo="' + inicial + '"]').length) { correoSeguimiento.grupo = inicial; }
    correoSeguimiento.list();

    $('#csFiltros').on('click', '.btn', function () {
        correoSeguimiento.grupo = $(this).data('grupo');
        var params = new URLSearchParams(location.search);
        if (correoSeguimiento.grupo === 'todos') { params.delete('estado'); } else { params.set('estado', correoSeguimiento.grupo); }
        history.replaceState(null, '', '?' + params.toString());
        correoSeguimiento.pintarFiltros();
        correoSeguimiento.tabla.draw();
    });

    // Opciones del menú «⋯» (en la tabla y en la ventana de detalle).
    $(document).on('click', '.actions-dropdown-menu a[data-accion]', function (e) {
        e.preventDefault();
        var accion = $(this).data('accion'), id = $(this).data('id');
        if (accion === 'ver') { return correoSeguimiento.detalle(id); }
        if (accion === 'comparativo') {
            var r = correoSeguimiento.fila(id);
            if (r) { window.location.href = csComparativo.replace('/0/', '/' + r.vehiculo_id + '/'); }
            return;
        }
        correoSeguimiento.accion(accion, id);
    });
    $('#csGuardarDestinatarios').on('click', function () {
        correoSeguimiento.enviar('destinatarios', correoSeguimiento.editando, {para: $('#csPara').val(), cc: $('#csCc').val()}, $(this));
    });
    $('#csReOtroCheck').on('change', function () {
        $('#csReOtro').prop('disabled', !this.checked);
        if (this.checked) { $('#csReOtro').trigger('focus'); }
    });
    $('#csReEnviar').on('click', function () {
        if ($('#csReOtroCheck').is(':checked') && !$.trim($('#csReOtro').val())) { return message_error('Escriba el otro correo o desmarque esa casilla.'); }
        var para = correoSeguimiento.paraReenvio();
        if (!para.length) { return message_error('Marque al menos un correo del cliente o escriba otro.'); }
        correoSeguimiento.enviar('reenviar', correoSeguimiento.editando, {para: para.join(', '), cc: $('#csReCc').val()}, $(this));
    });
    $('#csGuardarReprogramar').on('click', function () {
        if (!$('#csMomento').val()) { return message_error('Elija la fecha y la hora.'); }
        correoSeguimiento.enviar('reprogramar', correoSeguimiento.editando, {momento: $('#csMomento').val()}, $(this));
    });
});

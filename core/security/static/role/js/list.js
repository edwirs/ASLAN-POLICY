var role = {
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
                {data: "name"},
                {data: "permissions"},
                {data: "users"},
                {data: "id"},
            ],
            columnDefs: [
                {
                    targets: [0],
                    render: function (data, type, row) {
                        var badge = row.is_system ? ' <span class="badge bg-secondary">Sistema</span>' : '';
                        return '<b>' + $('<span>').text(data).html() + '</b>' + badge;
                    }
                },
                {
                    targets: [1],
                    class: 'text-center',
                    render: function (data, type, row) {
                        var pct = row.total ? Math.round(data * 100 / row.total) : 0;
                        return '<div class="progress" style="height: 18px; min-width: 120px;">' +
                            '<div class="progress-bar bg-info" style="width:' + pct + '%">' + data + ' / ' + row.total + '</div></div>';
                    }
                },
                {
                    targets: [2],
                    class: 'text-center',
                    render: function (data) {
                        return '<span class="badge bg-primary">' + data + '</span>';
                    }
                },
                {
                    targets: [-1],
                    class: 'text-center',
                    orderable: false,
                    render: function (data, type, row) {
                        var buttons = '';
                        if (can_change) {
                            var title = row.is_system ? 'Ver permisos' : 'Editar';
                            var icon = row.is_system ? 'fa-eye' : 'fa-edit';
                            var btn = row.is_system ? 'btn-info' : 'btn-warning';
                            buttons += '<a href="' + pathname + 'update/' + row.id + '/" data-bs-toggle="tooltip" title="' + title + '" class="btn ' + btn + ' btn-sm"><i class="fas ' + icon + '"></i></a> ';
                        }
                        if (can_delete && !row.is_system) {
                            buttons += '<a href="' + pathname + 'delete/' + row.id + '/" data-bs-toggle="tooltip" title="Eliminar" class="btn btn-danger btn-sm"><i class="fas fa-trash"></i></a>';
                        }
                        return buttons;
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
    role.list();
});

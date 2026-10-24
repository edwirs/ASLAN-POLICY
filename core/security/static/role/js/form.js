var roleForm = {
    $form: null,
    selected: [],
    perms: {},
    menu: [],

    init: function () {
        var self = this;
        self.$form = $('#frmForm');
        self.selected = JSON.parse($('#role-selected').text());
        self.perms = JSON.parse($('#role-perms').text());
        self.menu = JSON.parse($('#role-menu').text());
        self.setChecked(self.selected);

        // Acción marcada => "Ver" del mismo módulo (sin ver no se puede entrar a la pantalla).
        self.$form.on('change', '.perm', function () {
            var $row = $(this).closest('tr');
            if ($(this).is(':checked') && $(this).data('col') !== 'view') {
                $row.find('.perm[data-col="view"]').prop('checked', true);
            }
            if (!$row.find('.perm[data-col="view"]').is(':checked')) {
                // Quitar "Ver" quita también el resto de la fila.
                $row.find('.perm').prop('checked', false);
            }
            self.refresh();
        });

        self.$form.on('change', '.row-toggle', function () {
            var $row = $(this).closest('tr');
            $row.find('.perm').prop('checked', $(this).is(':checked'));
            self.refresh();
        });

        self.$form.on('click', '.col-toggle', function (e) {
            e.preventDefault();
            var col = $(this).data('col');
            var $table = $(this).closest('table');
            var $section = $(this).closest('table').find('tbody');
            var $boxes = $section.find('.perm[data-col="' + col + '"]');
            var all = $boxes.length && $boxes.filter(':checked').length === $boxes.length;
            $boxes.prop('checked', !all).each(function () {
                if (!all && col !== 'view') {
                    $(this).closest('tr').find('.perm[data-col="view"]').prop('checked', true);
                }
            });
            if (all && col === 'view') {
                $boxes.closest('tr').find('.perm').prop('checked', false);
            }
            self.refresh();
        });

        $('#btn_all').on('click', function () {
            self.$form.find('.perm').prop('checked', true);
            self.refresh();
        });
        $('#btn_none').on('click', function () {
            self.$form.find('.perm').prop('checked', false);
            self.refresh();
        });
        $('#btn_readonly').on('click', function () {
            self.$form.find('.perm').prop('checked', false);
            self.$form.find('.perm[data-ro="1"]').prop('checked', true);
            self.refresh();
        });
        $('#btn_copy').on('click', function () {
            var id = $('#copy_role').val();
            if (!id) {
                message_error('Seleccione el rol del que desea copiar los permisos.');
                return;
            }
            self.setChecked(self.perms[id] || []);
        });

        self.$form.on('submit', function (e) {
            e.preventDefault();
            var form = self.$form[0];
            if (!$.trim($('#id_name').val())) {
                message_error('Ingrese el nombre del rol.');
                return false;
            }
            var count = self.$form.find('.perm:checked').length;
            submit_with_formdata({
                'params': new FormData(form),
                'form': form,
                'content': count ? '¿Estas seguro de guardar este rol con ' + count + ' permiso(s)?' :
                    'Este rol no tendrá ningún permiso: solo podrá ver Actualizar Perfil y Contraseña. ¿Desea guardarlo?'
            });
        });
    },

    setChecked: function (keys) {
        var set = {};
        keys.forEach(function (k) { set[k] = true; });
        this.$form.find('.perm').each(function () {
            $(this).prop('checked', !!set[$(this).val()]);
        });
        this.refresh();
    },

    refresh: function () {
        var self = this;
        // Estado del checkbox "Todo" de cada fila
        self.$form.find('tbody tr').each(function () {
            var $boxes = $(this).find('.perm');
            $(this).find('.row-toggle').prop('checked', $boxes.length > 0 && $boxes.filter(':checked').length === $boxes.length);
            $(this).toggleClass('row-on', $boxes.filter(':checked').length > 0);
        });
        self.renderPreview();
    },

    renderPreview: function () {
        var checked = {};
        this.$form.find('.perm:checked').each(function () { checked[$(this).val()] = true; });
        var esc = function (t) { return $('<span>').text(t).html(); };

        function build(nodes) {
            var html = '';
            nodes.forEach(function (n) {
                if (n.children) {
                    var inner = build(n.children);
                    if (inner) {
                        html += '<li><div class="sec"><i class="' + n.icon + '"></i> ' + esc(n.label) + '</div><ul>' + inner + '</ul></li>';
                    }
                } else if (n.perm === null || checked[n.perm]) {
                    html += '<li><i class="far fa-circle" style="font-size:9px"></i> ' + esc(n.label) + '</li>';
                }
            });
            return html;
        }

        $('#menu_preview').html(build(this.menu) || '<li class="text-muted">Sin módulos</li>');
    }
};

/* Aslani: ventana de chat con historial. El servidor guarda las conversaciones de cada usuario; aquí solo se pinta,
   se envía la pregunta y se lee la respuesta en vivo (NDJSON: un evento por línea). */
(function () {
    'use strict';
    var $boton = document.getElementById('asistBoton'), $raiz = document.getElementById('asistRaiz');
    if (!$boton || !$raiz) { return; }
    var $ = function (id) { return document.getElementById(id); };
    var $cuerpo = $('asistCuerpo'), $inicio = $('asistInicio'), $lista = $('asistMensajes'), $form = $('asistForm'),
        $texto = $('asistTexto'), $enviar = $('asistEnviar'), $chats = $('asistChats'), $lateral = $('asistLateral'),
        $titulo = $('asistTitulo');
    var URL = $raiz.dataset, ULTIMA = 'aslani-ultima';
    var conv = {id: null, titulo: 'Nuevo chat'}, chats = [], ocupado = false, ICONO = 'fa-solid';

    function csrf() { return typeof csrftoken !== 'undefined' ? csrftoken : ''; }
    function guardarUltima() { try { if (conv.id) { sessionStorage.setItem(ULTIMA, conv.id); } else { sessionStorage.removeItem(ULTIMA); } } catch (e) { /* sin almacenamiento */ } }
    function leerUltima() { try { return sessionStorage.getItem(ULTIMA); } catch (e) { return null; } }

    // ---------- Texto seguro (markdown mínimo: **negrita**, `código`, [enlaces](/ruta), listas, tablas) ----------
    function esc(t) {
        return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function enLinea(s) {
        s = s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
        return s.replace(/\[([^\]]+)\]\((\/[^)\s]*)\)/g, function (m, t, u) { return u.charAt(1) === '/' ? m : '<a href="' + u + '">' + t + '</a>'; });  // solo rutas internas
    }
    function formato(texto) {
        var html = '', lista = null, tabla = null;
        function cerrarLista() { if (lista) { html += '</' + lista + '>'; lista = null; } }
        function cerrarTabla() {
            if (!tabla) { return; }
            var filas = tabla.filter(function (f) { return !/^\s*\|?[\s:|-]+\|?\s*$/.test(f); }).map(function (f) {
                return f.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(function (c) { return enLinea(c.trim()); });
            });
            if (filas.length) {
                html += '<table class="asist-tabla"><thead><tr>' + filas[0].map(function (c) { return '<th>' + c + '</th>'; }).join('') + '</tr></thead><tbody>' +
                    filas.slice(1).map(function (f) { return '<tr>' + f.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table>';
            }
            tabla = null;
        }
        esc(texto).split('\n').forEach(function (l) {
            if (/^\s*\|/.test(l)) { cerrarLista(); (tabla = tabla || []).push(l); return; }
            cerrarTabla();
            var vineta = /^\s*[-*•]\s+(.*)/.exec(l), numero = /^\s*\d+[.)]\s+(.*)/.exec(l), titulo = /^\s*#{1,4}\s+(.*)/.exec(l);
            if (vineta || numero) {
                var tipo = vineta ? 'ul' : 'ol';
                if (lista !== tipo) { cerrarLista(); html += '<' + tipo + '>'; lista = tipo; }
                html += '<li>' + enLinea((vineta || numero)[1]) + '</li>';
            } else if (titulo) { cerrarLista(); html += '<p><b>' + enLinea(titulo[1]) + '</b></p>'; }
            else if (l.trim()) { cerrarLista(); html += '<p>' + enLinea(l) + '</p>'; } else { cerrarLista(); }
        });
        cerrarLista(); cerrarTabla();
        return html;
    }

    // ---------- Mensajes ----------
    function alFondo(forzar) {
        if (forzar || $cuerpo.scrollHeight - $cuerpo.scrollTop - $cuerpo.clientHeight < 140) { $cuerpo.scrollTop = $cuerpo.scrollHeight; }
    }
    function mostrarConversacion(hay) { $inicio.hidden = hay; $lista.hidden = !hay; }
    function fuentes(el, consultas) {
        var prev = el.querySelector('.asist-herr'); if (prev) { prev.remove(); }
        if (consultas && consultas.length) {
            el.insertAdjacentHTML('beforeend', '<div class="asist-herr"><span><i class="fas fa-database"></i>Consultado: ' + esc(consultas.join(', ')) + '</span></div>');
        }
    }
    function burbuja(rol, texto, consultas) {
        var $m = document.createElement('div');
        $m.className = 'asist-msg ' + rol;
        if (rol === 'usuario') { $m.textContent = texto; }
        else { $m.innerHTML = '<div class="asist-texto">' + formato(texto) + '</div>'; fuentes($m, consultas); }
        $lista.appendChild($m);
        return $m;
    }
    function dibujar(mensajes) {
        $lista.innerHTML = '';
        mensajes.forEach(function (m) { burbuja(m.role === 'user' ? 'usuario' : 'asistente', m.content, m.consultas); });
        mostrarConversacion(mensajes.length > 0);
        alFondo(true);
    }
    function fijarTitulo() { $titulo.textContent = conv.titulo || 'Nuevo chat'; }

    // ---------- Cupo diario ----------
    var modoBasico = false, ultimoCupo = null;
    function pintarModo(ev) {
        if (!ev || !ev.modo) { return; }
        modoBasico = ev.modo === 'basico';
        var $b = $('asistModo');
        $b.hidden = !modoBasico;
        $b.title = ev.motivo ? 'Aslani está en modo básico: ' + ev.motivo
            : 'Aslani responde con respuestas guiadas (sin inteligencia artificial) por ahora. Un administrador puede activarla.';
        if (ultimoCupo) { pintarCupo(ultimoCupo); }
    }
    // La bolsa de preguntas es de TODA la empresa, por mes. Si se agota, Aslani sigue en modo básico (no se bloquea el chat).
    function pintarCupo(c) {
        if (!c) { return; }
        ultimoCupo = c;
        var $c = $('asistCupo'), restantes = c.restantes, sin = restantes <= 0;
        if (modoBasico && !sin) { $c.hidden = true; return; }   // modo básico por otra razón: no hay bolsa que mostrar
        $c.hidden = false;
        $c.title = 'La bolsa es de toda tu empresa. Se renueva el ' + c.renueva + '; las preguntas que no se usen no se acumulan.';
        $c.className = 'asist-cupo' + (sin ? ' agotado' : restantes <= Math.max(10, Math.ceil(c.limite * 0.1)) ? ' poco' : '');
        $('asistCupoTexto').textContent = sin ? 'Bolsa del mes agotada · se renueva el ' + c.renueva : 'Te quedan ' + restantes + ' de ' + c.limite + ' preguntas este mes';
        $('asistCupoBarra').style.width = Math.round(restantes * 100 / Math.max(c.limite, 1)) + '%';
    }

    // ---------- Historial ----------
    function pintarChats() {
        if (!chats.length) { $chats.innerHTML = '<div class="asist-vacio">Aún no tienes chats. Escríbele a Aslani y quedará aquí.</div>'; return; }
        var html = '', grupo = null;
        chats.forEach(function (c) {
            if (c.grupo !== grupo) { grupo = c.grupo; html += '<div class="asist-grupo">' + esc(grupo) + '</div>'; }
            html += '<div class="asist-chat' + (c.id === conv.id ? ' activo' : '') + '" data-id="' + c.id + '"><button type="button" class="abrir" title="' + esc(c.titulo) + '">' + esc(c.titulo) +
                '</button><button type="button" class="asist-borrar" title="Eliminar" aria-label="Eliminar este chat"><i class="fas fa-trash"></i></button></div>';
        });
        $chats.innerHTML = html;
    }
    function cargarChats() {
        return fetch(URL.lista, {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : {conversaciones: []}; })
            .then(function (d) { chats = d.conversaciones || []; pintarChats(); pintarModo(d); pintarCupo(d.cupo); }).catch(function () { /* se reintenta al reabrir */ });
    }
    function abrirChat(id) {
        $lateral.classList.remove('abierto');
        return fetch(URL.detalle.replace('/0/', '/' + id + '/'), {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) { nuevoChat(); return; }
                conv = {id: d.id, titulo: d.titulo}; guardarUltima(); fijarTitulo(); dibujar(d.mensajes); pintarChats();
            });
    }
    function nuevoChat() {
        conv = {id: null, titulo: 'Nuevo chat'}; guardarUltima(); fijarTitulo(); $lista.innerHTML = ''; mostrarConversacion(false);
        $lateral.classList.remove('abierto'); pintarChats(); $texto.focus();
    }

    // ---------- Enviar y leer la respuesta en vivo ----------
    function accion(ev, $m) {
        var $c = document.createElement('div');
        $c.className = 'asist-accion';
        $c.innerHTML = '<b>' + esc(ev.titulo) + '</b><p>' + esc(ev.detalle) + '</p><div class="botones"><button type="button" class="confirmar">' + esc(ev.boton || 'Confirmar') +
            '</button><button type="button" class="cancelar">Ahora no</button></div>';
        $c.querySelector('.cancelar').addEventListener('click', function () { $c.remove(); });
        $c.querySelector('.confirmar').addEventListener('click', function () {
            var botones = $c.querySelectorAll('button'); botones.forEach(function (b) { b.disabled = true; });
            fetch(URL.accion, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()}, body: JSON.stringify({token: ev.token})})
                .then(function (r) { return r.json().then(function (d) { return {ok: r.ok && d.ok, d: d}; }); })
                .then(function (res) {
                    $c.classList.add(res.ok ? 'listo' : 'fallo');
                    $c.innerHTML = '<b><i class="fas ' + (res.ok ? 'fa-circle-check' : 'fa-circle-exclamation') + '"></i> ' + (res.ok ? 'Hecho' : 'No se pudo') + '</b><p style="margin:0">' + esc(res.d.mensaje || res.d.error || '') + '</p>';
                })
                .catch(function () { $c.classList.add('fallo'); $c.innerHTML = '<b>No se pudo</b><p style="margin:0">Revisa tu conexión e intenta de nuevo.</p>'; });
        });
        $m.appendChild($c); alFondo(true);   // la confirmación es lo que el usuario debe ver
    }

    // Respuestas rápidas (modo básico): botones que envían la pregunta con un clic.
    function opciones(items, $m) {
        var $o = document.createElement('div');
        $o.className = 'asist-opciones';
        (items || []).forEach(function (t) {
            var b = document.createElement('button'); b.type = 'button'; b.textContent = t;
            b.addEventListener('click', function () { $o.querySelectorAll('button').forEach(function (x) { x.disabled = true; }); enviar(t); });
            $o.appendChild(b);
        });
        $m.appendChild($o); alFondo(true);
    }

    function leerFlujo(respuesta, $m) {
        var $t = $m.querySelector('.asist-texto'), buffer = '', pendiente = false, estado = null;
        function render() { pendiente = false; $t.innerHTML = formato(buffer); alFondo(); }
        function evento(ev) {
            if (ev.t === 'texto') { buffer += ev.d; if (!pendiente) { pendiente = true; requestAnimationFrame(render); } }
            else if (ev.t === 'herramienta') {
                if (!estado) { estado = document.createElement('div'); estado.className = 'asist-herr'; $m.appendChild(estado); }
                estado.innerHTML = '<span><i class="fas fa-spinner fa-spin"></i>Consultando ' + esc(ev.etiqueta) + '…</span>'; alFondo();
            }
            else if (ev.t === 'accion') { accion(ev, $m); }
            else if (ev.t === 'inicio') { pintarModo(ev); pintarCupo(ev.cupo); }
            else if (ev.t === 'modo') { pintarModo(ev); }
            else if (ev.t === 'opciones') { opciones(ev.items, $m); }
            else if (ev.t === 'error') { $m.className = 'asist-msg error'; buffer = ev.m; render(); pintarCupo(ev.cupo); }
            else if (ev.t === 'fin') {
                render(); fuentes($m, ev.consultas); pintarModo(ev); pintarCupo(ev.cupo);
                conv = {id: ev.conversacion, titulo: ev.titulo}; guardarUltima(); fijarTitulo(); cargarChats();
            }
        }
        var lector = respuesta.body.getReader(), decodificador = new TextDecoder(), resto = '';
        return (function paso() {
            return lector.read().then(function (r) {
                if (r.done) { return; }
                resto += decodificador.decode(r.value, {stream: true});
                var lineas = resto.split('\n'); resto = lineas.pop();
                lineas.forEach(function (l) { if (l.trim()) { try { evento(JSON.parse(l)); } catch (e) { /* línea incompleta */ } } });
                return paso();
            });
        })().then(function () { if (resto.trim()) { try { evento(JSON.parse(resto)); } catch (e) { /* fin sin saltos */ } } });
    }

    function enviar(pregunta) {
        pregunta = (pregunta || '').trim();
        if (!pregunta || ocupado) { return; }
        ocupado = true; $enviar.disabled = true;
        mostrarConversacion(true);
        burbuja('usuario', pregunta);
        var $m = burbuja('asistente', '');
        $m.querySelector('.asist-texto').innerHTML = '<span class="asist-punto"><span></span><span></span><span></span></span>';
        $texto.value = ''; autoAltura(); alFondo(true);

        fetch(URL.chat, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
                         body: JSON.stringify({conversacion: conv.id, mensaje: pregunta})})
            .then(function (r) {
                if (!r.ok || !r.body) {
                    return r.json().catch(function () { return {}; }).then(function (d) { $m.className = 'asist-msg error'; $m.querySelector('.asist-texto').textContent = d.error || 'No se pudo responder.'; });
                }
                return leerFlujo(r, $m);
            })
            .catch(function () { $m.className = 'asist-msg error'; $m.querySelector('.asist-texto').textContent = 'No se pudo conectar. Revisa tu conexión e intenta de nuevo.'; })
            .then(function () { ocupado = false; $enviar.disabled = false; $texto.focus(); });
    }

    // ---------- Abrir / cerrar y eventos ----------
    function autoAltura() { $texto.style.height = 'auto'; $texto.style.height = Math.min($texto.scrollHeight, 140) + 'px'; }
    function abrir(si) {
        $raiz.hidden = !si;
        $boton.classList.toggle('activo', si);
        $boton.setAttribute('aria-expanded', si ? 'true' : 'false');
        document.body.style.overflow = si ? 'hidden' : '';
        if (!si) { return; }
        var nombre = ($raiz.dataset.nombre || '').trim().split(/\s+/)[0];
        $('asistSaludo').textContent = 'Hola' + (nombre ? ', ' + nombre : '');
        cargarChats().then(function () {
            var ultima = leerUltima();
            if (conv.id) { pintarChats(); } else if (ultima) { abrirChat(ultima); }
        });
        setTimeout(function () { $texto.focus(); }, 60);
    }

    $boton.addEventListener('click', function (e) { e.preventDefault(); abrir($raiz.hidden); });
    $('asistCerrar').addEventListener('click', function () { abrir(false); });
    $raiz.addEventListener('mousedown', function (e) { if (e.target === $raiz) { abrir(false); } });
    $('asistNuevo').addEventListener('click', nuevoChat);
    $('asistMenu').addEventListener('click', function () { $lateral.classList.toggle('abierto'); });
    $form.addEventListener('submit', function (e) { e.preventDefault(); enviar($texto.value); });
    $texto.addEventListener('input', autoAltura);
    $texto.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar($texto.value); } });
    $('asistIdeas').addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { enviar(b.textContent); } });
    $chats.addEventListener('click', function (e) {
        var fila = e.target.closest('.asist-chat'); if (!fila) { return; }
        var id = parseInt(fila.dataset.id, 10);
        if (e.target.closest('.asist-borrar')) {
            if (!window.confirm('¿Eliminar esta conversación? No se puede deshacer.')) { return; }
            fetch(URL.eliminar.replace('/0/', '/' + id + '/'), {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}})
                .then(function () { if (conv.id === id) { nuevoChat(); } return cargarChats(); });
        } else { abrirChat(id); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !$raiz.hidden) { abrir(false); } });
})();

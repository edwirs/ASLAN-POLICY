"""Agente ASLAN: le presta el navegador de un PC de la oficina a los bots de ASLAN MultiAgente de Seguros.

Para qué sirve
--------------
Algunas aseguradoras bloquean la conexión desde el servidor de ASLAN (La Equidad: «Acceso denegado… desde su red») o
piden que una persona marque un captcha (Mapfre). Con el agente, el bot que corre en el servidor maneja el navegador de
este PC: el portal ve la red de la oficina (la que la aseguradora ya autorizó) y las ventanas que necesitan a una
persona salen en esta pantalla. Los bots y las contraseñas siguen en el servidor; aquí no se guarda ninguna.

Cómo funciona
-------------
- Solo hace conexiones de SALIDA por HTTPS (wss://…/agente/ws/): no hay que abrir puertos ni tocar el router.
- Arranca en este PC un servidor de Playwright escuchando solo en 127.0.0.1 (con una ruta secreta).
- Cuando el servidor de ASLAN pide un navegador, abre una conexión nueva y une sus mensajes con el servidor local.
- Protecciones: todo el tráfico del navegador pasa por un proxy local que NO deja llegar a direcciones de la red
  interna (192.168.x.x, 10.x.x.x, el router, este mismo PC…), y se rechazan las órdenes que no usan los bots (leer o
  escribir archivos de este PC, abrir file://, cambiar el proxy, hacer peticiones fuera del navegador…).

Uso
---
    aslan_agente.py                 ventana (lo normal; el instalador lo deja arrancando con Windows)
    aslan_agente.py --oculto        igual, pero minimizado (arranque automático)
    aslan_agente.py --consola [--servidor https://empresa.aslan-multiagente.com --codigo ABCD-EFGH]
                                    sin ventana (pruebas / Linux)
"""
import argparse
import asyncio
import base64
import ipaddress
import json
import logging
import logging.handlers
import os
import platform
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

VERSION = '1.0.0'
NOMBRE = 'Agente ASLAN'
PUERTO_UNICA_INSTANCIA = 48151
SEGUNDOS_LATIDO = 25

log = logging.getLogger('agente')


# =====================================================================================================================
# Carpeta de datos, registro y configuración
# =====================================================================================================================
def carpeta_datos():
    if os.environ.get('ASLAN_AGENTE_CARPETA'):   # pruebas: otra carpeta de datos
        return os.environ['ASLAN_AGENTE_CARPETA']
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'ASLAN Agente')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/ASLAN Agente')
    return os.path.expanduser('~/.aslan-agente')


CARPETA = carpeta_datos()


def configurar_registro(consola=False):
    os.makedirs(CARPETA, exist_ok=True)
    formato = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    archivo = logging.handlers.RotatingFileHandler(os.path.join(CARPETA, 'agente.log'), maxBytes=1_000_000,
                                                   backupCount=3, encoding='utf-8')
    archivo.setFormatter(formato)
    log.addHandler(archivo)
    if consola or not getattr(sys, 'frozen', False):
        pantalla = logging.StreamHandler()
        pantalla.setFormatter(formato)
        log.addHandler(pantalla)
    log.setLevel(logging.INFO)


def _proteger(texto):
    """La llave del agente se guarda cifrada con la cuenta de Windows (DPAPI): copiar el archivo a otro PC no sirve."""
    if sys.platform != 'win32':
        return 'plano:' + texto
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    datos = texto.encode('utf-8')
    entrada = Blob(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)), ctypes.POINTER(ctypes.c_char)))
    salida = Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise OSError('No se pudo cifrar la llave del agente.')
    try:
        return 'dpapi:' + base64.b64encode(ctypes.string_at(salida.pbData, salida.cbData)).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def _desproteger(guardado):
    if not guardado:
        return ''
    if guardado.startswith('plano:'):
        return guardado[6:]
    if guardado.startswith('dpapi:') and sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        datos = base64.b64decode(guardado[6:])
        entrada = Blob(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)), ctypes.POINTER(ctypes.c_char)))
        salida = Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
            return ''
        try:
            return ctypes.string_at(salida.pbData, salida.cbData).decode('utf-8')
        finally:
            ctypes.windll.kernel32.LocalFree(salida.pbData)
    return ''


class Configuracion:
    def __init__(self):
        self.ruta = os.path.join(CARPETA, 'config.json')
        self.servidor = ''
        self.llave = ''
        self.equipo = ''
        self.empresa = ''
        self.cargar()

    def cargar(self):
        try:
            with open(self.ruta, encoding='utf-8') as f:
                datos = json.load(f)
        except (OSError, ValueError):
            return
        self.servidor = datos.get('servidor', '')
        self.llave = _desproteger(datos.get('llave', ''))
        self.equipo = datos.get('equipo', '')
        self.empresa = datos.get('empresa', '')

    def guardar(self):
        os.makedirs(CARPETA, exist_ok=True)
        datos = {'servidor': self.servidor, 'llave': _proteger(self.llave) if self.llave else '',
                 'equipo': self.equipo, 'empresa': self.empresa}
        temporal = self.ruta + '.tmp'
        with open(temporal, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        try:
            os.chmod(temporal, 0o600)
        except OSError:
            pass
        os.replace(temporal, self.ruta)

    @property
    def vinculado(self):
        return bool(self.servidor and self.llave)

    def olvidar(self):
        self.llave = ''
        self.empresa = ''
        self.guardar()


def normalizar_servidor(texto):
    texto = (texto or '').strip().rstrip('/')
    if texto and '://' not in texto:
        texto = 'https://' + texto
    partes = urlsplit(texto)
    if partes.scheme not in ('https', 'http') or not partes.hostname:
        raise ValueError('Escriba la dirección con la que entra a ASLAN (ej. https://suempresa.aslan-multiagente.com).')
    if partes.scheme == 'http' and partes.hostname not in ('localhost', '127.0.0.1') \
            and not partes.hostname.endswith('.localhost'):
        raise ValueError('La dirección de ASLAN debe empezar por https://')
    return f'{partes.scheme}://{partes.netloc}'


def vincular(servidor, codigo, equipo):
    """Canjea el código de vinculación (generado en ASLAN › Configuraciones › Agente de la oficina) por la llave."""
    cuerpo = json.dumps({'codigo': codigo, 'equipo': equipo, 'sistema': descripcion_sistema(),
                         'version': VERSION}).encode('utf-8')
    peticion = Request(servidor + '/agente/api/vincular/', data=cuerpo, method='POST',
                       headers={'Content-Type': 'application/json', 'User-Agent': f'AgenteASLAN/{VERSION}'})
    try:
        with urlopen(peticion, timeout=20) as respuesta:
            return json.loads(respuesta.read().decode('utf-8'))
    except HTTPError as exc:
        try:
            mensaje = json.loads(exc.read().decode('utf-8')).get('error')
        except Exception:
            mensaje = None
        raise ValueError(mensaje or f'ASLAN respondió con un error ({exc.code}). Revise la dirección.') from exc
    except URLError as exc:
        raise ValueError(f'No se pudo conectar con {servidor}: {exc.reason}') from exc


def descripcion_sistema():
    if sys.platform == 'win32':
        return f'Windows {platform.release()}'
    if sys.platform == 'darwin':
        return f'macOS {platform.mac_ver()[0]}'
    return f'{platform.system()} {platform.release()}'


# =====================================================================================================================
# Navegador y servidor local de Playwright
# =====================================================================================================================
def detectar_navegador():
    """(canal de Playwright, nombre). Se prefiere el Chrome instalado; en Windows Edge siempre está."""
    if sys.platform == 'win32':
        bases = [os.environ.get(v) for v in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        for base in filter(None, bases):
            if os.path.exists(os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')):
                return 'chrome', 'Google Chrome'
        for base in filter(None, bases[:2]):
            if os.path.exists(os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe')):
                return 'msedge', 'Microsoft Edge'
    elif sys.platform == 'darwin':
        if os.path.exists('/Applications/Google Chrome.app'):
            return 'chrome', 'Google Chrome'
    elif shutil.which('google-chrome') or shutil.which('google-chrome-stable'):
        return 'chrome', 'Google Chrome'
    return '', 'Chromium'


def version_playwright():
    try:
        from playwright._repo_version import version
        return version
    except Exception:
        return ''


def puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServidorPlaywright:
    """`playwright run-server` en 127.0.0.1 con una ruta secreta: es quien abre y maneja el navegador de este PC."""

    def __init__(self):
        self.proceso = None
        self.puerto = None
        self.ruta = None
        self.navegadores = os.path.join(CARPETA, 'navegadores')

    def _comando(self, *args):
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        node, cli = compute_driver_executable()
        entorno = get_driver_env()
        entorno['PLAYWRIGHT_BROWSERS_PATH'] = self.navegadores
        return [node, cli, *args], entorno

    @staticmethod
    def _sin_ventana():
        return {'creationflags': 0x08000000} if sys.platform == 'win32' else {}   # CREATE_NO_WINDOW

    def instalar_chromium(self):
        """Solo si no hay Chrome ni Edge: descarga el Chromium de Playwright (una vez, ~150 MB)."""
        comando, entorno = self._comando('install', 'chromium')
        log.info('Descargando Chromium en %s …', self.navegadores)
        subprocess.run(comando, env=entorno, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=1800, **self._sin_ventana())

    def chromium_instalado(self):
        return os.path.isdir(self.navegadores) and any(n.startswith('chromium') for n in os.listdir(self.navegadores))

    @property
    def url(self):
        return f'ws://127.0.0.1:{self.puerto}{self.ruta}'

    def vivo(self):
        return self.proceso is not None and self.proceso.poll() is None

    def iniciar(self):
        self.detener()
        self.puerto = puerto_libre()
        self.ruta = '/' + secrets.token_hex(16)
        comando, entorno = self._comando('run-server', '--port', str(self.puerto), '--host', '127.0.0.1',
                                         '--path', self.ruta)
        salida = open(os.path.join(CARPETA, 'playwright.log'), 'a', encoding='utf-8')
        self.proceso = subprocess.Popen(comando, env=entorno, stdout=salida, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, **self._sin_ventana())
        limite = time.time() + 30
        while time.time() < limite:
            if self.proceso.poll() is not None:
                raise RuntimeError('El servidor de navegador se cerró al arrancar (ver playwright.log).')
            try:
                socket.create_connection(('127.0.0.1', self.puerto), timeout=1).close()
                log.info('Servidor de navegador listo en 127.0.0.1:%s', self.puerto)
                return
            except OSError:
                time.sleep(0.3)
        raise RuntimeError('El servidor de navegador no arrancó a tiempo.')

    def detener(self):
        if self.proceso is not None and self.proceso.poll() is None:
            self.proceso.terminate()
            try:
                self.proceso.wait(10)
            except subprocess.TimeoutExpired:
                self.proceso.kill()
        self.proceso = None


# =====================================================================================================================
# Proxy local: el navegador solo puede salir a internet, nunca a la red de la oficina
# =====================================================================================================================
def ip_publica(texto):
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


class ProxySeguro:
    def __init__(self):
        self.servidor = None
        self.puerto = None
        self.bloqueados = 0

    async def iniciar(self):
        self.servidor = await asyncio.start_server(self._atender, '127.0.0.1', 0)
        self.puerto = self.servidor.sockets[0].getsockname()[1]
        log.info('Proxy de protección escuchando en 127.0.0.1:%s', self.puerto)

    @staticmethod
    async def _resolver(host, puerto):
        """IP pública a la que conectarse, o None si el destino es de la red interna (o no existe)."""
        try:
            info = await asyncio.get_running_loop().getaddrinfo(host, puerto, type=socket.SOCK_STREAM)
        except OSError:
            return None
        ips = list(dict.fromkeys(i[4][0] for i in info))
        if not ips or not all(ip_publica(ip) for ip in ips):
            return None
        return ips   # se conecta a las IP ya revisadas: un DNS tramposo no puede cambiarlas después

    async def _atender(self, lector, escritor):
        try:
            linea = await asyncio.wait_for(lector.readline(), 30)
            cabeceras = []
            while True:
                h = await asyncio.wait_for(lector.readline(), 30)
                if h in (b'\r\n', b'\n', b''):
                    break
                cabeceras.append(h)
            metodo, destino, version = linea.decode('latin-1').strip().split(' ', 2)
            if metodo.upper() == 'CONNECT':
                host, _, puerto = destino.rpartition(':')
                host, puerto = host.strip('[]'), int(puerto or 443)
            else:
                partes = urlsplit(destino)
                if partes.scheme != 'http' or not partes.hostname:
                    raise ValueError('petición no válida')
                host, puerto = partes.hostname, partes.port or 80
            ips = await self._resolver(host, puerto)
            if ips is None:
                self.bloqueados += 1
                log.warning('Bloqueado: el navegador intentó llegar a %s:%s (red interna o inexistente).', host, puerto)
                escritor.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await escritor.drain()
                return
            remoto_l = remoto_e = None
            for ip in ips:   # IPv6 e IPv4: la primera que conteste
                try:
                    remoto_l, remoto_e = await asyncio.wait_for(asyncio.open_connection(ip, puerto), 10)
                    break
                except (OSError, asyncio.TimeoutError):
                    continue
            if remoto_e is None:
                escritor.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await escritor.drain()
                return
            if metodo.upper() == 'CONNECT':
                escritor.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                await escritor.drain()
            else:
                partes = urlsplit(destino)
                ruta = (partes.path or '/') + (('?' + partes.query) if partes.query else '')
                limpias = [h for h in cabeceras if not h.lower().startswith((b'proxy-', b'connection:', b'keep-alive:'))]
                remoto_e.write(f'{metodo} {ruta} {version}\r\n'.encode('latin-1') + b''.join(limpias) +
                               b'Connection: close\r\n\r\n')
                await remoto_e.drain()
            await asyncio.gather(self._pasar(lector, remoto_e), self._pasar(remoto_l, escritor))
        except Exception:
            pass
        finally:
            escritor.close()

    @staticmethod
    async def _pasar(lector, escritor):
        try:
            while True:
                datos = await lector.read(65536)
                if not datos:
                    break
                escritor.write(datos)
                await escritor.drain()
        except Exception:
            pass
        finally:
            try:
                escritor.close()
            except Exception:
                pass


# =====================================================================================================================
# Filtro de órdenes: solo pasa lo que necesita un bot para cotizar en un portal web
# =====================================================================================================================
METODOS_BLOQUEADOS = frozenset({
    'launch', 'launchPersistentContext', 'launchServer', 'connect', 'connectOverCDP', 'newRequest',
    'harOpen', 'harLookup', 'harUnzip', 'harClose', 'zip', 'saveAs', 'devices', 'newCDPSession', 'send',
})
CLAVES_BLOQUEADAS = frozenset({
    'proxy', 'localPaths', 'localDirectory', 'executablePath', 'recordHar', 'recordVideo', 'harPath',
    'downloadsPath', 'tracesDir', 'userDataDir', 'artifactsDir', 'cdpUrl', 'wsEndpoint',
})


def _claves(valor, nivel=0):
    if nivel > 4:
        return
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            yield clave, contenido
            yield from _claves(contenido, nivel + 1)
    elif isinstance(valor, list):
        for contenido in valor[:50]:
            yield from _claves(contenido, nivel + 1)


def motivo_bloqueo(texto):
    """None si la orden puede pasar al navegador; si no, por qué se rechaza."""
    try:
        mensaje = json.loads(texto)
    except (ValueError, TypeError):
        return 'mensaje ilegible'
    if not isinstance(mensaje, dict):
        return 'mensaje ilegible'
    metodo = mensaje.get('method')
    if metodo in METODOS_BLOQUEADOS:
        return f'orden no permitida: {metodo}'
    parametros = mensaje.get('params') or {}
    for clave, contenido in _claves(parametros):
        if clave in CLAVES_BLOQUEADAS and contenido not in (None, False, '', [], {}):
            return f'parámetro no permitido: {clave}'
    if metodo == 'goto':
        url = str(parametros.get('url', ''))
        if url != 'about:blank' and urlsplit(url).scheme not in ('http', 'https'):
            return 'solo se abren páginas web (http/https)'
    return None


# =====================================================================================================================
# Núcleo: conexión con ASLAN y sesiones de navegador
# =====================================================================================================================
class Agente:
    def __init__(self, configuracion):
        self.config = configuracion
        self.estado = 'iniciando'          # iniciando · preparando · sin_vincular · conectando · conectado · incompatible
        self.mensaje = 'Iniciando…'
        self.sesiones = 0
        self.total_sesiones = 0
        self.ultima_sesion = None
        self.descarga = ''
        self.canal, self.nombre_navegador = detectar_navegador()
        self.playwright = ServidorPlaywright()
        self.proxy = ProxySeguro()
        self.bucle = None
        self._cambio = None
        self._ws_control = None
        self.parar = False

    # ------------------------------------------------------------------ estado (lo lee la ventana)
    def _estado(self, estado, mensaje):
        if (estado, mensaje) != (self.estado, self.mensaje):
            log.info('Estado: %s — %s', estado, mensaje)
        self.estado, self.mensaje = estado, mensaje

    def configuracion_cambiada(self):
        """La ventana vinculó o desvinculó el equipo: se reconecta con los datos nuevos."""
        if self.bucle is not None:
            self.bucle.call_soon_threadsafe(self._despertar)

    def _despertar(self):
        self._cambio.set()
        if self._ws_control is not None:
            asyncio.ensure_future(self._ws_control.close(1000, 'Configuración cambiada'))

    # ------------------------------------------------------------------ arranque
    def correr(self):
        asyncio.run(self._principal())

    async def _principal(self):
        self.bucle = asyncio.get_running_loop()
        self._cambio = asyncio.Event()
        if not self.canal and not self.playwright.chromium_instalado():
            self._estado('preparando', 'Descargando el navegador (solo la primera vez, puede tardar unos minutos)…')
            await asyncio.to_thread(self.playwright.instalar_chromium)
        await self.proxy.iniciar()
        await asyncio.to_thread(self.playwright.iniciar)
        espera = 2
        while not self.parar:
            if not self.config.vinculado:
                self._estado('sin_vincular', 'Este equipo no está vinculado a ninguna empresa.')
                self._cambio.clear()
                await self._cambio.wait()
                continue
            self._cambio.clear()
            inicio = time.time()
            try:
                await self._control()
            except Exception as exc:
                if self.estado == 'sin_vincular':
                    continue
                if not self._cambio.is_set():
                    log.warning('Conexión con ASLAN: %s', exc)
            if self._cambio.is_set() or self.parar:
                espera = 2
                continue
            if time.time() - inicio > 60:
                espera = 2
            if self.estado != 'incompatible':
                self._estado('conectando', f'Sin conexión con ASLAN. Reintentando en {espera} s…')
            try:
                await asyncio.wait_for(self._cambio.wait(), espera)
            except asyncio.TimeoutError:
                pass
            espera = min(espera * 2, 60)

    def _ws(self, ruta):
        prueba = os.environ.get('ASLAN_AGENTE_RELAY')   # solo pruebas locales: ws://127.0.0.1:8008 (sin nginx)
        if prueba:
            return prueba.rstrip('/') + ruta
        partes = urlsplit(self.config.servidor)
        return f"{'wss' if partes.scheme == 'https' else 'ws'}://{partes.netloc}{ruta}"

    def _cabeceras(self):
        return {'Authorization': f'Bearer {self.config.llave}', 'User-Agent': f'AgenteASLAN/{VERSION}'}

    async def _control(self):
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        self._estado('conectando', f'Conectando con {self.config.servidor}…')
        try:
            ws = await connect(self._ws('/agente/ws/control'), additional_headers=self._cabeceras(), max_size=None,
                               open_timeout=20, ping_interval=20, ping_timeout=40, compression=None)
        except InvalidStatus as exc:
            if exc.response.status_code == 401:
                self._desvinculado()
            raise
        self._ws_control = ws
        latidos = None
        try:
            await ws.send(json.dumps({'tipo': 'hola', 'version': VERSION, 'playwright': version_playwright(),
                                      'sistema': descripcion_sistema(), 'navegador': self.nombre_navegador}))
            bienvenida = json.loads(await asyncio.wait_for(ws.recv(), 20))
            self.config.empresa = bienvenida.get('empresa', self.config.empresa)
            self.config.equipo = bienvenida.get('equipo', self.config.equipo)
            self.config.guardar()
            self.descarga = bienvenida.get('descarga', '')
            servidor_pw = str(bienvenida.get('playwright_servidor', ''))
            if servidor_pw and servidor_pw.split('.')[:2] != version_playwright().split('.')[:2]:
                self._estado('incompatible', 'Hay una versión nueva del agente: descárguela e instálela para seguir '
                                             'cotizando (el servidor usa otra versión del navegador).')
            elif _version(VERSION) < _version(bienvenida.get('version_minima', '0')):
                self._estado('incompatible', 'Hay una versión nueva del agente: descárguela e instálela.')
            else:
                self._estado('conectado', f'Conectado a {self.config.empresa or "ASLAN"} como «{self.config.equipo}».')
            latidos = asyncio.ensure_future(self._latir(ws))
            async for texto in ws:
                try:
                    orden = json.loads(texto)
                except ValueError:
                    continue
                if orden.get('tipo') == 'abrir' and orden.get('sid'):
                    asyncio.ensure_future(self._sesion(str(orden['sid']), bool(orden.get('headless', True))))
        except ConnectionClosed as exc:
            if exc.rcvd is not None and exc.rcvd.code == 4401:
                self._desvinculado()
            raise
        finally:
            self._ws_control = None
            if latidos is not None:
                latidos.cancel()
            await ws.close()

    def _desvinculado(self):
        log.warning('ASLAN rechazó la llave: el equipo fue desvinculado.')
        self.config.olvidar()
        self._estado('sin_vincular', 'Este equipo fue desvinculado en ASLAN. Vincúlelo de nuevo con un código.')

    @staticmethod
    async def _latir(ws):
        while True:
            await asyncio.sleep(SEGUNDOS_LATIDO)
            await ws.send(json.dumps({'tipo': 'latido'}))

    async def _sesion(self, sid, headless):
        """Un navegador para un bot: une la conexión de ASLAN con el servidor local de Playwright."""
        from websockets.asyncio.client import connect

        self.sesiones += 1
        self.total_sesiones += 1
        self.ultima_sesion = time.strftime('%I:%M %p')
        remoto = local = None
        try:
            if not self.playwright.vivo():
                await asyncio.to_thread(self.playwright.iniciar)
            remoto = await connect(self._ws(f'/agente/ws/datos/{sid}'), additional_headers=self._cabeceras(),
                                   max_size=None, open_timeout=20, ping_interval=20, ping_timeout=60, compression=None)
            opciones = {'headless': headless, 'timeout': 60000,
                        'proxy': {'server': f'http://127.0.0.1:{self.proxy.puerto}'}}
            if self.canal:
                opciones['channel'] = self.canal
            local = await connect(self.playwright.url, max_size=None, open_timeout=60, ping_interval=None,
                                  compression=None,
                                  additional_headers={'x-playwright-browser': 'chromium',
                                                      'x-playwright-launch-options': json.dumps(opciones)})
            log.info('Sesión %s: navegador abierto (%s).', sid[:6], 'oculto' if headless else 'visible')
            await self._unir(remoto, local, sid)
        except Exception as exc:
            log.warning('Sesión %s: %s', sid[:6], exc)
        finally:
            for conexion in (local, remoto):
                if conexion is not None:
                    try:
                        await conexion.close()
                    except Exception:
                        pass
            self.sesiones -= 1
            log.info('Sesión %s terminada.', sid[:6])

    @staticmethod
    async def _unir(remoto, local, sid):
        async def de_aslan():
            async for mensaje in remoto:
                texto = mensaje.decode('utf-8', 'replace') if isinstance(mensaje, bytes) else mensaje
                motivo = motivo_bloqueo(texto)
                if motivo:
                    log.warning('Sesión %s cerrada: %s.', sid[:6], motivo)
                    return
                await local.send(mensaje)

        async def hacia_aslan():
            async for mensaje in local:
                await remoto.send(mensaje)

        tareas = [asyncio.ensure_future(de_aslan()), asyncio.ensure_future(hacia_aslan())]
        await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
        for tarea in tareas:
            tarea.cancel()

    def apagar(self):
        self.parar = True
        self.playwright.detener()


def _version(texto):
    try:
        return tuple(int(p) for p in str(texto).split('.')[:3])
    except ValueError:
        return (0,)


# =====================================================================================================================
# Una sola copia abierta
# =====================================================================================================================
def tomar_instancia_unica(al_pedir_mostrar):
    """Si ya hay un agente abierto, le pide que se muestre y devuelve None. Si no, deja escuchando el aviso."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        servidor.bind(('127.0.0.1', PUERTO_UNICA_INSTANCIA))
    except OSError:
        servidor.close()
        try:
            socket.create_connection(('127.0.0.1', PUERTO_UNICA_INSTANCIA), timeout=2).close()
        except OSError:
            pass
        return None
    servidor.listen(2)

    def escuchar():
        while True:
            try:
                conexion, _ = servidor.accept()
                conexion.close()
                al_pedir_mostrar()
            except OSError:
                return
    threading.Thread(target=escuchar, daemon=True).start()
    return servidor


# =====================================================================================================================
# Ventana
# =====================================================================================================================
COLORES = {'conectado': '#15803d', 'conectando': '#b45309', 'preparando': '#0e7490', 'iniciando': '#0e7490',
           'sin_vincular': '#b91c1c', 'incompatible': '#b91c1c'}


class Ventana:
    def __init__(self, agente, oculto=False):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.agente = agente
        self.pedidos = queue.Queue()
        self.raiz = tk.Tk()
        self.raiz.title(NOMBRE)
        self.raiz.geometry('560x430')
        self.raiz.minsize(480, 380)
        self.raiz.protocol('WM_DELETE_WINDOW', self._minimizar)
        icono = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'aslan.ico')
        if sys.platform == 'win32' and os.path.exists(icono):
            try:
                self.raiz.iconbitmap(icono)
            except Exception:
                pass
        self._avisado = False
        marco = ttk.Frame(self.raiz, padding=18)
        marco.pack(fill='both', expand=True)
        ttk.Label(marco, text=NOMBRE, font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(marco, text=f'Versión {VERSION} · navegador: {agente.nombre_navegador}', foreground='#64748b').pack(anchor='w')
        self.lbl_estado = tk.Label(marco, text='', font=('Segoe UI', 12, 'bold'), anchor='w', justify='left', wraplength=500)
        self.lbl_estado.pack(fill='x', pady=(14, 2))
        self.lbl_detalle = ttk.Label(marco, text='', foreground='#475569', wraplength=500, justify='left')
        self.lbl_detalle.pack(fill='x')

        # Vinculación
        self.frm_vincular = ttk.LabelFrame(marco, text=' Vincular este equipo ', padding=12)
        ttk.Label(self.frm_vincular, text='Dirección de ASLAN (la que usa para entrar):').grid(row=0, column=0, sticky='w')
        self.txt_servidor = ttk.Entry(self.frm_vincular, width=48)
        self.txt_servidor.grid(row=1, column=0, sticky='we', pady=(0, 8))
        ttk.Label(self.frm_vincular, text='Código de vinculación (Configuraciones › Agente de la oficina):').grid(row=2, column=0, sticky='w')
        self.txt_codigo = ttk.Entry(self.frm_vincular, width=20, font=('Consolas', 14))
        self.txt_codigo.grid(row=3, column=0, sticky='w', pady=(0, 8))
        ttk.Label(self.frm_vincular, text='Nombre de este equipo:').grid(row=4, column=0, sticky='w')
        self.txt_equipo = ttk.Entry(self.frm_vincular, width=32)
        self.txt_equipo.grid(row=5, column=0, sticky='w', pady=(0, 8))
        self.btn_vincular = ttk.Button(self.frm_vincular, text='Vincular', command=self._vincular)
        self.btn_vincular.grid(row=6, column=0, sticky='w')
        self.frm_vincular.columnconfigure(0, weight=1)
        self.txt_servidor.insert(0, agente.config.servidor or 'https://')
        self.txt_equipo.insert(0, agente.config.equipo or socket.gethostname()[:60])

        # Pie
        pie = ttk.Frame(marco)
        pie.pack(side='bottom', fill='x', pady=(12, 0))
        ttk.Button(pie, text='Salir', command=self._salir).pack(side='right')
        ttk.Button(pie, text='Ver registro', command=self._abrir_registro).pack(side='right', padx=6)
        self.btn_desvincular = ttk.Button(pie, text='Desvincular este equipo', command=self._desvincular)
        self.btn_desvincular.pack(side='left')
        self.btn_descargar = ttk.Button(pie, text='Descargar la versión nueva', command=self._descargar)
        self.raiz.after(300, self._refrescar)
        if oculto and agente.config.vinculado:
            self.raiz.iconify()

    def pedir_mostrar(self):
        self.pedidos.put('mostrar')

    def _refrescar(self):
        while not self.pedidos.empty():
            if self.pedidos.get() == 'mostrar':
                self.raiz.deiconify()
                self.raiz.lift()
        a = self.agente
        titulos = {'conectado': '● Conectado', 'conectando': '● Sin conexión', 'preparando': '● Preparando',
                   'iniciando': '● Iniciando', 'sin_vincular': '● Sin vincular', 'incompatible': '● Debe actualizarse'}
        self.lbl_estado.config(text=titulos.get(a.estado, a.estado), fg=COLORES.get(a.estado, '#0f172a'))
        detalle = a.mensaje
        if a.estado == 'conectado':
            detalle += f'\nNavegadores abiertos ahora: {a.sesiones}'
            if a.ultima_sesion:
                detalle += f' · Último a las {a.ultima_sesion} · Hoy: {a.total_sesiones}'
            detalle += '\nDeje este programa abierto (puede minimizarlo). Si una aseguradora pide una persona, la ventana sale aquí.'
        self.lbl_detalle.config(text=detalle)
        if a.estado == 'sin_vincular':
            self.frm_vincular.pack(fill='x', pady=12)
            self.btn_desvincular.state(['disabled'])
        else:
            self.frm_vincular.pack_forget()
            self.btn_desvincular.state(['!disabled'])
        if a.estado == 'incompatible':
            self.btn_descargar.pack(side='left', padx=6)
        else:
            self.btn_descargar.pack_forget()
        self.raiz.after(1000, self._refrescar)

    def _vincular(self):
        from tkinter import messagebox
        try:
            servidor = normalizar_servidor(self.txt_servidor.get())
        except ValueError as exc:
            messagebox.showerror(NOMBRE, str(exc))
            return
        codigo, equipo = self.txt_codigo.get().strip(), self.txt_equipo.get().strip() or socket.gethostname()
        self.btn_vincular.state(['disabled'])

        def trabajo():
            try:
                respuesta = vincular(servidor, codigo, equipo)
                if not respuesta.get('llave'):
                    raise ValueError(respuesta.get('error') or 'ASLAN no entregó la llave.')
            except ValueError as exc:
                error = str(exc)
                self.raiz.after(0, lambda: (messagebox.showerror(NOMBRE, error), self.btn_vincular.state(['!disabled'])))
                return
            c = self.agente.config
            c.servidor, c.llave, c.equipo, c.empresa = servidor, respuesta['llave'], respuesta.get('equipo', equipo), respuesta.get('empresa', '')
            c.guardar()
            self.agente.configuracion_cambiada()
            self.raiz.after(0, lambda: (self.txt_codigo.delete(0, 'end'), self.btn_vincular.state(['!disabled']),
                                        messagebox.showinfo(NOMBRE, f'Listo: este equipo quedó vinculado a {c.empresa}.')))
        threading.Thread(target=trabajo, daemon=True).start()

    def _desvincular(self):
        from tkinter import messagebox
        if messagebox.askyesno(NOMBRE, '¿Desvincular este equipo? Dejará de cotizar hasta que se vincule de nuevo con un código.'):
            self.agente.config.olvidar()
            self.agente.configuracion_cambiada()

    def _descargar(self):
        destino = self.agente.descarga or '/descargas/ASLAN-Agente-Setup.exe'
        if destino.startswith('/'):
            destino = self.agente.config.servidor + destino
        webbrowser.open(destino)

    @staticmethod
    def _abrir_registro():
        ruta = os.path.join(CARPETA, 'agente.log')
        if sys.platform == 'win32':
            os.startfile(ruta)  # noqa: S606 — el registro propio del agente
        else:
            webbrowser.open('file://' + ruta)

    def _minimizar(self):
        from tkinter import messagebox
        if not self._avisado:
            self._avisado = True
            messagebox.showinfo(NOMBRE, 'El agente sigue funcionando minimizado: así ASLAN puede cotizar Mapfre y La '
                                        'Equidad. Para cerrarlo del todo use el botón «Salir».')
        self.raiz.iconify()

    def _salir(self):
        from tkinter import messagebox
        if messagebox.askyesno(NOMBRE, 'Si cierra el agente, ASLAN no podrá cotizar desde este equipo hasta que lo abra de '
                                       'nuevo. ¿Cerrarlo?'):
            self.agente.apagar()
            self.raiz.destroy()

    def correr(self):
        self.raiz.mainloop()


# =====================================================================================================================
def main():
    parser = argparse.ArgumentParser(description=NOMBRE)
    parser.add_argument('--oculto', action='store_true', help='arrancar minimizado')
    parser.add_argument('--consola', action='store_true', help='sin ventana')
    parser.add_argument('--servidor', help='(consola) dirección de ASLAN para vincular')
    parser.add_argument('--codigo', help='(consola) código de vinculación')
    parser.add_argument('--equipo', help='(consola) nombre del equipo')
    args = parser.parse_args()
    configurar_registro(consola=args.consola)
    log.info('%s %s · Playwright %s · %s', NOMBRE, VERSION, version_playwright(), descripcion_sistema())

    configuracion = Configuracion()
    agente = Agente(configuracion)

    if args.consola:
        if args.codigo:
            servidor = normalizar_servidor(args.servidor or configuracion.servidor)
            respuesta = vincular(servidor, args.codigo, args.equipo or socket.gethostname())
            configuracion.servidor, configuracion.llave = servidor, respuesta['llave']
            configuracion.equipo, configuracion.empresa = respuesta.get('equipo', ''), respuesta.get('empresa', '')
            configuracion.guardar()
            log.info('Equipo vinculado a %s.', configuracion.empresa)
        try:
            agente.correr()
        except KeyboardInterrupt:
            pass
        finally:
            agente.apagar()
        return

    ventana_holder = {}
    if tomar_instancia_unica(lambda: ventana_holder['v'].pedir_mostrar() if 'v' in ventana_holder else None) is None:
        return   # ya había uno abierto: se le pidió que se muestre
    hilo = threading.Thread(target=agente.correr, daemon=True)
    hilo.start()
    ventana = Ventana(agente, oculto=args.oculto)
    ventana_holder['v'] = ventana
    ventana.correr()
    agente.apagar()


if __name__ == '__main__':
    main()

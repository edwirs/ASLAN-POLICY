# Agente ASLAN: puesta en marcha

El **Agente ASLAN** se instala en un PC de la oficina del cliente. Los bots siguen corriendo en el VPS, pero manejan el
navegador de ese PC. Así:

- el portal ve la red de la oficina, y La Equidad deja de bloquear;
- la ventana del captcha de Mapfre sale en ese PC.

```
bot (VPS) ──ws://127.0.0.1:8008──▶ relevo (aslan-relay) ◀──wss:// /agente/ws/ (443)── Agente ASLAN (PC oficina) ─▶ Chrome/Edge
```

Piezas del sistema:

| Pieza | Archivo |
|---|---|
| Relevo | `core/tenants/management/commands/relay_agentes.py` |
| Datos de los agentes | `core/tenants/agentes.py` |
| Pantalla «Agente de la oficina» y API de vinculación | `core/policies/views/agente/views.py` |
| Programa del agente | `agente/aslan_agente.py` |
| Instalador | `agente/instalador.iss` y `.github/workflows/agente-windows.yml` |

## 1. VPS (una sola vez)

```bash
cd ~/aslan-multiagente/ASLAN-POLICY
git pull
venv/bin/python manage.py respaldo_crear
venv/bin/python -m pip install -r deploy/txt/requirements.txt     # playwright 1.60.0 + websockets
venv/bin/python -m playwright install chromium                    # por si cambió la versión de Playwright
venv/bin/python manage.py migrate_schemas --shared                # tablas AgenteLocal y CodigoVinculacion
sudo systemctl restart <servicio-de-gunicorn>
```

### Relevo (servicio)

```bash
sudo cp deploy/agente/aslan-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aslan-relay
systemctl status aslan-relay          # debe decir active (running)
```

### nginx

1. Pegue el contenido de `deploy/agente/nginx-agente.conf` dentro del bloque `server` con `listen 443` del dominio de las empresas.
2. Luego ejecute:

```bash
mkdir -p ~/aslan-multiagente/descargas && chmod o+rx ~/aslan-multiagente/descargas
sudo nginx -t && sudo systemctl reload nginx
```

### Prueba

Desde cualquier PC:

```bash
curl -i https://gali.aslan-multiagente.com/agente/ws/control
```

Debe responder `401 Falta la llave del agente`.

- Si responde **404**, nginx no está pasando `/agente/ws/`.
- Si responde **502**, el relevo no está corriendo.

## 2. Instalador para Windows

1. En GitHub, abra **Actions › «Agente ASLAN (Windows)» › Run workflow**.
2. Al terminar, descargue el artefacto **ASLAN-Agente-Setup** (es un .zip con el .exe dentro).
3. Súbalo al VPS:

```bash
scp ASLAN-Agente-Setup.exe edwin@148.230.86.99:~/aslan-multiagente/descargas/
chmod o+r ~/aslan-multiagente/descargas/ASLAN-Agente-Setup.exe
```

4. Pruebe que el botón «Descargar Agente ASLAN» de la pantalla «Agente de la oficina» lo baja.

Sin certificado de firma de código, Windows SmartScreen muestra «Windows protegió su PC». Se continúa con **Más información › Ejecutar de todas formas**. Para quitar ese aviso hay que comprar un certificado de firma de código (OV o EV) y firmar el .exe en el workflow.

## 3. En cada oficina

1. En ASLAN, abra **Configuraciones › Agente de la oficina › Generar código**.
2. En el PC de la oficina, descargue e instale el agente. No pide administrador y queda arrancando con Windows.
3. Escriba en el agente la dirección de ASLAN (ej. `https://gali.aslan-multiagente.com`) y el código. El código vence en 15 minutos y sirve una sola vez.
4. Cuando el agente diga **● Conectado**, el equipo sale **En línea** en ASLAN.
5. Revise **Aseguradoras › Editar › «Dónde se cotiza»**:
   - Mapfre y La Equidad vienen en «Agente de la oficina si está encendido».
   - Las demás vienen en «Servidor de ASLAN».
   - Seguros del Estado no tiene la opción: se sigue cotizando a mano.

Para Mapfre conviene un agente en el PC de cada asesor que cotiza. La ventana sale en el equipo del asesor que creó la solicitud, si su agente está en línea; si no, en cualquier otro equipo en línea.

## Seguridad

- El PC solo hace conexiones de salida por HTTPS: no se abren puertos.
- La llave del agente se guarda cifrada con la cuenta de Windows (DPAPI).
- En ASLAN solo se guarda el SHA-256 de la llave.
- **Desvincular** corta al agente en menos de 30 s.
- Las contraseñas de los portales no se guardan en el PC.
- El navegador del agente sale por un proxy local que bloquea toda dirección de red interna: 192.168.x, 10.x, el router y el propio PC.
- El agente rechaza las órdenes que un bot no usa, y la sesión se corta: leer o escribir archivos del PC, abrir `file://`, cambiar el proxy, hacer peticiones HTTP fuera del navegador o usar CDP.
- El relevo solo publica `/agente/ws/`. La ruta de los bots (`/interno/`) exige una clave interna y rechaza lo que llegue por nginx.

## Versiones

El agente y el VPS deben tener la **misma versión mayor.menor de Playwright** (hoy 1.60). Si se cambia en `deploy/txt/requirements.txt`, hay que hacer tres cosas:

1. Cambiarla también en `agente/requirements.txt`.
2. Subir `VERSION` en `agente/aslan_agente.py`.
3. Recompilar el instalador.

Los agentes viejos avisan «Debe actualizarse» y muestran un botón para bajar el nuevo. `AGENTE_VERSION_MINIMA` (en `.env.secrets`) obliga a actualizar.

Los cambios a los bots no requieren actualizar el agente: los bots viven en el VPS.

# LP Assistant

LP Assistant es un asistente de voz pensado para Windows 11 que dicta texto en cualquier campo seleccionado y ejecuta comandos de productividad mediante la voz.

## Funcionalidades

- **Escuchar**: inicia la transcripción global con puntuación por voz.
- **Escuchar libremente**: dicta sin comandos ni puntuación por voz.
- **Escuchar comandos**: escucha comandos sin transcribir.
- **Detener**: detiene la transcripción.
- **Seleccionar todo**: envía `CTRL + A`.
- **Copiar**: envía `CTRL + C`.
- **Pegar**: envía `CTRL + V`.
- **Deshacer / Rehacer**: envía `CTRL + Z` / `CTRL + Y`.
- **Guardar**: envía `CTRL + S`.
- **Cerrar pestaña / ventana**: envía `CTRL + W` / `ALT + F4`.
- **Salto de línea**: envía `Enter`.
- **Borrar última palabra**: envía `CTRL + Backspace`.
- **Mover cursor**: flechas, `CTRL + flecha`, `Home` y `End`.
- **Página arriba / abajo**: envía `Page Up` / `Page Down`.
- **Mover teclado**: envía `Tab` / `Shift + Tab`.
- **Mejorar texto**: corrige ortografía, mayúsculas y puntuación con LanguageTool (gratis).

## Requisitos

- Windows 11
- Python 3.10+
- Micrófono disponible
- `setuptools` (necesario en Python 3.12+ para LanguageTool)

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Descargar modelo Vosk

Descarga el modelo en español y colócalo en `lpassistant/models/`.

- Modelo sugerido: `vosk-model-small-es-0.42`
- URL: https://alphacephei.com/vosk/models

La ruta final debe quedar así:

```
lpassistant/
  models/
    vosk-model-small-es-0.42/
```

## Uso

```bash
python -m lpassistant.gui
```

## Notas

- El asistente escucha continuamente las palabras clave "Escuchar", "Escuchar libremente", "Escuchar comandos" y "Detener".
- Para "Mejorar texto", selecciona el texto en cualquier aplicación antes de dictar el comando.
- Si aparece el estado "Modelo no encontrado", verifica que descargaste el modelo Vosk y que la carpeta exista en `lpassistant/models/`.

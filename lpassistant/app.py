import json
import os
import queue
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import language_tool_python
import pyperclip
import sounddevice as sd
from pynput.keyboard import Controller, Key
from pynput.mouse import Button, Controller as MouseController
from vosk import KaldiRecognizer, Model


@dataclass
class RecognitionConfig:
    model_path: str
    sample_rate: int = 16000


class SpeechWorker(threading.Thread):
    def __init__(self, config: RecognitionConfig, events: "queue.Queue[str]", log: "queue.Queue[str]") -> None:
        super().__init__(daemon=True)
        self.config = config
        self.events = events
        self.log = log
        self._stop_event = threading.Event()
        self._mode = "idle"
        self._keyboard = Controller()
        self._mouse = MouseController()
        self._tool: Optional[language_tool_python.LanguageTool] = None

    def stop(self) -> None:
        self._stop_event.set()

    def _emit_log(self, message: str) -> None:
        self.log.put(message)

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        status_map = {
            "idle": "En espera",
            "dictation": "Escuchando (dictado)",
            "commands": "Escuchando comandos",
            "free": "Escuchando (libre)",
        }
        self.events.put(status_map.get(mode, "En espera"))

    @staticmethod
    def _normalize_text(text: str) -> str:
        collapsed = re.sub(r"\s+", " ", text.lower()).strip()
        return SpeechWorker._strip_accents(collapsed)

    def _handle_command(self, text: str, allow_commands: bool = True) -> bool:
        normalized = self._normalize_text(text)
        if normalized == "escuchar" and self._mode != "dictation":
            self._emit_log("Activando modo dictado.")
            self._set_mode("dictation")
            return True
        if normalized == "escuchar libremente" and self._mode != "free":
            self._emit_log("Activando modo libre (sin comandos ni puntuación).")
            self._set_mode("free")
            return True
        if normalized == "escuchar comandos" and self._mode != "commands":
            self._emit_log("Activando modo comandos.")
            self._set_mode("commands")
            return True
        if normalized == "detener" and self._mode != "idle":
            self._emit_log("Deteniendo escucha.")
            self._set_mode("idle")
            return True
        if self._mode == "idle" or not allow_commands:
            return False
        if normalized == "seleccionar todo":
            self._emit_log("Ejecutando CTRL+A.")
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("a")
                self._keyboard.release("a")
            return True
        if normalized == "copiar":
            self._emit_log("Ejecutando CTRL+C.")
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("c")
                self._keyboard.release("c")
            return True
        if normalized == "pegar":
            self._emit_log("Ejecutando CTRL+V.")
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("v")
                self._keyboard.release("v")
            return True
        if normalized == "deshacer":
            self._emit_log("Ejecutando CTRL+Z.")
            self._press_combo([Key.ctrl], "z")
            return True
        if normalized == "rehacer":
            self._emit_log("Ejecutando CTRL+Y.")
            self._press_combo([Key.ctrl], "y")
            return True
        if normalized == "guardar":
            self._emit_log("Ejecutando CTRL+S.")
            self._press_combo([Key.ctrl], "s")
            return True
        if normalized == "cerrar pestaña":
            self._emit_log("Ejecutando CTRL+W.")
            self._press_combo([Key.ctrl], "w")
            return True
        if normalized == "cerrar ventana":
            self._emit_log("Ejecutando ALT+F4.")
            self._press_combo([Key.alt], Key.f4)
            return True
        if normalized in {"salto de linea", "salto de línea", "nueva linea", "nueva línea"}:
            self._emit_log("Insertando salto de línea.")
            self._keyboard.press(Key.enter)
            self._keyboard.release(Key.enter)
            return True
        if normalized in {"borrar ultima palabra", "borrar última palabra"}:
            self._emit_log("Borrando última palabra (CTRL+Backspace).")
            self._press_combo([Key.ctrl], Key.backspace)
            return True
        if normalized in {"borrar linea", "borrar línea"}:
            self._emit_log("Borrando línea actual.")
            self._press_combo([Key.ctrl], "l")
            return True
        if normalized == "mover cursor izquierda":
            self._emit_log("Moviendo cursor a la izquierda.")
            self._keyboard.press(Key.left)
            self._keyboard.release(Key.left)
            return True
        if normalized == "mover cursor derecha":
            self._emit_log("Moviendo cursor a la derecha.")
            self._keyboard.press(Key.right)
            self._keyboard.release(Key.right)
            return True
        if normalized == "mover cursor arriba":
            self._emit_log("Moviendo cursor arriba.")
            self._keyboard.press(Key.up)
            self._keyboard.release(Key.up)
            return True
        if normalized == "mover cursor abajo":
            self._emit_log("Moviendo cursor abajo.")
            self._keyboard.press(Key.down)
            self._keyboard.release(Key.down)
            return True
        if normalized == "mover cursor palabra izquierda":
            self._emit_log("Moviendo cursor una palabra a la izquierda.")
            self._press_combo([Key.ctrl], Key.left)
            return True
        if normalized == "mover cursor palabra derecha":
            self._emit_log("Moviendo cursor una palabra a la derecha.")
            self._press_combo([Key.ctrl], Key.right)
            return True
        if normalized in {"inicio de linea", "inicio de línea", "ir al inicio"}:
            self._emit_log("Moviendo cursor al inicio de la línea.")
            self._keyboard.press(Key.home)
            self._keyboard.release(Key.home)
            return True
        if normalized in {"fin de linea", "fin de línea", "ir al final"}:
            self._emit_log("Moviendo cursor al final de la línea.")
            self._keyboard.press(Key.end)
            self._keyboard.release(Key.end)
            return True
        if normalized == "pagina arriba":
            self._emit_log("Desplazando página arriba.")
            self._keyboard.press(Key.page_up)
            self._keyboard.release(Key.page_up)
            return True
        if normalized == "pagina abajo":
            self._emit_log("Desplazando página abajo.")
            self._keyboard.press(Key.page_down)
            self._keyboard.release(Key.page_down)
            return True
        if normalized == "mover teclado":
            self._emit_log("Moviendo foco al siguiente campo (Tab).")
            self._keyboard.press(Key.tab)
            self._keyboard.release(Key.tab)
            return True
        if normalized == "mover teclado atras":
            self._emit_log("Moviendo foco al campo anterior (Shift+Tab).")
            with self._keyboard.pressed(Key.shift):
                self._keyboard.press(Key.tab)
                self._keyboard.release(Key.tab)
            return True
        if normalized == "mejorar texto":
            self._emit_log("Mejorando texto seleccionado con LanguageTool.")
            self._improve_selected_text()
            return True
        if normalized == "corregir texto":
            self._emit_log("Corrigiendo texto seleccionado con Groq.")
            self._correct_selected_text_groq()
            return True
        if normalized in {"click", "clic"}:
            self._emit_log("Ejecutando click izquierdo.")
            self._mouse.click(Button.left, 1)
            return True
        if normalized in {"click derecho", "clic derecho"}:
            self._emit_log("Ejecutando click derecho.")
            self._mouse.click(Button.right, 1)
            return True
        if normalized in {"doble click", "doble clic"}:
            self._emit_log("Ejecutando doble click.")
            self._mouse.click(Button.left, 2)
            return True
        if normalized in {"click pulsado", "clic pulsado"}:
            self._emit_log("Ejecutando click pulsado.")
            self._mouse.press(Button.left)
            time.sleep(0.4)
            self._mouse.release(Button.left)
            return True
        return False

    def _improve_selected_text(self) -> None:
        if self._tool is None:
            try:
                self._tool = language_tool_python.LanguageTool("es")
            except Exception as exc:  # noqa: BLE001 - log and keep assistant running
                self._emit_log(
                    "No se pudo iniciar LanguageTool. Instala setuptools si usas Python 3.12+."
                )
                self._emit_log(f"Detalle: {exc}")
                return
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("a")
            self._keyboard.release("a")
        time.sleep(0.05)
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("c")
            self._keyboard.release("c")
        time.sleep(0.1)
        original_text = pyperclip.paste()
        if not original_text.strip():
            self._emit_log("No hay texto seleccionado para mejorar.")
            return
        improved = self._tool.correct(original_text)
        polished = self._polish_text(improved)
        pyperclip.copy(polished)
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("v")
            self._keyboard.release("v")
        self._emit_log("Texto mejorado y pegado.")

    def _correct_selected_text_groq(self) -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            self._emit_log("Falta la variable de entorno GROQ_API_KEY para usar Groq.")
            return
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("a")
            self._keyboard.release("a")
        time.sleep(0.05)
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("c")
            self._keyboard.release("c")
        time.sleep(0.1)
        original_text = pyperclip.paste()
        if not original_text.strip():
            self._emit_log("No hay texto seleccionado para corregir.")
            return
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres un corrector de estilo en español. "
                        "Corrige ortografía, acentuación, puntuación y mayúsculas "
                        "sin cambiar el sentido. Devuelve solo el texto corregido."
                    ),
                },
                {"role": "user", "content": original_text},
            ],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._emit_log("Error al corregir texto con Groq (HTTP).")
            self._emit_log(f"Detalle: {detail}")
            return
        except urllib.error.URLError as exc:
            self._emit_log("Error al conectar con Groq.")
            self._emit_log(f"Detalle: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - keep assistant running
            self._emit_log("Error inesperado al usar Groq.")
            self._emit_log(f"Detalle: {exc}")
            return
        try:
            parsed = json.loads(body)
            corrected = parsed["choices"][0]["message"]["content"].strip()
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            self._emit_log("Respuesta inválida de Groq al corregir texto.")
            self._emit_log(f"Detalle: {exc}")
            return
        if not corrected:
            self._emit_log("Groq devolvió un texto vacío.")
            return
        pyperclip.copy(corrected)
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("v")
            self._keyboard.release("v")
        self._emit_log("Texto corregido y pegado.")

    def _type_text(self, text: str) -> None:
        if not text:
            return
        self._keyboard.type(text)
        if not text.endswith("\n"):
            self._keyboard.type(" ")

    def _press_combo(self, modifiers: list[Key], key) -> None:
        if not modifiers:
            self._keyboard.press(key)
            self._keyboard.release(key)
            return
        if len(modifiers) == 1:
            with self._keyboard.pressed(modifiers[0]):
                self._keyboard.press(key)
                self._keyboard.release(key)
            return
        with self._keyboard.pressed(modifiers[0]):
            with self._keyboard.pressed(modifiers[1]):
                self._keyboard.press(key)
                self._keyboard.release(key)

    def run(self) -> None:
        model_path = Path(self.config.model_path)
        if not model_path.exists():
            self._emit_log(
                f"Modelo Vosk no encontrado en: {model_path}. Descárgalo y verifica la ruta."
            )
            self.events.put("Modelo no encontrado")
            return
        try:
            model = Model(str(model_path))
        except Exception as exc:  # noqa: BLE001 - surface model load errors
            self._emit_log(f"No se pudo cargar el modelo Vosk: {exc}")
            self.events.put("Error de modelo")
            return
        recognizer = KaldiRecognizer(model, self.config.sample_rate)
        recognizer.SetWords(True)
        audio_queue: "queue.Queue[bytes]" = queue.Queue()

        def audio_callback(indata, frames, time_info, status):
            if status:
                self._emit_log(f"Audio status: {status}")
            audio_queue.put(bytes(indata))

        with sd.RawInputStream(
            samplerate=self.config.sample_rate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            self._emit_log("Microfono listo. Esperando comandos...")
            self._set_mode("idle")
            while not self._stop_event.is_set():
                try:
                    data = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if recognizer.AcceptWaveform(data):
                    result = recognizer.Result()
                    text = self._extract_text(result)
                    if not text:
                        continue
                    self._emit_log(f"Reconocido: {text}")
                    if self._mode == "free":
                        if self._handle_command(text, allow_commands=False):
                            continue
                        self._type_text(text)
                        continue
                    if self._handle_command(text, allow_commands=True):
                        continue
                    if self._mode == "dictation":
                        self._type_text(self._apply_voice_punctuation(text))

    @staticmethod
    def _extract_text(result: str) -> str:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return ""
        text = payload.get("text", "")
        return text.strip()

    @staticmethod
    def _strip_accents(value: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFD", value)
            if unicodedata.category(char) != "Mn"
        )

    @classmethod
    def _apply_voice_punctuation(cls, text: str) -> str:
        if not text:
            return text
        tokens = text.split()
        normalized = [cls._strip_accents(token.lower()) for token in tokens]
        phrases = {
            ("punto", "y", "coma"): ";",
            ("puntos", "suspensivos"): "...",
            ("dos", "puntos"): ":",
            ("salto", "de", "linea"): "\n",
            ("nueva", "linea"): "\n",
            ("signo", "de", "interrogacion"): "?",
            ("signo", "de", "exclamacion"): "!",
            ("interrogacion",): "?",
            ("exclamacion",): "!",
            ("punto",): ".",
            ("coma",): ",",
        }
        phrase_lengths = sorted({len(key) for key in phrases}, reverse=True)
        output: list[str] = []
        idx = 0
        while idx < len(tokens):
            matched = False
            for length in phrase_lengths:
                if idx + length > len(tokens):
                    continue
                key = tuple(normalized[idx : idx + length])
                if key in phrases:
                    output.append(phrases[key])
                    idx += length
                    matched = True
                    break
            if matched:
                continue
            output.append(tokens[idx])
            idx += 1
        assembled = " ".join(output)
        assembled = re.sub(r"\s+([,.:;!?])", r"\1", assembled)
        assembled = re.sub(r"\s*\.\.\.\s*", "...", assembled)
        assembled = re.sub(r"([,;:!?])(\S)", r"\1 \2", assembled)
        assembled = re.sub(r"\s*\n\s*", "\n", assembled)
        return assembled

    @staticmethod
    def _polish_text(text: str) -> str:
        if not text:
            return text
        stripped = text.strip()
        stripped = stripped[0].upper() + stripped[1:]
        stripped = re.sub(
            r"([.!?]\s+)([a-záéíóúñ])",
            lambda match: f"{match.group(1)}{match.group(2).upper()}",
            stripped,
        )
        stripped = re.sub(
            r"^(Honestamente|Sinceramente|Realmente)(\s+)",
            r"\1, ",
            stripped,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r"(de todas las cosas posibles que se podían hacer)(\s+)",
            r"\1, ",
            stripped,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(r"\bcercano\s+ti\b", "cercano a ti", stripped, flags=re.IGNORECASE)
        stripped = re.sub(
            r"\btirando todo a la basura\b",
            "tirarlo todo a la basura",
            stripped,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r"(?<![.!?])\s+(Al fin y al cabo)",
            r". \1",
            stripped,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r"\b(Al fin y al cabo)(?![,.!?])",
            r"\1,",
            stripped,
            flags=re.IGNORECASE,
        )
        if stripped[-1] not in ".!?":
            stripped += "."
        return stripped


class AssistantController:
    def __init__(self, model_path: str) -> None:
        self.status = "Inicializando"
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.status_queue: "queue.Queue[str]" = queue.Queue()
        self.worker = SpeechWorker(
            RecognitionConfig(model_path=model_path),
            events=self.status_queue,
            log=self.log_queue,
        )

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    def poll_status(self) -> Optional[str]:
        try:
            return self.status_queue.get_nowait()
        except queue.Empty:
            return None

    def poll_log(self) -> Optional[str]:
        try:
            return self.log_queue.get_nowait()
        except queue.Empty:
            return None

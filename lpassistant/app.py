import json
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import language_tool_python
import pyperclip
import sounddevice as sd
from pynput.keyboard import Controller, Key
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
        self._listening_mode = False
        self._keyboard = Controller()
        self._tool: Optional[language_tool_python.LanguageTool] = None

    def stop(self) -> None:
        self._stop_event.set()

    def _emit_log(self, message: str) -> None:
        self.log.put(message)

    def _toggle_listen(self, state: bool) -> None:
        self._listening_mode = state
        status = "Escuchando" if state else "En espera"
        self.events.put(status)

    def _handle_command(self, text: str) -> bool:
        normalized = text.lower().strip()
        if "escuchar" in normalized and not self._listening_mode:
            self._emit_log("Activando modo escucha.")
            self._toggle_listen(True)
            return True
        if "detener" in normalized and self._listening_mode:
            self._emit_log("Deteniendo modo escucha.")
            self._toggle_listen(False)
            return True
        if not self._listening_mode:
            return False
        if "seleccionar todo" in normalized:
            self._emit_log("Ejecutando CTRL+A.")
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("a")
                self._keyboard.release("a")
            return True
        if "copiar" in normalized:
            self._emit_log("Ejecutando CTRL+C.")
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("c")
                self._keyboard.release("c")
            return True
        if "pegar" in normalized:
            self._emit_log("Ejecutando CTRL+V.")
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("v")
                self._keyboard.release("v")
            return True
        if "mejorar texto" in normalized:
            self._emit_log("Mejorando texto seleccionado con LanguageTool.")
            self._improve_selected_text()
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
            self._keyboard.press("c")
            self._keyboard.release("c")
        time.sleep(0.1)
        original_text = pyperclip.paste()
        if not original_text.strip():
            self._emit_log("No hay texto seleccionado para mejorar.")
            return
        improved = self._tool.correct(original_text)
        pyperclip.copy(improved)
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("v")
            self._keyboard.release("v")
        self._emit_log("Texto mejorado y pegado.")

    def _type_text(self, text: str) -> None:
        self._keyboard.type(text + " ")

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
            self._toggle_listen(False)
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
                    if self._handle_command(text):
                        continue
                    if self._listening_mode:
                        self._type_text(text)

    @staticmethod
    def _extract_text(result: str) -> str:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return ""
        text = payload.get("text", "")
        return text.strip()


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

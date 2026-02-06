import json
import queue
import re
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
        self._mode = "idle"
        self._keyboard = Controller()
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
        }
        self.events.put(status_map.get(mode, "En espera"))

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _handle_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if normalized == "escuchar" and self._mode != "dictation":
            self._emit_log("Activando modo dictado.")
            self._set_mode("dictation")
            return True
        if normalized == "escuchar comandos" and self._mode != "commands":
            self._emit_log("Activando modo comandos.")
            self._set_mode("commands")
            return True
        if normalized == "detener" and self._mode != "idle":
            self._emit_log("Deteniendo escucha.")
            self._set_mode("idle")
            return True
        if self._mode == "idle":
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
        if normalized == "mejorar texto":
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
                    if self._handle_command(text):
                        continue
                    if self._mode == "dictation":
                        self._type_text(text)

    @staticmethod
    def _extract_text(result: str) -> str:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return ""
        text = payload.get("text", "")
        return text.strip()

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

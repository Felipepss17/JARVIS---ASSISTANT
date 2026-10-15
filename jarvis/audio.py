"""Entrada de áudio, reconhecimento de fala e utilitários sonoros."""
import os
import re
import time
import queue
import threading
import collections
import difflib
import glob
import unicodedata

import numpy as np
import pygame
import sounddevice as sd
import speech_recognition as sr
from PySide6.QtCore import QThread, Signal

from .settings import *  # noqa: F403

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

speech_lock = threading.Lock()

# ---------------- utilitário de efeitos sonoros ----------------
if not pygame.mixer.get_init():
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
    except pygame.error as exc:
        print(f"[som] áudio indisponível na inicialização: {exc}")


def tocar_som(nome_arquivo):
    """Toca um efeito sonoro de forma independente usando canais livres do Pygame."""
    try:
        aliases = {"chat_open.wav": "chat_open.mp3", "typing_click.wav": "typing_click.flac"}
        nome_arquivo = aliases.get(nome_arquivo, nome_arquivo)
        caminho = os.path.join(PROJECT_ROOT, "assets", "sounds", nome_arquivo)
        if os.path.exists(caminho):
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2)
            som = pygame.mixer.Sound(caminho)
            # Encontra um canal livre para o som não cortar a voz ou outros cliques
            canal = pygame.mixer.find_channel(True)
            if canal:
                canal.play(som)
    except Exception as e:
        print(f"[som] Erro ao reproduzir {nome_arquivo}: {e}")


# ---------------- microfone e utilidades ----------------
def find_mic():
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and "usb audio" in d["name"].lower():
                return i
    except Exception as e:
        print(f"[mic] erro ao listar dispositivos: {e}")
    return None


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def so_pedido_de_parar(texto):
    palavras = re.findall(r"\w+", strip_accents(texto.lower()))
    return all(p in PALAVRAS_DE_PARAR for p in palavras)


def interpretar_sim_nao(texto):
    palavras = set(re.findall(r"\w+", strip_accents(texto.lower())))
    if palavras & {"nao", "negativo", "negar", "nego", "cancele", "cancelar", "pare"}:
        return False
    if palavras & {"sim", "pode", "autorizo", "autorizado", "confirmo", "claro",
                   "execute", "faca", "ok", "positivo"}:
        return True
    return None


def mentions_studio(text):
    for w in re.findall(r"\w+", strip_accents(text.lower())):
        if difflib.SequenceMatcher(None, w, "studio").ratio() >= 0.6:
            return True
    return False


def find_roblox_studio():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "Versions")
    if os.path.isdir(base):
        for folder in os.listdir(base):
            exe = os.path.join(base, folder, "RobloxStudioBeta.exe")
            if os.path.isfile(exe):
                return exe
    return None


def find_installed_app(app_name):
    app_name = app_name.lower()
    search_paths = [
        os.path.expanduser(r"~\Desktop\*.lnk"),
        os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\**\*.lnk"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\**\*.lnk"
    ]
    for path_pattern in search_paths:
        for file_path in glob.glob(path_pattern, recursive=True):
            filename = os.path.basename(file_path).lower()
            if app_name in filename:
                return file_path
    return None


# ---------------- áudio e reconhecimento ----------------
def block_rms(block):
    return float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))


def normalize(audio):
    peak = int(np.abs(audio).max())
    if peak < 50:
        return audio
    gain = min(20000 / peak, MAX_GAIN)
    return np.clip(audio.astype(np.float32) * gain, -32768, 32767).astype(np.int16)


def split_wake(text):
    words = re.findall(r"\w+", text.lower())
    for i, w in enumerate(words):
        n = 0
        if w in WAKE_VARIANTS or difflib.SequenceMatcher(None, w, WAKE_WORD).ratio() >= 0.8:
            n = 1
        elif i + 1 < len(words):
            pair = w + words[i + 1]
            if difflib.SequenceMatcher(None, pair, WAKE_WORD).ratio() >= 0.8:
                n = 2
        if n:
            return True, " ".join(words[i + n:])
    return False, text


def has_content(rest):
    return any(len(w) >= 3 for w in rest.split())


def build_stt(status_cb):
    if STT_ENGINE == "whisper":
        if WhisperModel is None:
            print("[stt] faster-whisper não instalado: usando o Google.")
        else:
            try:
                status_cb("LOADING SPEECH MODEL")
                model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

                def transcribe_whisper(audio):
                    segments, _ = model.transcribe(
                        audio.astype(np.float32) / 32768.0,
                        language="pt",
                        beam_size=3,
                        condition_on_previous_text=False,
                        initial_prompt="Jarvis, abra o Roblox Studio.",
                    )
                    parts = []
                    for s in segments:
                        if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                            continue
                        parts.append(s.text)
                    text = " ".join(parts).strip()
                    if any(h in text.lower() for h in HALLUCINATIONS):
                        return ""
                    return text

                print(f"[stt] usando Whisper local ({WHISPER_MODEL}).")
                return transcribe_whisper
            except Exception as e:
                print(f"[stt] não consegui carregar o Whisper ({e}): usando o Google.")

    recognizer = sr.Recognizer()

    def transcribe_google(audio):
        data = sr.AudioData(audio.tobytes(), SAMPLE_RATE, 2)
        try:
            return recognizer.recognize_google(data, language="pt-BR").strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print(f"[stt] erro de conexão com o Google: {e}")
            return ""

    print("[stt] usando o reconhecimento do Google (online).")
    return transcribe_google


class ListenerWorker(QThread):
    status = Signal(str)
    ready = Signal()
    wake = Signal()
    command = Signal(str)
    command_timeout = Signal()
    interrupt = Signal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.paused = threading.Event()
        self.speaking = threading.Event()
        self.speech_text = ""
        self.ignore_until = 0.0
        self.awaiting_command = False
        self.command_deadline = None
        self.noise_floor = 20.0
        self.audio_q = queue.Queue()
        self.transcribe = None

    def pause(self):
        self.paused.set()

    def resume(self, start_timer=True):
        if self.awaiting_command and start_timer:
            self.command_deadline = time.monotonic() + COMMAND_WAIT_SEC
        self.paused.clear()

    def begin_speaking(self, texto):
        self.speech_text = (self.speech_text + " " + texto).strip()
        self.speaking.set()

    def end_speaking(self):
        self.speaking.clear()
        self.speech_text = ""

    def request_command(self):
        self._start_waiting()

    def stop(self):
        self.running = False
        self.wait(3000)

    def _start_waiting(self):
        self.awaiting_command = True
        self.command_deadline = None

    def _callback(self, indata, frames, time_info, status):
        self.audio_q.put(indata[:, 0].copy())

    def run(self):
        self.transcribe = build_stt(self.status.emit)
        for attempt in range(1, 11):
            if not self.running:
                return
            try:
                device = find_mic()
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                    blocksize=BLOCK, device=device,
                                    callback=self._callback):
                    self._calibrate()
                    self.ready.emit()
                    self._loop()
                return
            except Exception as e:
                print(f"[mic] ERRO ao abrir o microfone: {e}")
                time.sleep(5)

    def _calibrate(self):
        levels = []
        t0 = time.monotonic()
        while len(levels) < CALIBRATION_BLOCKS and time.monotonic() - t0 < 4:
            try:
                levels.append(block_rms(self.audio_q.get(timeout=0.5)))
            except queue.Empty:
                continue
        if levels:
            self.noise_floor = float(np.percentile(levels, 30))

    def _loop(self):
        pre = collections.deque(maxlen=PREROLL_BLOCKS)
        buf = []
        in_speech = False
        loud = 0
        silence = 0
        eco = None

        while self.running:
            try:
                block = self.audio_q.get(timeout=0.2)
            except queue.Empty:
                continue

            if self.paused.is_set() or time.monotonic() < self.ignore_until:
                pre.clear()
                buf = []
                in_speech = False
                loud = 0
                silence = 0
                eco = None
                continue

            speaking = self.speaking.is_set()

            if (self.awaiting_command and not speaking and not in_speech
                    and self.command_deadline is not None
                    and time.monotonic() > self.command_deadline):
                self.awaiting_command = False
                self.command_deadline = None
                self.command_timeout.emit()

            rms = block_rms(block)
            boost = BARGE_IN_BOOST if speaking else 1.0
            start_thr = max(self.noise_floor * START_FACTOR, MIN_START_RMS) * boost
            end_thr = max(self.noise_floor * END_FACTOR, MIN_START_RMS * 0.6)
            max_phrase = BARGE_MAX_PHRASE_SEC if speaking else MAX_PHRASE_SEC

            if not in_speech:
                pre.append(block)
                if rms > start_thr:
                    loud += 1
                else:
                    loud = 0
                    if not speaking:
                        self.noise_floor = 0.98 * self.noise_floor + 0.02 * rms
                if loud >= 2:
                    in_speech = True
                    buf = list(pre)
                    silence = 0
                    eco = self.speech_text if speaking else None
            else:
                buf.append(block)
                if speaking and eco is None:
                    eco = self.speech_text
                silence = silence + 1 if rms < end_thr else 0
                dur = len(buf) * BLOCK / SAMPLE_RATE
                if silence >= SILENCE_BLOCKS or dur >= max_phrase:
                    try:
                        self._finish(buf, silence, eco)
                    except Exception as e:
                        print(f"[mic] erro ao processar a fala: {e}")
                    buf = []
                    in_speech = False
                    loud = 0
                    silence = 0
                    eco = None
                    pre.clear()

    def _finish(self, buf, silence, eco=None):
        audio = np.concatenate(buf)
        trim = max(0, silence - 8) * BLOCK
        if trim:
            audio = audio[:-trim]
        dur = len(audio) / SAMPLE_RATE
        if dur < MIN_TOTAL_SEC:
            return
        self.status.emit("PROCESSING")
        text = self.transcribe(normalize(audio))
        self._dispatch(text, eco)

    def _emit_command(self, command):
        self._start_waiting()
        self.command.emit(command)

    def _interromper(self, rest):
        self.speaking.clear()
        self.speech_text = ""
        self.ignore_until = time.monotonic() + 0.4
        self.awaiting_command = True
        pedido = rest if (has_content(rest) and not so_pedido_de_parar(rest)) else ""
        self.command_deadline = None if pedido else time.monotonic() + COMMAND_WAIT_SEC
        self.interrupt.emit(pedido)

    def _dispatch(self, text, eco=None):
        if not text:
            return
        found, rest = split_wake(text)

        if eco is not None:
            if not found:
                return
            if WAKE_WORD in eco.lower():
                return
            if self.speaking.is_set():
                self._interromper(rest)
                return

        if self.awaiting_command:
            command = rest if found else text
            if not command.strip():
                self.command_deadline = time.monotonic() + COMMAND_WAIT_SEC
                return
            if not has_content(command):
                return
            self._emit_command(command)
            return

        if not found:
            return
        if has_content(rest):
            self._emit_command(rest)
        else:
            self._start_waiting()
            self.wake.emit()


\n
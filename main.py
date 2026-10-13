import sys
import os

# Sem terminal (inicialização do Windows), a saída vai para um arquivo de log
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis.log"),
                "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log
    if sys.stderr is None:
        sys.stderr = _log

import re
import json
import pygame
import html
import time
import queue
import difflib
import tempfile
import threading
import subprocess
import webbrowser
import glob
import collections
import unicodedata

import numpy as np
import sounddevice as sd
import speech_recognition as sr
import pyttsx3
import keyboard
from dotenv import load_dotenv
from groq import Groq

import acoes
import ferramentas

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal, QPoint, QLockFile
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QAction, QTextCursor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QStyle,
    QVBoxLayout, QTextEdit, QLineEdit, QPushButton, QHBoxLayout, QLabel
)

load_dotenv()

# ---------------- configurações gerais ----------------
SAMPLE_RATE = 16000
SPEECH_RATE = 175
AI_MODEL = "openai/gpt-oss-20b"
AI_MAX_TOKENS_VOZ = 400          # respostas faladas: curtas
AI_MAX_TOKENS_AGENTE = 3000      # chat de texto: espaço para escrever código
MAX_HISTORY = 16
MAX_TOOL_STEPS = 14              # importar um projeto usa várias ferramentas seguidas
CONFIRM_TIMEOUT = 120            # segundos esperando sua autorização (depois disso, nega)
FALAR_RESPOSTAS_DO_CHAT = False  # True = também fala respostas curtas do chat
DEBUG = True

# ---------------- animação de escrita e interrupção por voz ----------------
DIGITACAO_CPS = 90               # velocidade da "escrita" (caracteres por segundo)
DIGITACAO_MAX_SEG = 6            # respostas longas aceleram para não passar disso
DIGITACAO_INTERVALO_MS = 20
BARGE_IN = True                  # interromper o JARVIS dizendo "Jarvis" enquanto ele fala
BARGE_IN_BOOST = 1.6             # quanto maior, mais forte você precisa falar para interromper
BARGE_MAX_PHRASE_SEC = 4         # enquanto ele fala, a escuta analisa trechos curtos

# ---------------- configurações da escuta ----------------
STT_ENGINE = "whisper"
WHISPER_MODEL = "small"

BLOCK = 480
START_FACTOR = 3.0
END_FACTOR = 1.8
MIN_START_RMS = 60
SILENCE_SEC = 1.3
MAX_PHRASE_SEC = 10
MIN_TOTAL_SEC = 0.6
PREROLL_BLOCKS = 10
CALIBRATION_BLOCKS = 40
COMMAND_WAIT_SEC = 8
RESUME_DELAY_MS = 500
MAX_GAIN = 30

SILENCE_BLOCKS = int(SILENCE_SEC * SAMPLE_RATE / BLOCK)

SYSTEM_PROMPT_VOZ = (
    "Você é o J.A.R.V.I.S., assistente pessoal do senhor Felipe, um jovem que usa Windows e cria "
    "jogos no Roblox Studio. Responda sempre em português do Brasil, com tom educado, elegante e "
    "levemente espirituoso, chamando-o de 'senhor' de vez em quando. "
    "Suas respostas serão FALADAS em voz alta: no máximo 3 frases, sem markdown, listas, emojis "
    "ou código. "
    "Por voz você não executa ações no computador: abrir programas, sites, volume e afins são "
    "comandos locais do sistema. Para tarefas de programação ou de criar e editar arquivos, diga "
    "ao senhor para abrir o chat de texto (basta dizer 'abrir chat'). "
    "Se não souber algo, diga com honestidade."
)

SYSTEM_PROMPT_AGENTE = (
    "Você é o J.A.R.V.I.S., assistente pessoal do senhor Felipe e agente de programação no chat de "
    "texto. Responda em português do Brasil, com tom educado, elegante e direto, chamando-o de 'senhor'. "
    "Você tem ferramentas reais. Regras aplicadas pelo próprio sistema, que independem de você: "
    "você só escreve e apaga dentro da pasta jarvis_workspace; pode LER (nunca alterar) os arquivos "
    "main.py, acoes.py, ferramentas.py, requirements.txt, README.md, jarvis.log e os plugins; "
    "executar código, apagar, sobrescrever, instalar pacotes e criar ou remover plugins exigem a "
    "autorização do senhor, que o sistema pede por você: basta chamar a ferramenta, sem perguntar antes. "
    "Para dar uma nova habilidade ao JARVIS por voz, crie um plugin com criar_plugin: um arquivo "
    "Python com 'def handle(texto):' que recebe o comando em minúsculas e devolve a frase que o JARVIS "
    "deve falar, ou None se o comando não for dele. O plugin vale imediatamente. "
    "Para mudar o main.py, leia o arquivo, explique a alteração e entregue o trecho pronto para o "
    "senhor colar, pois você não pode editá-lo. "
    "PROJETOS DO GITHUB: quando o senhor enviar um link do GitHub, o pedido é transformar o projeto "
    "numa habilidade. Siga estes passos: (1) chame baixar_projeto_github; (2) leia o README e os "
    "arquivos Python principais com ler_ficheiro (caminho 'importados/<pasta>/<arquivo>'); (3) conte ao "
    "senhor, em poucas frases, o que o projeto faz, quais dependências ele precisa e o que o relatório "
    "de segurança encontrou, destacando qualquer coisa estranha (rede, subprocess, leitura de .env, "
    "código ofuscado, executáveis); se algo parecer malicioso, recomende não usar e não prossiga; "
    "(4) instale as dependências necessárias UMA por vez com instalar_pacote, só as realmente "
    "usadas, e nunca instale nada que o projeto não precise; "
    "(5) crie o plugin com criar_plugin. No plugin, use 'import sys, os' e insira o caminho do projeto "
    "em sys.path com um texto literal, por exemplo "
    "PASTA = os.path.join(os.path.dirname(__file__), '..', 'jarvis_workspace', 'importados', '<pasta>'), "
    "e escreva o nome exato da pasta no código; o plugin deve chamar só as funções do projeto "
    "que forem necessárias, com tratamento de erro; (6) explique como usar por voz. "
    "Seja honesto sobre os limites: só projetos Python com funções ou classes chamáveis viram plugin; "
    "aplicativos com interface própria, bots, projetos em outras linguagens ou que exijam chaves de API "
    "e dependências gigantes (como PyTorch) não se encaixam, então explique o motivo em vez de forçar. "
    "Nunca afirme ter feito algo sem o resultado de uma ferramenta confirmar. Se uma ferramenta "
    "falhar, leia o erro e tente corrigir. Se o senhor negar uma autorização, aceite e não insista. "
    "Seja objetivo, sem formatação excessiva."
)

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "roblox": "https://www.roblox.com",
}
PROGRAMS = {
    "bloco de notas": "notepad.exe",
    "calculadora": "calc.exe",
}

WAKE_WORD = "jarvis"
WAKE_VARIANTS = {
    "jarvis", "jarves", "jarvi", "jarvez", "jarbis", "jarbas",
    "garvis", "charvis", "jarvys", "javis", "jarvisse",
}
HALLUCINATIONS = ("amara.org", "legendas pela comunidade", "obrigado por assistir", "inscreva-se")
PALAVRAS_DE_PARAR = {"para", "pare", "parar", "chega", "silencio", "calma", "espera",
                     "espere", "ok", "senhor", "jarvis"}

speech_lock = threading.Lock()


# ---------------- utilitário de efeitos sonoros ----------------
if not pygame.mixer.get_init():
    pygame.mixer.init(frequency=44100, size=-16, channels=2)
def tocar_som(nome_arquivo):
    """Toca um efeito sonoro de forma independente usando canais livres do Pygame."""
    try:
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds", nome_arquivo)
        if os.path.exists(caminho):
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


class AIWorker(QThread):
    answer = Signal(str)
    failed = Signal(str)
    confirm_needed = Signal(str)
    confirm_closed = Signal()

    def __init__(self, history, agente):
        super().__init__()
        self.history = list(history)
        self.agente = agente
        self._evento = threading.Event()
        self._decisao = False

    def decide(self, ok):
        self._decisao = bool(ok)
        self._evento.set()

    def pedir_autorizacao(self, descricao):
        self._evento.clear()
        self._decisao = False
        self.confirm_needed.emit(descricao)
        if not self._evento.wait(CONFIRM_TIMEOUT):
            self.confirm_closed.emit()
        return self._decisao

    def run(self):
        try:
            client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
            sistema = SYSTEM_PROMPT_AGENTE if self.agente else SYSTEM_PROMPT_VOZ
            messages = [{"role": "system", "content": sistema}] + self.history
            max_tokens = AI_MAX_TOKENS_AGENTE if self.agente else AI_MAX_TOKENS_VOZ
            kwargs = dict(model=AI_MODEL, max_tokens=max_tokens)
            if self.agente:
                kwargs["tools"] = ferramentas.ESQUEMA
                kwargs["tool_choice"] = "auto"

            for _ in range(MAX_TOOL_STEPS if self.agente else 1):
                resp = client.chat.completions.create(messages=messages, **kwargs)
                msg = resp.choices[0].message
                chamadas = msg.tool_calls if self.agente else None

                if not chamadas:
                    texto = (msg.content or "").strip()
                    self.answer.emit(texto or "Desculpe, senhor, não consegui formular uma resposta.")
                    return

                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [{
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.function.name,
                                     "arguments": tc.function.arguments or "{}"},
                    } for tc in chamadas],
                })
                for tc in chamadas:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    resultado = ferramentas.executar(tc.function.name, args, self.pedir_autorizacao)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})

            kwargs["tool_choice"] = "none"
            resp = client.chat.completions.create(messages=messages, **kwargs)
            texto = (resp.choices[0].message.content or "").strip()
            self.answer.emit(texto or "Cheguei ao limite de passos, senhor. Peça para eu continuar.")
        except Exception as e:
            print(f"[ia] erro: {e}")
            if self.agente:
                self.failed.emit(f"Não consegui concluir, senhor. Detalhe técnico: {str(e)[:250]}")
            else:
                self.failed.emit("Não consegui falar com a inteligência artificial agora, senhor.")


class ActionWorker(QThread):
    done = Signal(str, str, str)

    def __init__(self, text, source="voz"):
        super().__init__()
        self.text = text
        self.source = source

    def run(self):
        reply = None
        try:
            texto = self.text.lower()
            if self.source == "chat" and ("github.com" in texto or len(self.text.split()) > 8):
                pass
            else:
                reply = acoes.try_handle(self.text) or ferramentas.rodar_plugins(texto)
        except Exception as e:
            print(f"[acoes] erro: {e}")
            reply = "Tive um problema ao executar isso, senhor."
        self.done.emit(self.text, reply or "", self.source)


class SpeakWorker(QThread):
    finished_speaking = Signal(object)

    def __init__(self, text, callback=None):
        super().__init__()
        self.text = text
        self.callback = callback
        self._parar = threading.Event()

    def parar(self):
        self._parar.set()

    def _falar_windows(self):
        engine = pyttsx3.init()
        engine.setProperty("rate", SPEECH_RATE)
        for v in engine.getProperty("voices"):
            name = v.name.lower()
            if "portugu" in name or "brazil" in name or "brasil" in name or "maria" in name:
                engine.setProperty("voice", v.id)
                break

        def ao_falar_palavra(name, location, length):
            if self._parar.is_set():
                engine.stop()

        engine.connect("started-word", ao_falar_palavra)
        engine.say(self.text)
        engine.runAndWait()
        engine.stop()

    def run(self):
        with speech_lock:
            if not self._parar.is_set():
                arquivo_temporario = None
                try:
                    from gtts import gTTS
                    import pygame

                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as arquivo:
                        arquivo_temporario = arquivo.name

                    gTTS(text=self.text, lang="pt-br", slow=False).save(arquivo_temporario)

                    if not self._parar.is_set():
                        if not pygame.mixer.get_init():
                            pygame.mixer.init()
                        pygame.mixer.music.load(arquivo_temporario)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            if self._parar.is_set():
                                pygame.mixer.music.stop()
                                break
                            time.sleep(0.03)
                        pygame.mixer.music.unload()
                except Exception:
                    if not self._parar.is_set():
                        try:
                            self._falar_windows()
                        except Exception as e:
                            print(f"[voz] erro: {e}")
                finally:
                    if arquivo_temporario and os.path.exists(arquivo_temporario):
                        try:
                            os.remove(arquivo_temporario)
                        except OSError:
                            pass
        self.finished_speaking.emit(self)


class ChatWindow(QWidget):
    message_submitted = Signal(str)
    decided = Signal(bool)
    closed = Signal()

    PLACEHOLDER = "Escreva uma ordem ou mensagem ao JARVIS..."
    PLACEHOLDER_ESCREVENDO = "JARVIS está respondendo..."

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. // Terminal de Comunicação")
        self.resize(680, 760)
        self.setStyleSheet("""
            QWidget { background-color: #050b14; color: #2accff; font-family: 'Consolas'; }
            QTextEdit {
                background-color: #081220; border: 1px solid #1a5276; border-radius: 8px;
                padding: 15px; color: #9af2ff; font-size: 15px;
            }
            QLineEdit {
                background-color: #081220; border: 1px solid #2accff; border-radius: 6px;
                padding: 10px; color: #ffffff; font-size: 15px;
            }
            QLineEdit:disabled { border-color: #1a5276; color: #4b7387; }
            QPushButton {
                background-color: #0b2545; border: 1px solid #2accff; border-radius: 6px;
                color: #2accff; font-weight: bold; padding: 10px 20px; font-size: 15px;
            }
            QPushButton:hover { background-color: #133a6f; color: #ffffff; }
            QPushButton:disabled { border-color: #1a5276; color: #4b7387; }
            QPushButton#yes { border-color: #3ddc84; color: #3ddc84; }
            QPushButton#no { border-color: #ff5c5c; color: #ff5c5c; }
        """)

        layout = QVBoxLayout()
        header_label = QLabel("--- MODO AGENTE: ferramentas ativas, ações sensíveis pedem autorização ---")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header_label)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history)

        self.confirm_bar = QWidget()
        bar = QHBoxLayout(self.confirm_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.btn_yes = QPushButton("Autorizar")
        self.btn_yes.setObjectName("yes")
        self.btn_no = QPushButton("Negar")
        self.btn_no.setObjectName("no")
        self.btn_yes.clicked.connect(lambda: self.decided.emit(True))
        self.btn_no.clicked.connect(lambda: self.decided.emit(False))
        bar.addWidget(self.btn_yes)
        bar.addWidget(self.btn_no)
        self.confirm_bar.hide()
        layout.addWidget(self.confirm_bar)

        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(self.PLACEHOLDER)
        self.input_field.returnPressed.connect(self.send_message)
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)

        self.setLayout(layout)

        self._fila = collections.deque()
        self._digit = None
        self._instantaneo = False
        self._timer = QTimer(self)
        self._timer.setInterval(DIGITACAO_INTERVALO_MS)
        self._timer.timeout.connect(self._passo_digitacao)

        self.append_message("JARVIS", "Terminal aberto, senhor. Posso ler o projeto, criar arquivos "
                                      "na pasta jarvis_workspace e criar plugins. Ações sensíveis "
                                      "pedirão a sua autorização.")

    def send_message(self):
        if not self.input_field.isEnabled():
            return
        text = self.input_field.text().strip()
        if text:
            tocar_som("send_message.wav") # <--- Som ao enviar mensagem
            self.append_message("Felipe", text)
            self.input_field.clear()
            self.message_submitted.emit(text)

    def _travar(self, travar):
        self.input_field.setEnabled(not travar)
        self.send_button.setEnabled(not travar)
        self.input_field.setPlaceholderText(self.PLACEHOLDER_ESCREVENDO if travar else self.PLACEHOLDER)
        if not travar:
            self.input_field.setFocus()

    def append_message(self, sender, message, animar=None):
        if animar is None:
            animar = (sender == "JARVIS")
        self._fila.append(("anim" if animar else "inst", sender, str(message)))
        self._processar_fila()

    def _processar_fila(self):
        if self._digit is not None:
            return
        while self._fila:
            tipo, sender, msg = self._fila.popleft()
            if tipo == "barra":
                self._mostrar_barra()
            elif tipo == "anim" and not self._instantaneo:
                self._iniciar_digitacao(sender, msg)
                self._travar(True)
                return
            else:
                self._inserir_instantaneo(sender, msg)
        self._travar(False)

    def _inserir_instantaneo(self, sender, message):
        color = "#ffffff" if sender.startswith("Felipe") else "#2accff"
        corpo = html.escape(message).replace("\n", "<br>").replace("  ", "&nbsp;&nbsp;")
        self.chat_history.append(
            f"<div style='margin-bottom: 12px;'><b style='color:{color};'>{html.escape(sender)}:</b>"
            f"<br>{corpo}</div>")

    def _iniciar_digitacao(self, sender, message):
        self.chat_history.append(f"<b style='color:#2accff;'>{html.escape(sender)}:</b>")
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        self.chat_history.setTextCursor(cursor)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#9af2ff"))
        cps = max(DIGITACAO_CPS, len(message) / DIGITACAO_MAX_SEG)
        passo = max(1, round(cps * DIGITACAO_INTERVALO_MS / 1000))
        self._digit = {"texto": message, "pos": 0, "passo": passo, "fmt": fmt}
        self._timer.start()

    def _escrever(self, trecho):
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(trecho, self._digit["fmt"])
        self.chat_history.setTextCursor(cursor)
        self.chat_history.ensureCursorVisible()

    def _passo_digitacao(self):
        d = self._digit
        if d is None:
            self._timer.stop()
            return
        trecho = d["texto"][d["pos"]:d["pos"] + d["passo"]]
        d["pos"] += d["passo"]
        if trecho:
            tocar_som("typing_click.wav") # <--- Som enquanto ele digita (a cada passo)
            self._escrever(trecho)
        if d["pos"] >= len(d["texto"]):
            self._finalizar_digitacao()

    def _finalizar_digitacao(self):
        self._timer.stop()
        self._digit = None
        self.chat_history.append("")
        self._processar_fila()

    def pular_digitacao(self):
        self._instantaneo = True
        try:
            d = self._digit
            if d is not None:
                resto = d["texto"][d["pos"]:]
                if resto:
                    self._escrever(resto)
                self._timer.stop()
                self._digit = None
                self.chat_history.append("")
            self._processar_fila()
        finally:
            self._instantaneo = False

    def ask_confirmation(self, descricao):
        self.append_message("⚠ AUTORIZAÇÃO NECESSÁRIA", descricao +
                            "\n\nClique em Autorizar ou Negar (ou digite sim / não).", animar=False)
        self._fila.append(("barra", "", ""))
        self._processar_fila()

    def _mostrar_barra(self):
        self.confirm_bar.show()
        self.raise_()
        self.activateWindow()

    def close_confirmation(self, mensagem):
        self.confirm_bar.hide()
        self._fila = collections.deque(i for i in self._fila if i[0] != "barra")
        self.append_message("JARVIS", mensagem, animar=False)

    def closeEvent(self, event):
        self._timer.stop()
        self.closed.emit()
        event.accept()


class FloatingReactor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(200, 200)

        screen = QApplication.primaryScreen().geometry()
        self.move(30, screen.height() - 240)

        self.phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(30)

        self.dragging = False
        self.offset = QPoint()

    def animate(self):
        self.phase = (self.phase + 1) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(w, h) * 0.38

        for i in range(6, 0, -1):
            alpha = int(4 + i * 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 170, 255, alpha))
            r = radius * (0.5 + i * 0.08)
            p.drawEllipse(int(cx-r), int(cy-r), int(2*r), int(2*r))

        for ring, mult, width in [(0.75, 1, 2), (0.92, -1, 2), (1.1, 1, 1)]:
            r = radius * ring
            p.save()
            p.translate(cx, cy)
            p.rotate(self.phase * mult)
            pen = QPen(QColor(42, 204, 255, 210), width)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(int(-r), int(-r), int(2*r), int(2*r), 20 * 16, 105 * 16)
            p.drawArc(int(-r), int(-r), int(2*r), int(2*r), 170 * 16, 65 * 16)
            p.drawArc(int(-r), int(-r), int(2*r), int(2*r), 270 * 16, 45 * 16)
            p.restore()

        p.setPen(QPen(QColor(107, 231, 255), 2))
        p.setBrush(QColor(3, 44, 72, 230))
        cr = radius * 0.5
        p.drawEllipse(int(cx-cr), int(cy-cr), int(2*cr), int(2*cr))
        p.setPen(QColor(154, 242, 255))
        p.setFont(QFont("Consolas", max(9, int(radius * 0.13)), QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False


class JarvisController(QObject):
    hotkey_pressed = Signal()

    def __init__(self):
        super().__init__()
        self.listener = None
        self.ai_worker = None
        self.ai_busy = False
        self.ai_origin = "voz"
        self.confirm_worker = None
        self.action_worker = None
        self.action_busy = False
        self.speakers = []
        self.pending_speech = 0
        self.history = []
        self.reactor_pinned = False
        self.has_key = bool(os.environ.get("GROQ_API_KEY"))

        self.reactor_window = FloatingReactor()
        self.reactor_window.hide()
        self.chat_window = None

        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray_menu = QMenu()
        self.toggle_action = QAction("Mostrar/Ocultar Reator", self.tray_menu)
        self.toggle_action.triggered.connect(self.toggle_reactor_visibility)
        self.open_chat_action = QAction("Abrir Chat de Texto", self.tray_menu)
        self.open_chat_action.triggered.connect(self.open_chat_ui)
        self.quit_action = QAction("Sair do JARVIS", self.tray_menu)
        self.quit_action.triggered.connect(QApplication.quit)
        self.tray_menu.addAction(self.toggle_action)
        self.tray_menu.addAction(self.open_chat_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.quit_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

        self.hotkey_pressed.connect(self.trigger_hotkey_action)
        try:
            keyboard.add_hotkey("ctrl+space", lambda: self.hotkey_pressed.emit())
        except Exception as e:
            print(f"[atalho] não consegui registrar Ctrl+Espaço: {e}")

        self.start_listener()

    def open_chat_ui(self):
        if not self.chat_window:
            self.chat_window = ChatWindow()
            self.chat_window.message_submitted.connect(self.handle_chat_input)
            self.chat_window.decided.connect(self.resolve_confirmation)
            self.chat_window.closed.connect(self.on_chat_closed)
        tocar_som("chat_open.wav") # <--- Som ao abrir o chat
        self.chat_window.show()
        self.chat_window.raise_()
        self.chat_window.activateWindow()

    def on_chat_closed(self):
        self.chat_window = None
        if self.confirm_worker is not None:
            w = self.confirm_worker
            self.confirm_worker = None
            w.decide(False)

    def chat_log(self, sender, text):
        if self.chat_window:
            self.chat_window.append_message(sender, text)

    def handle_chat_input(self, text):
        lower = text.lower().strip()

        if self.confirm_worker is not None:
            decisao = interpretar_sim_nao(lower)
            if decisao is None:
                self.chat_log("JARVIS", "Aguardo a sua resposta, senhor: sim ou não (ou use os botões).")
            else:
                self.resolve_confirmation(decisao)
            return

        if any(f in lower for f in ("fechar jarvis", "encerrar jarvis", "desligar jarvis")):
            self.chat_log("JARVIS", "Desligando sistemas. Até logo, senhor.")
            QTimer.singleShot(1500, QApplication.quit)
            return

        if self.ai_busy or self.action_busy:
            self.chat_log("JARVIS", "Ainda estou processando o pedido anterior, senhor.")
            return

        # Regista a mensagem do utilizador no histórico de chat
        self.history.append({"role": "user", "content": text})
        self.history = self.history[-MAX_HISTORY:]

        # Se for um comando simples de ação (como abrir o YouTube, pastas, etc.), tenta executar
        if any(w in lower for w in ["abra", "abrir", "abre", "pasta"]) and "http" not in lower:
            self.action_busy = True
            self.action_worker = ActionWorker(text, "chat")
            self.action_worker.done.connect(self.on_action_done)
            self.action_worker.start()
        else:
            # Caso contrário, envia para a IA mantendo o contexto da conversa anterior
            self.ai_origin = "chat"
            self.ai_busy = True
            self.ai_worker = AIWorker(self.history, agente=True)
            self.ai_worker.answer.connect(self.on_ai_answer)
            self.ai_worker.failed.connect(self.on_ai_failed)
            self.ai_worker.confirm_needed.connect(self.on_confirm_needed)
            self.ai_worker.confirm_closed.connect(self.on_confirm_closed)
            self.ai_worker.start()

    def on_ai_answer(self, text):
        self.ai_busy = False
        self.history.append({"role": "assistant", "content": text}) # <--- Guarda a resposta no histórico
        if self.ai_origin == "chat":
            self.chat_log("JARVIS", text)
            if FALAR_RESPOSTAS_DO_CHAT and len(text) <= 300:
                self.speak(text)
        else:
            self.say(text)

    def on_confirm_needed(self, descricao):
        self.confirm_worker = self.ai_worker
        if not self.chat_window:
            self.open_chat_ui()
        self.chat_window.ask_confirmation(descricao)

    def resolve_confirmation(self, ok):
        w = self.confirm_worker
        self.confirm_worker = None
        if self.chat_window:
            self.chat_window.close_confirmation("Autorizado." if ok else "Negado.")
        if w:
            w.decide(ok)

    def on_confirm_closed(self):
        self.confirm_worker = None
        if self.chat_window:
            self.chat_window.close_confirmation("Tempo esgotado: ação negada.")

    def start_listener(self):
        self.listener = ListenerWorker()
        self.listener.status.connect(self.on_listener_status)
        self.listener.ready.connect(self.on_listener_ready)
        self.listener.wake.connect(self.on_wake)
        self.listener.command.connect(self.on_command)
        self.listener.command_timeout.connect(self.on_command_timeout)
        self.listener.interrupt.connect(self.on_interrupt)
        self.listener.start()

    def on_listener_status(self, text):
        print(f"[jarvis] {text}")

    def on_listener_ready(self):
        self.say("Sistemas online. Às suas ordens, senhor.")

    def on_wake(self):
        self.say("Olá, senhor.")

    def on_command(self, text):
        self.handle_text(text)

    def on_command_timeout(self):
        QTimer.singleShot(1000, self.check_hide_reactor)

    def on_interrupt(self, pedido):
        self.stop_speaking()
        if self.chat_window:
            self.chat_window.pular_digitacao()
        if pedido:
            self.handle_text(pedido)

    def trigger_hotkey_action(self):
        self.stop_speaking()
        if self.chat_window:
            self.chat_window.pular_digitacao()
        self.listener.request_command()
        self.say("Sim, senhor?")

    def toggle_reactor_visibility(self):
        if self.reactor_window.isVisible():
            self.reactor_pinned = False
            tocar_som("reactor_off.wav") # <--- Som ao fechar manualmente
            self.reactor_window.hide()
        else:
            self.reactor_pinned = True
            self.reactor_window.show()

    def is_busy(self):
        return (self.pending_speech > 0 or self.ai_busy or self.action_busy
                or (self.listener is not None and self.listener.awaiting_command))

    def check_hide_reactor(self):
        if not self.reactor_pinned and not self.is_busy():
            if self.reactor_window.isVisible():
                tocar_som("reactor_off.wav") # <--- Som quando o reator some automaticamente
            self.reactor_window.hide()

    def speak(self, text, callback=None):
        self.reactor_window.show()
        self.pending_speech += 1
        if self.listener:
            if BARGE_IN:
                self.listener.begin_speaking(text)
            else:
                self.listener.pause()
        self.speakers = [w for w in self.speakers if w.isRunning()]
        w = SpeakWorker(text, callback)
        w.finished_speaking.connect(self.on_speech_done)
        self.speakers.append(w)
        w.start()

    def say(self, text, callback=None):
        self.chat_log("JARVIS", text)
        self.speak(text, callback)

    def stop_speaking(self):
        for w in list(self.speakers):
            w.parar()

    def on_speech_done(self, worker):
        self.pending_speech = max(0, self.pending_speech - 1)
        if self.pending_speech == 0:
            QTimer.singleShot(RESUME_DELAY_MS, self.resume_if_idle)
            QTimer.singleShot(3000, self.check_hide_reactor)
        if worker.callback:
            worker.callback()

    def resume_if_idle(self):
        if self.pending_speech == 0 and self.listener:
            self.listener.end_speaking()
            self.listener.resume(start_timer=not self.ai_busy)

    def handle_text(self, text):
        print(f"[comando] {text}")
        self.reactor_window.show()
        self.chat_log("Felipe (voz)", text)
        lower = text.lower()

        if any(w in lower for w in ["desligar", "desligue", "encerrar sistema", "fechar jarvis"]):
            self.say("Desligando sistemas. Até logo, senhor.", QApplication.quit)
            return

        if re.search(r"\b(abr\w+|ativ\w+)\b.*\bchat\b", lower):
            self.speak("Abrindo terminal de chat, senhor.")
            QTimer.singleShot(1000, self.open_chat_ui)
            return

        if self.action_busy:
            return
        self.action_busy = True
        self.action_worker = ActionWorker(text, "voz")
        self.action_worker.done.connect(self.on_action_done)
        self.action_worker.start()

    def parece_abrir(self, lower, source):
        if "github.com" in lower:
            return False
        if not re.search(r"\b(abra|abrir|abre|pasta)\b", lower):
            return False
        if source == "chat":
            return len(lower.split()) <= 5 and re.match(r"^(abra|abrir|abre)\b", lower) is not None
        return True

    def on_action_done(self, text, reply, source):
        self.action_busy = False
        lower = text.lower()
        if reply:
            self.say(reply)
        elif self.parece_abrir(lower, source):
            self.execute_command(lower)
        else:
            self.ask_ai(text, origem=source)

        if source == "voz" and self.pending_speech == 0 and not self.ai_busy and self.listener:
            self.listener.resume()

    def execute_command(self, text):
        clean_text = text.lower()
        for noise in ["sistemas online", "às suas ordens, senhor", "às suas ordens", "senhor"]:
            clean_text = clean_text.replace(noise, "")
        clean_text = clean_text.strip()

        prefixes = [
            "abra o site do ", "abra o site ", "abra a página do ", "abra a página ",
            "abra o ", "abra a ", "abra ",
            "abrir o ", "abrir a ", "abrir ",
            "abre o ", "abre a ", "abre ",
            "pesquise sobre o ", "pesquise sobre a ", "pesquise sobre ", "pesquise ",
            "procure o ", "procure a ", "procure "
        ]

        for prefix in prefixes:
            if clean_text.startswith(prefix):
                clean_text = clean_text[len(prefix):].strip()
                break

        if not clean_text:
            self.ask_ai(text)
            return

        if "pasta" in text.lower() or "diretório" in text.lower():
            if "downloads" in clean_text:
                target_folder = os.path.expanduser(r"~\Downloads")
            elif "documentos" in clean_text:
                target_folder = os.path.expanduser(r"~\Documents")
            else:
                possible_path = os.path.join(os.path.expanduser(r"~\Documents"), clean_text.title())
                if os.path.isdir(possible_path):
                    target_folder = possible_path
                else:
                    target_folder = os.path.expanduser(r"~\Documents")

            os.startfile(target_folder)
            self.say("Abrindo a pasta, senhor.")
            return

        if "roblox" in clean_text and mentions_studio(clean_text):
            exe = find_roblox_studio()
            if exe:
                subprocess.Popen([exe])
                self.say("Abrindo o Roblox Studio, senhor.")
            else:
                self.say("Não encontrei o Roblox Studio na pasta padrão.")
            return

        for name, url in SITES.items():
            if name in clean_text:
                webbrowser.open(url)
                self.say(f"Abrindo o site do {name}, senhor.")
                return

        for name, exe in PROGRAMS.items():
            if name in clean_text:
                try:
                    subprocess.Popen([exe])
                    self.say(f"Abrindo {name}, senhor.")
                except Exception:
                    self.say(f"Erro ao abrir {name}.")
                return

        app_lnk = find_installed_app(clean_text)
        if app_lnk:
            try:
                os.startfile(app_lnk)
                self.say(f"Abrindo {clean_text}, senhor.")
                return
            except Exception:
                pass

        self.say(f"Não encontrei {clean_text} no computador, senhor.")

    def ask_ai(self, text, origem="voz"):
        if not self.has_key:
            self.say("A IA ainda não está conectada. Falta a chave no arquivo .env.")
            return
        if self.ai_busy:
            return

        self.history.append({"role": "user", "content": text})
        self.history = self.history[-MAX_HISTORY:]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)

        self.ai_origin = origem
        self.ai_busy = True
        self.ai_worker = AIWorker(self.history, agente=(origem == "chat"))
        self.ai_worker.answer.connect(self.on_ai_answer)
        self.ai_worker.failed.connect(self.on_ai_failed)
        self.ai_worker.confirm_needed.connect(self.on_confirm_needed)
        self.ai_worker.confirm_closed.connect(self.on_confirm_closed)
        self.ai_worker.start()

    def on_ai_answer(self, text):
        self.ai_busy = False
        self.history.append({"role": "assistant", "content": text})
        if self.ai_origin == "chat":
            self.chat_log("JARVIS", text)
            if FALAR_RESPOSTAS_DO_CHAT and len(text) <= 300:
                self.speak(text)
        else:
            self.say(text)

    def on_ai_failed(self, error):
        self.ai_busy = False
        self.confirm_worker = None
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()
        if self.ai_origin == "chat":
            self.chat_log("JARVIS", error)
        else:
            self.say(error)

    def shutdown(self):
        self.stop_speaking()
        if self.confirm_worker is not None:
            self.confirm_worker.decide(False)
            self.confirm_worker = None
        if self.listener:
            self.listener.stop()
        try:
            keyboard.unhook_all()
        except Exception:
            pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(os.path.join(tempfile.gettempdir(), "jarvis.lock"))
    if not lock.tryLock(100):
        print("JARVIS já está em execução.")
        sys.exit(0)

    try:
        print(ferramentas.backup_codigo(None))
    except Exception as e:
        print(f"[backup] falhou: {e}")

    controller = JarvisController()
    app.aboutToQuit.connect(controller.shutdown)

    sys.exit(app.exec())
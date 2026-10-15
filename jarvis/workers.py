"""Workers em background para IA, ações e síntese de voz."""
import json
import os
import base64
import subprocess
import tempfile
import threading
import time
import wave

import pyttsx3
from groq import Groq
from PySide6.QtCore import QThread, Signal

import acoes
import ferramentas
from .audio import speech_lock
from .settings import *  # noqa: F403

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
        """Usa a voz masculina Daniel do Windows Speech quando a rede neural falha."""
        script = r'''
Add-Type -AssemblyName System.Speech
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
$text = [Console]::In.ReadToEnd()
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $speaker.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -eq "Microsoft Daniel" } | Select-Object -First 1
if (-not $voice) { throw "Microsoft Daniel não está instalado. Vozes disponíveis: $($speaker.GetInstalledVoices().VoiceInfo.Name -join ', ')" }
$speaker.SelectVoice("Microsoft Daniel")
$escaped = [System.Security.SecurityElement]::Escape($text)
$ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='pt-BR'><voice name='Microsoft Daniel'><prosody pitch='-4st' rate='-8%'>$escaped</prosody></voice></speak>"
$speaker.SpeakSsml($ssml)
$speaker.Dispose()
'''
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process.stdin.write(self.text.encode("utf-8"))
            process.stdin.close()
            while process.poll() is None:
                if self._parar.is_set():
                    process.terminate()
                    return
                time.sleep(0.05)
            if process.returncode:
                erro = process.stderr.read().decode("utf-8", errors="replace")
                raise RuntimeError(erro or f"PowerShell saiu com código {process.returncode}")
        finally:
            if process.poll() is None:
                process.terminate()

    def _sintetizar_piper(self, arquivo_saida):
        """Gera fala masculina brasileira local, sem depender do serviço online."""
        from piper import PiperVoice

        if not os.path.isfile(PIPER_VOICE_MODEL):
            raise FileNotFoundError(f"modelo Piper ausente: {PIPER_VOICE_MODEL}")
        voice = PiperVoice.load(PIPER_VOICE_MODEL)
        with wave.open(arquivo_saida, "wb") as wav_file:
            voice.synthesize_wav(self.text, wav_file)

    def _falar_pyttsx3(self):
        engine = pyttsx3.init()
        engine.setProperty("rate", SPEECH_RATE)
        voices = engine.getProperty("voices")
        masculinas = []
        nomes_masculinos = (
            "daniel", "antonio", "antônio", "david", "mark", "jorge", "faber", "cadu", "jeff", "male"
        )
        nomes_femininos = ("maria", "zira", "female")
        for v in voices:
            name = v.name.lower()
            if any(n in name for n in nomes_femininos):
                continue
            if any(n in name for n in nomes_masculinos):
                masculinas.append(v)
        if not masculinas:
            engine.stop()
            raise RuntimeError("nenhuma voz masculina instalada foi encontrada no pyttsx3")
        escolha = next((v for v in masculinas if "pt-br" in v.name.lower() or "brazil" in v.name.lower()), masculinas[0])
        engine.setProperty("voice", escolha.id)
        print(f"[voz] pyttsx3: {escolha.name}.")

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
                audio_gerado = None
                try:
                    import pygame

                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as arquivo:
                        arquivo_temporario = arquivo.name

                    falou_localmente = False
                    erro_edge = None
                    if USE_EDGE_TTS:
                        try:
                            import asyncio
                            import edge_tts

                            comunicacao = edge_tts.Communicate(
                                text=self.text,
                                voice=TTS_VOICE,
                                rate=TTS_RATE,
                                pitch=TTS_PITCH,
                            )
                            asyncio.run(comunicacao.save(arquivo_temporario))
                            if os.path.getsize(arquivo_temporario) == 0:
                                raise RuntimeError("o serviço neural não retornou áudio")
                            audio_gerado = arquivo_temporario
                            print(f"[voz] Edge TTS: {TTS_VOICE}, pitch {TTS_PITCH}, velocidade {TTS_RATE}.")
                        except Exception as erro:
                            erro_edge = erro

                    if not USE_EDGE_TTS or erro_edge is not None:
                        if erro_edge is not None:
                            print(f"[voz] Edge TTS indisponível ({erro_edge}); usando Piper local.")
                        try:
                            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_temp:
                                audio_gerado = wav_temp.name
                            self._sintetizar_piper(audio_gerado)
                            print("[voz] Piper pt_BR-faber-medium (masculina, local).")
                        except Exception as erro_piper:
                            if audio_gerado and audio_gerado.endswith(".wav") and os.path.exists(audio_gerado):
                                os.remove(audio_gerado)
                            audio_gerado = None
                            print(f"[voz] Piper indisponível ({erro_piper}); tentando Microsoft Daniel.")
                            try:
                                self._falar_windows()
                                falou_localmente = True
                                print("[voz] Microsoft Daniel (Windows Speech), pitch -4st, velocidade -8%.")
                            except Exception as erro_pyttsx3:
                                print(f"[voz] Daniel indisponível ({erro_pyttsx3}); tentando outra voz masculina instalada.")
                                try:
                                    self._falar_pyttsx3()
                                    falou_localmente = True
                                except Exception as erro_reserva:
                                    print(f"[voz] nenhuma voz masculina local disponível ({erro_reserva}); não usarei uma voz feminina como reserva.")

                    if (not self._parar.is_set() and not falou_localmente and audio_gerado
                            and os.path.exists(audio_gerado) and os.path.getsize(audio_gerado) > 0):
                        if not pygame.mixer.get_init():
                            pygame.mixer.init()
                        pygame.mixer.music.load(audio_gerado)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            if self._parar.is_set():
                                pygame.mixer.music.stop()
                                break
                            time.sleep(0.03)
                        pygame.mixer.music.unload()
                except Exception as erro:
                    print(f"[voz] erro ao sintetizar ou reproduzir: {erro}")
                    if not self._parar.is_set():
                        try:
                            self._falar_pyttsx3()
                        except Exception as fallback_error:
                            print(f"[voz] fallback pyttsx3 falhou: {fallback_error}")
                finally:
                    if arquivo_temporario and os.path.exists(arquivo_temporario):
                        try:
                            os.remove(arquivo_temporario)
                        except OSError:
                            pass
                    if audio_gerado and audio_gerado != arquivo_temporario and os.path.exists(audio_gerado):
                        try:
                            os.remove(audio_gerado)
                        except OSError:
                            pass
        self.finished_speaking.emit(self)


\n
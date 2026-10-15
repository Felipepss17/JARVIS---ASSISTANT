"""Coordenação dos eventos, workers, interface e comandos do J.A.R.V.I.S."""
import os
import re
import subprocess
import webbrowser

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QStyle

import ferramentas
from .audio import (
    ListenerWorker, find_installed_app, find_roblox_studio, interpretar_sim_nao,
    mentions_studio, tocar_som,
)
from .settings import *  # noqa: F403
from .ui import ChatWindow, FloatingReactor
from .workers import AIWorker, ActionWorker, SpeakWorker

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

        # Se for um comando simples de ação (como abrir o YouTube, pastas, etc.), tenta executar
        if any(w in lower for w in ["abra", "abrir", "abre", "pasta"]) and "http" not in lower:
            self.action_busy = True
            self.action_worker = ActionWorker(text, "chat")
            self.action_worker.done.connect(self.on_action_done)
            self.action_worker.start()
        else:
            self.ask_ai(text, origem="chat")

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


\n
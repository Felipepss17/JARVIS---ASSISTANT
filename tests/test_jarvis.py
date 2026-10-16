"""Testes automatizados das partes locais do J.A.R.V.I.S."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

import acoes
import ferramentas
import jarvis.routines as routines
import jarvis.reminders as reminders
import jarvis.screen_vision as screen_vision
import jarvis.system_status as system_status
import jarvis.roblox_bridge as roblox_bridge
import jarvis.file_search as file_search
import jarvis.lifecycle as lifecycle
import jarvis.idea_inbox as idea_inbox
from jarvis.audio import (
    ListenerWorker,
    _provavel_eco,
    block_rms,
    has_content,
    interpretar_sim_nao,
    normalize,
    split_wake,
)
from jarvis.memory import CONFIRM_CLEAR_ALL, MemoryStore, handle_command, is_memory_command
from jarvis.settings import SPEECH_RATE, TTS_PITCH, TTS_RATE, TTS_VOICE, VISION_MODEL
from jarvis.ui import ChatWindow, FloatingReactor
from jarvis.workers import AIWorker, SpeakWorker


class AudioUtilityTests(unittest.TestCase):
    def test_block_rms_and_normalize(self):
        self.assertAlmostEqual(block_rms(np.array([3, 4])), 3.5355339059)
        self.assertEqual(normalize(np.zeros(4, dtype=np.int16)).tolist(), [0, 0, 0, 0])

    def test_wake_word_and_command_content(self):
        self.assertEqual(split_wake("Jarvis abra o YouTube"), (True, "abra o youtube"))
        self.assertTrue(has_content("abrir calculadora"))
        self.assertFalse(has_content("oi"))

    def test_yes_no_interpretation(self):
        self.assertIs(interpretar_sim_nao("sim, pode"), True)
        self.assertIs(interpretar_sim_nao("não, cancelar"), False)
        self.assertIsNone(interpretar_sim_nao("talvez"))

    def test_natural_phrase_interrupts_without_wake_word(self):
        listener = ListenerWorker()
        listener.begin_speaking("Estou verificando isso para você")
        received = []
        listener.interrupt.connect(received.append)

        listener._dispatch("abra o YouTube", eco=listener.speech_text)

        self.assertEqual(received, ["abra o YouTube"])
        self.assertFalse(listener.speaking.is_set())

    def test_wake_word_is_optional_during_interruption(self):
        listener = ListenerWorker()
        listener.begin_speaking("Resposta do assistente")
        received = []
        listener.interrupt.connect(received.append)

        listener._dispatch("Jarvis, pare", eco=listener.speech_text)

        self.assertEqual(received, [""])
        self.assertFalse(listener.speaking.is_set())

    def test_echo_filter_ignores_assistant_audio(self):
        self.assertTrue(_provavel_eco(
            "Estou verificando isso para você",
            "Estou verificando isso para você agora.",
        ))
        self.assertFalse(_provavel_eco(
            "abra o YouTube",
            "Estou verificando isso para você agora.",
        ))


class ToolTests(unittest.TestCase):
    def test_restart_request_recognizes_jarvis_and_short_command(self):
        self.assertTrue(lifecycle.is_restart_request("Reinicie o JARVIS, por favor"))
        self.assertTrue(lifecycle.is_restart_request("reiniciar"))
        self.assertFalse(lifecycle.is_restart_request("reiniciar o computador"))

    def test_restart_launcher_uses_detached_delayed_helper_without_shell(self):
        popen = MagicMock()
        lifecycle.launch_delayed_restart("C:/JARVIS", "C:/JARVIS/main.py", "python.exe", popen)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0:2], ["python.exe", "-c"])
        self.assertIn("time.sleep(1.5)", args[0][2])
        self.assertEqual(kwargs["cwd"], "C:/JARVIS")
        self.assertNotIn("shell", kwargs)

    def test_smart_file_search_finds_and_opens_matching_document(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docs = Path(temp_dir, "Documentos")
            docs.mkdir()
            target = docs / "Trabalho de Ciências.docx"
            target.write_bytes(b"fake document")
            opened = []
            result = file_search.open_best_match("abre o trabalho de ciencias", roots=[temp_dir], opener=opened.append)
            self.assertEqual(result, ("opened", str(target)))
            self.assertEqual(opened, [str(target)])

    def test_smart_file_search_does_not_return_executables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "trabalho de ciencias.exe").write_bytes(b"not a document")
            self.assertEqual(file_search.search_files("trabalho de ciencias", roots=[temp_dir]), [])

    def test_roblox_script_tools_are_confined_to_configured_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "src", "ServerScript.luau")
            script_path.parent.mkdir()
            script_path.write_text("print('oi')", encoding="utf-8")
            with patch.dict(os.environ, {"JARVIS_ROBLOX_PROJECT_DIR": temp_dir}):
                self.assertEqual(ferramentas.roblox_list_scripts(), "src/ServerScript.luau")
                self.assertEqual(ferramentas.roblox_read_script(caminho="src/ServerScript.luau"), "print('oi')")
                with self.assertRaises(ValueError):
                    ferramentas.roblox_read_script(caminho="../outside.lua")
                with self.assertRaises(ValueError):
                    ferramentas.roblox_read_script(caminho="notes.txt")

    def test_roblox_output_bridge_accepts_only_error_and_warning(self):
        old_records = list(roblox_bridge._records)
        try:
            roblox_bridge._records.clear()
            from unittest.mock import Mock
            handler = object.__new__(roblox_bridge._Handler)
            handler.path = "/roblox/output"
            handler.headers = {"Content-Length": "45"}
            handler.rfile = io.BytesIO(b'{"level":"error","message":"bad script"}')
            handler.send_response = Mock()
            handler.end_headers = Mock()
            handler.send_error = Mock()
            handler.wfile = io.BytesIO()
            handler.do_POST()
            self.assertIn("bad script", roblox_bridge.get_recent_output())
            self.assertFalse(handler.send_error.called)
        finally:
            roblox_bridge._records.clear()
            roblox_bridge._records.extend(old_records)

    def test_workspace_path_is_confined(self):
        resolved = ferramentas._resolver(ferramentas.WORKSPACE, "subpasta")
        self.assertEqual(resolved, os.path.join(ferramentas.WORKSPACE, "subpasta"))
        with self.assertRaises(ValueError):
            ferramentas._resolver(ferramentas.WORKSPACE, "..\\fora")

    def test_plugin_validator_requires_handle(self):
        self.assertIsNone(ferramentas._validar_plugin("def handle(texto):\n    return None\n"))
        self.assertIn("handle", ferramentas._validar_plugin("def outra(texto):\n    return None\n"))
        self.assertIn("sintaxe", ferramentas._validar_plugin("def handle(:\n    pass\n"))

    def test_tool_schema_and_unknown_tool(self):
        self.assertTrue(ferramentas.ESQUEMA)
        self.assertTrue(all(item["type"] == "function" for item in ferramentas.ESQUEMA))
        self.assertIn("desconhecida", ferramentas.executar("nao_existe", {}, lambda _: False))

    def test_backup_contains_new_package_and_excludes_env(self):
        old_backups = ferramentas.BACKUPS
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ferramentas.BACKUPS = temp_dir
                ferramentas.backup_codigo()
                backup_path = next(os.path.join(temp_dir, name) for name in os.listdir(temp_dir)
                                   if name.endswith(".zip"))
                with zipfile.ZipFile(backup_path) as archive:
                    names = archive.namelist()
                self.assertIn("jarvis/settings.py", names)
                self.assertFalse(any(name.endswith(".env") for name in names))
        finally:
            ferramentas.BACKUPS = old_backups


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(os.path.join(self.temp_dir.name, "memory.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_list_and_deduplicate_explicit_memory(self):
        self.assertTrue(is_memory_command("Lembre que prefiro respostas curtas"))
        self.assertIn("Anotado", handle_command("Lembre que prefiro respostas curtas", self.store))
        self.assertIn("já está guardada", handle_command("Guarde que prefiro respostas curtas", self.store))
        result = handle_command("O que você lembra de mim?", self.store)
        self.assertIn("[preferência] prefiro respostas curtas", result)

    def test_memory_commands_are_handled_locally_by_actions(self):
        with patch("jarvis.memory._store", self.store):
            reply = acoes.try_handle("Lembre que meu nome é Felipe")
            self.assertIn("Anotado", reply)
            self.assertIn("Felipe", acoes.try_handle("O que você lembra de mim?"))
            self.assertEqual(acoes.try_handle("Apague todas as memórias"), CONFIRM_CLEAR_ALL)

    def test_delete_specific_memory_and_confirm_delete_all(self):
        self.store.add("prefiro respostas curtas")
        self.assertIn("Apaguei", handle_command("Esqueça que prefiro respostas curtas", self.store))
        self.assertEqual(self.store.list_all(), [])
        self.store.add("meu nome é Felipe")
        self.assertEqual(handle_command("Apague todas as memórias", self.store), CONFIRM_CLEAR_ALL)
        self.assertEqual(len(self.store.list_all()), 1)

    def test_memory_context_is_bounded_and_local(self):
        self.store.add("meu nome é Felipe")
        self.assertIn("Felipe", self.store.prompt_context())
        self.assertNotIn("Felipe", MemoryStore(os.path.join(self.temp_dir.name, "outro.sqlite3")).prompt_context())


class IdeaInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = idea_inbox.IdeaInbox(os.path.join(self.temp_dir.name, "inbox.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_voice_commands_add_and_list_ideas_and_tasks(self):
        self.assertTrue(idea_inbox.is_inbox_command("Anota uma ideia: fazer um jogo de roblox"))
        reply = idea_inbox.handle_command("Anota uma ideia: fazer um jogo de roblox", self.store)
        self.assertIn("Anotei ideia #1", reply)
        idea_inbox.handle_command("Guarde a tarefa de estudar matemática", self.store)
        self.assertIn("jogo de roblox", idea_inbox.handle_command("minhas ideias", self.store))
        self.assertIn("estudar matemática", idea_inbox.handle_command("minhas tarefas", self.store))

    def test_inbox_items_can_be_completed_or_deleted(self):
        self.store.add("tarefa", "terminar trabalho")
        self.assertIn("concluído", idea_inbox.handle_command("concluir tarefa 1", self.store))
        self.assertEqual(self.store.list_items(), [])
        self.assertEqual(self.store.list_items(include_completed=True)[0]["content"], "terminar trabalho")
        self.store.add("ideia", "novo projeto")
        self.assertIn("Removi", idea_inbox.handle_command("apague ideia 2", self.store))
        self.assertEqual(len(self.store.list_items(include_completed=True)), 1)

    def test_inbox_voice_commands_are_routed_locally(self):
        with patch("jarvis.idea_inbox._store", self.store):
            self.assertIn("Anotei tarefa", acoes.try_handle("Anote uma tarefa: estudar álgebra"))
            self.assertIn("estudar álgebra", acoes.try_handle("minhas tarefas"))


class RoutineTests(unittest.TestCase):
    @patch("acoes.run_study_mode", return_value="rotina executada")
    def test_study_mode_is_routed_as_a_local_command(self, run_routine):
        self.assertTrue(routines.is_routine_command("Ative o modo de estudo"))
        self.assertEqual(acoes.try_handle("Ative o modo de estudo"), "rotina executada")
        run_routine.assert_called_once_with()

    @patch("jarvis.routines.os.startfile", create=True)
    @patch("jarvis.routines.webbrowser.open", return_value=True)
    @patch("acoes.open_app", return_value=True)
    @patch("jarvis.routines._load_routines")
    def test_study_mode_runs_configured_steps(self, load, open_app, open_url, startfile):
        load.return_value = {
            "modo estudo": {
                "apps": ["visual studio code"],
                "folders": ["."],
                "urls": ["https://example.com/playlist"],
                "open_focus_settings": True,
                "mute": False,
            }
        }
        reply = routines.run_study_mode()
        open_app.assert_called_once_with("visual studio code")
        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(startfile.call_count, 2)
        self.assertIn("playlist", reply)
        self.assertIn("foco", reply)


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = reminders.ReminderStore(os.path.join(self.temp_dir.name, "reminders.sqlite3"))
        self.now = datetime.now().astimezone()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_voice_request_parses_and_requires_confirmation_before_saving(self):
        request = "Me lembre de estudar amanhã às 19h"
        self.assertTrue(reminders.is_reminder_command(request))
        response = reminders.handle_command(request, self.store, now=self.now)
        self.assertTrue(response.startswith(reminders.CONFIRM_PREFIX))
        self.assertEqual(self.store.list_pending(), [])
        proposal = json.loads(response[len(reminders.CONFIRM_PREFIX):])
        reply = reminders.confirm_reminder(proposal, self.store)
        self.assertIn("estudar", reply)
        self.assertEqual(len(self.store.list_pending()), 1)

    def test_relative_reminder_fires_once_and_can_be_cancelled(self):
        proposal_text = reminders.handle_command(
            "me lembre de tomar água em 30 minutos", self.store, now=self.now
        )
        proposal = json.loads(proposal_text[len(reminders.CONFIRM_PREFIX):])
        reminders.confirm_reminder(proposal, self.store)
        due_at = datetime.fromisoformat(proposal["due_at"]).astimezone(timezone.utc)
        self.assertEqual(len(self.store.pop_due(now=due_at - timedelta(seconds=1))), 0)
        self.assertEqual(len(self.store.pop_due(now=due_at + timedelta(seconds=1))), 1)
        self.assertEqual(self.store.pop_due(now=due_at + timedelta(seconds=2)), [])

        another_id = self.store.add("ler", due_at + timedelta(hours=1))
        self.assertTrue(self.store.delete(another_id))
        self.assertFalse(self.store.delete(another_id))


class ScreenVisionTests(unittest.TestCase):
    def test_screen_questions_are_detected_in_portuguese(self):
        self.assertTrue(screen_vision.is_screen_question("O que está acontecendo aqui?"))
        self.assertTrue(screen_vision.is_screen_question("Analise a tela"))
        self.assertFalse(screen_vision.is_screen_question("O que está acontecendo no mundo?"))

    @patch("jarvis.workers.Groq")
    def test_vision_worker_sends_image_to_vision_model_and_discards_it(self, groq_type):
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="Uma janela está aberta."))]
        groq_type.return_value.chat.completions.create.return_value = response
        request = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "O que está acontecendo aqui?"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
            ],
        }]
        worker = AIWorker(request, agente=False, vision=True)

        worker.run()

        kwargs = groq_type.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], VISION_MODEL)
        self.assertIn("image_url", str(kwargs["messages"]))
        self.assertEqual(worker.history, [])


class SystemStatusTests(unittest.TestCase):
    def test_system_status_request_detection(self):
        self.assertTrue(system_status.is_system_status_request("Como está o sistema?"))
        self.assertTrue(system_status.is_system_status_request("status do meu sistema"))
        self.assertFalse(system_status.is_system_status_request("abra o sistema de arquivos"))

    @patch("jarvis.system_status.open_programs", return_value=["Editor - notas.txt"])
    @patch("jarvis.system_status.microphone_status", return_value="Microfone USB (captura ativa)")
    @patch("jarvis.system_status.volume_status", return_value="42%")
    @patch("jarvis.system_status.battery_status", return_value="78%, na bateria")
    def test_status_summary_includes_requested_local_information(
        self, battery, volume, microphone, programs
    ):
        controller = SimpleNamespace(
            ai_busy=True, action_busy=False, pending_speech=0, listener=None, pending_reminder=None
        )
        result = system_status.format_system_status(controller)
        self.assertIn("78%", result)
        self.assertIn("42%", result)
        self.assertIn("Microfone USB", result)
        self.assertIn("Editor - notas.txt", result)
        self.assertIn("IA processando", result)


class ActionTests(unittest.TestCase):
    def test_google_action_opens_search_url(self):
        with patch.object(acoes.webbrowser, "open") as open_url:
            reply = acoes.try_handle("pesquise sobre roblox")
        self.assertIn("Pesquisando", reply)
        open_url.assert_called_once()


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_chat_and_reactor_construct(self):
        chat = ChatWindow()
        reactor = FloatingReactor()
        try:
            self.assertIn("J.A.R.V.I.S.", chat.windowTitle())
            self.assertEqual((reactor.width(), reactor.height()), (150, 150))
        finally:
            chat.close()
            reactor.close()


class VoiceSettingsTests(unittest.TestCase):
    def test_voice_is_brazilian_male_and_lowered(self):
        self.assertEqual(TTS_VOICE, "pt-BR-AntonioNeural")
        self.assertEqual(TTS_PITCH, "-18Hz")
        self.assertLess(SPEECH_RATE, 175)


class VoiceFallbackTests(unittest.TestCase):
    def test_failed_edge_tts_uses_local_piper_voice(self):
        import edge_tts

        communication = MagicMock()
        communication.save = AsyncMock(side_effect=RuntimeError("serviço indisponível"))
        worker = SpeakWorker("Teste de fallback")
        with patch("jarvis.workers.USE_EDGE_TTS", True), \
             patch.object(edge_tts, "Communicate", return_value=communication), \
             patch.object(worker, "_sintetizar_piper") as piper_voice, \
             patch.object(worker, "_falar_windows") as windows_voice:
            worker.run()
        piper_voice.assert_called_once()
        windows_voice.assert_not_called()

    def test_local_tts_does_not_speak_with_female_voice_as_fallback(self):
        worker = SpeakWorker("Teste")
        voz_feminina = MagicMock(name="Microsoft Maria Desktop")
        voz_feminina.name = "Microsoft Maria Desktop"
        voz_feminina.id = "maria"
        engine = MagicMock()
        engine.getProperty.return_value = [voz_feminina]
        with patch("jarvis.workers.pyttsx3.init", return_value=engine):
            with self.assertRaisesRegex(RuntimeError, "nenhuma voz masculina"):
                worker._falar_pyttsx3()
        engine.say.assert_not_called()


@unittest.skipUnless(os.environ.get("JARVIS_TEST_EDGE_VOICE") == "1",
                     "defina JARVIS_TEST_EDGE_VOICE=1 para testar Edge TTS online")
class EdgeOnlineVoiceTests(unittest.TestCase):
    def test_edge_tts_returns_male_brazilian_audio(self):
        import asyncio
        import edge_tts

        async def generate(path):
            communication = edge_tts.Communicate(
                text="Olá, senhor. Esta é a nova voz do JARVIS.",
                voice=TTS_VOICE,
                rate=TTS_RATE,
                pitch=TTS_PITCH,
            )
            await communication.save(path)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as output:
            audio_path = output.name
        try:
            try:
                asyncio.run(generate(audio_path))
            except Exception as error:
                if getattr(error, "status", None) == 403 or "403" in str(error):
                    self.skipTest("o endpoint Edge TTS recusou a conexão com HTTP 403")
                raise
            result = Path(audio_path).read_bytes()
            self.assertGreater(len(result), 1024)
            self.assertTrue(result.startswith(b"ID3") or result[0] == 0xFF)
        finally:
            os.remove(audio_path)

class GoogleOnlineVoiceTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("JARVIS_TEST_ONLINE_VOICE") == "1",
                         "defina JARVIS_TEST_ONLINE_VOICE=1 para testar gTTS")
    def test_gtts_returns_portuguese_audio(self):
        from gtts import gTTS

        audio = io.BytesIO()
        gTTS(text="Teste de voz online do JARVIS.", lang="pt", slow=False).write_to_fp(audio)
        result = audio.getvalue()
        self.assertGreater(len(result), 1024)
        self.assertTrue(result.startswith(b"ID3") or result[0] == 0xFF,
                        "a resposta da gTTS não parece ser um arquivo MP3")


if __name__ == "__main__":
    unittest.main(verbosity=2)

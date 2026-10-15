"""Testes automatizados das partes locais do J.A.R.V.I.S."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

import acoes
import ferramentas
from jarvis.audio import block_rms, has_content, interpretar_sim_nao, normalize, split_wake
from jarvis.settings import SPEECH_RATE, TTS_PITCH, TTS_RATE, TTS_VOICE
from jarvis.ui import ChatWindow, FloatingReactor
from jarvis.workers import SpeakWorker


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


class ToolTests(unittest.TestCase):
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

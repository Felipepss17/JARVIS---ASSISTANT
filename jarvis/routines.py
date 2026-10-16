"""Rotinas locais e configuráveis para encadear ações do J.A.R.V.I.S."""
import json
import os
import re
import unicodedata
import webbrowser

from .settings import PROJECT_ROOT

WORKSPACE = os.path.join(PROJECT_ROOT, "jarvis_workspace")
ROUTINES_FILE = os.path.join(WORKSPACE, "rotinas.json")

DEFAULT_ROUTINES = {
    "modo estudo": {
        "apps": ["visual studio code"],
        "folders": ["."],
        "urls": ["https://www.youtube.com/results?search_query=lofi+para+estudar+playlist"],
        "open_focus_settings": True,
        "mute": False,
    }
}


def is_routine_command(text):
    normalized = unicodedata.normalize("NFD", str(text).casefold())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return bool(re.search(r"\bmodo (?:de )?estudo\b", normalized))


def _load_routines():
    os.makedirs(WORKSPACE, exist_ok=True)
    if not os.path.exists(ROUTINES_FILE):
        with open(ROUTINES_FILE, "w", encoding="utf-8") as profile:
            json.dump(DEFAULT_ROUTINES, profile, ensure_ascii=False, indent=2)
        return DEFAULT_ROUTINES
    try:
        with open(ROUTINES_FILE, "r", encoding="utf-8") as profile:
            data = json.load(profile)
        return data if isinstance(data, dict) else DEFAULT_ROUTINES
    except (OSError, json.JSONDecodeError) as error:
        print(f"[rotinas] não consegui ler {ROUTINES_FILE}: {error}")
        return DEFAULT_ROUTINES


def run_study_mode():
    """Executa a sequência configurada e informa quais etapas foram concluídas."""
    from acoes import open_app

    routine = _load_routines().get("modo estudo", {})
    completed = []
    failed = []

    for app in routine.get("apps", []):
        try:
            if open_app(str(app)):
                completed.append(f"abri {app}")
            else:
                failed.append(f"não encontrei {app}")
        except OSError as error:
            failed.append(f"falha ao abrir {app}: {error}")

    for folder in routine.get("folders", []):
        path = os.path.abspath(os.path.join(WORKSPACE, str(folder)))
        try:
            inside_workspace = os.path.commonpath([WORKSPACE, path]) == os.path.abspath(WORKSPACE)
        except ValueError:
            inside_workspace = False
        if not inside_workspace:
            failed.append(f"pasta fora do workspace ignorada: {folder}")
            continue
        try:
            os.startfile(path)
            completed.append("abri sua pasta de trabalho")
        except (OSError, AttributeError) as error:
            failed.append(f"não consegui abrir a pasta: {error}")

    if routine.get("mute"):
        try:
            import keyboard
            keyboard.send("volume mute")
            completed.append("ativei o mudo")
        except Exception as error:
            failed.append(f"não consegui ativar o mudo: {error}")

    for url in routine.get("urls", []):
        try:
            if webbrowser.open(str(url)):
                completed.append("abri resultados de playlists para estudar")
            else:
                failed.append("o navegador não abriu a playlist")
        except Exception as error:
            failed.append(f"não consegui abrir a playlist: {error}")

    if routine.get("open_focus_settings"):
        try:
            os.startfile("ms-settings:quiethours")
            completed.append("abri as configurações de foco e Não Perturbe")
        except (OSError, AttributeError) as error:
            failed.append(f"não consegui abrir as configurações de foco: {error}")

    details = "; ".join(completed + failed)
    if failed:
        return f"Modo estudo iniciado com etapas pendentes: {details}."
    return f"Modo estudo iniciado: {details or 'nenhuma ação configurada.'}."

"""Operações de ciclo de vida do aplicativo JARVIS."""
import re
import subprocess
import sys
import unicodedata


def is_restart_request(text):
    value = unicodedata.normalize("NFD", str(text).casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    if not re.search(r"\b(?:reiniciar|reinicie|reinicia|restart)\b", value):
        return False
    words = value.split()
    return "jarvis" in words or len(words) <= 2


def launch_delayed_restart(project_root, main_script, executable=None, popen=None):
    """Start a detached helper that launches JARVIS after the current lock is released."""
    executable = executable or sys.executable
    popen = popen or subprocess.Popen
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    helper = (
        "import subprocess,sys,time; time.sleep(1.5); "
        "subprocess.Popen([sys.argv[1], sys.argv[2]], cwd=sys.argv[3], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
        "creationflags=int(sys.argv[4]))"
    )
    return popen(
        [executable, "-c", helper, executable, main_script, project_root, str(flags)],
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )

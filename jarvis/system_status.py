"""Consultas locais de estado do Windows e do próprio J.A.R.V.I.S."""
import ctypes
import re
import unicodedata
from ctypes import wintypes


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def is_system_status_request(text):
    value = unicodedata.normalize("NFD", str(text).casefold())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = re.sub(r"\s+", " ", value).strip(" ?.!,")
    return bool(re.search(
        r"\b(?:status|estado|situacao|informacoes) (?:do|de) (?:meu )?sistema\b|"
        r"\bcomo esta o sistema\b|\bestado do computador\b",
        value,
    ))


def battery_status():
    if not hasattr(ctypes, "windll"):
        return "indisponível neste sistema operacional"
    status = _SystemPowerStatus()
    try:
        ok = ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
    except (AttributeError, OSError):
        return "indisponível"
    if not ok:
        return "indisponível"
    if status.BatteryFlag & 128:
        return "sem bateria detectável"
    if status.BatteryLifePercent == 255:
        level = "carga desconhecida"
    else:
        level = f"{status.BatteryLifePercent}%"
    power = {0: "na bateria", 1: "conectado à energia"}.get(status.ACLineStatus, "energia desconhecida")
    return f"{level}, {power}"


def volume_status():
    if not hasattr(ctypes, "windll"):
        return "indisponível neste sistema operacional"
    packed = ctypes.wintypes.DWORD()
    try:
        result = ctypes.windll.winmm.waveOutGetVolume(wintypes.UINT(0xFFFFFFFF), ctypes.byref(packed))
    except (AttributeError, OSError):
        return "indisponível"
    if result:
        return "indisponível"
    left = packed.value & 0xFFFF
    right = (packed.value >> 16) & 0xFFFF
    percent = round(((left + right) / 2) * 100 / 0xFFFF)
    return f"{percent}%" + (", mudo" if percent == 0 else "")


def microphone_status(listener=None):
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        selected = None
        if listener is not None:
            from .audio import find_mic
            selected = find_mic()
        if selected is None:
            default_device = sd.default.device
            selected = default_device[0] if default_device else None
        if selected is not None and int(selected) >= 0:
            device = sd.query_devices(int(selected))
        else:
            device = next((item for item in devices if item["max_input_channels"] > 0), None)
        if not device or device["max_input_channels"] <= 0:
            return "nenhum dispositivo de entrada encontrado"
        active = bool(listener and listener.running and not listener.paused.is_set())
        state = "captura ativa" if active else "disponível"
        return f"{device['name']} ({state})"
    except Exception:
        return "indisponível"


def open_programs(limit=12):
    if not hasattr(ctypes, "windll"):
        return []
    user32 = ctypes.windll.user32
    titles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    def collect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        value = title.value.strip()
        if value and value.lower() not in {item.lower() for item in titles}:
            titles.append(value)
        return True

    callback = callback_type(collect)
    try:
        user32.EnumWindows(callback, 0)
    except Exception:
        return []
    return titles[:limit]


def format_system_status(controller):
    programs = open_programs(limit=13)
    if programs:
        program_text = "; ".join(programs[:12])
        if len(programs) > 12:
            program_text += "; …"
    else:
        program_text = "nenhuma janela de aplicativo detectada"

    tasks = []
    if controller.ai_busy:
        tasks.append("IA processando")
    if controller.action_busy:
        tasks.append("ação local em andamento")
    if controller.pending_speech:
        tasks.append("JARVIS falando")
    listener = controller.listener
    if listener and listener.awaiting_command:
        tasks.append("aguardando comando de voz")
    if controller.pending_reminder is not None:
        tasks.append("aguardando confirmação de lembrete")
    task_text = "; ".join(tasks) if tasks else "nenhuma tarefa em andamento"

    return (
        "Estado do sistema:\n"
        f"• Bateria: {battery_status()}\n"
        f"• Volume: {volume_status()}\n"
        f"• Microfone: {microphone_status(listener)}\n"
        f"• Programas abertos: {program_text}\n"
        f"• Tarefas: {task_text}"
    )

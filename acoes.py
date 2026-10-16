"""Ações do JARVIS. Cada função recebe o texto já limpo e devolve a frase
que ele deve falar, ou None se o comando não for dela."""
import os
import re
import glob
import json
import uuid
import ctypes
import difflib
import subprocess
import unicodedata
import webbrowser
from datetime import datetime
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
import shutil
from datetime import datetime

import keyboard
from jarvis.memory import handle_command as handle_memory_command, is_memory_command
from jarvis.routines import is_routine_command, run_study_mode
from jarvis.reminders import handle_command as handle_reminder_command, is_reminder_command
from jarvis.idea_inbox import handle_command as handle_inbox_command, is_inbox_command
from jarvis.file_search import open_best_match

# ======================= SUAS CONFIGURAÇÕES =======================
# Jogos favoritos do Roblox: "nome que você fala": ID do jogo.
# O ID é o número no link: roblox.com/games/NUMERO/nome-do-jogo
JOGOS = {
    # "meu jogo": 1234567890,
}

# Pasta que o "modo desenvolvimento" abre
PASTA_PROJETOS = os.path.expanduser(r"~\Documents")

# Programas extras do modo desenvolvimento (nome do atalho no menu Iniciar)
APPS_MODO_DEV = ["visual studio code"]
# ==================================================================

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

STOP = r"(?:o|a|os|as|um|uma|de|do|da|dos|das|sobre|por|pelo|pela|no|na|em|pra|para|que|ver|me)"


# ---------------- utilidades ----------------
def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def clean(s):
    s = norm(s)
    s = re.sub(r"\b(jarvis|por favor|senhor|pra mim|para mim)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,.!?")


def strip_leading(term, extra=""):
    pattern = r"^(?:(?:" + STOP + extra + r")\s+)+"
    return re.sub(pattern, "", term).strip(" ,.!?")


def find_roblox_studio():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "Versions")
    if os.path.isdir(base):
        for folder in os.listdir(base):
            exe = os.path.join(base, folder, "RobloxStudioBeta.exe")
            if os.path.isfile(exe):
                return exe
    return None


def find_installed_app(app_name):
    app_name = norm(app_name)
    patterns = [
        os.path.expanduser(r"~\Desktop\*.lnk"),
        os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\**\*.lnk"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\**\*.lnk",
    ]
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            if app_name in norm(os.path.basename(path)):
                return path
    return None


def open_app(name):
    lnk = find_installed_app(name)
    if lnk:
        os.startfile(lnk)
        return True
    return False


def http_json(url, timeout=5):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- modo desenvolvimento ----------------
def h_modo_dev(t):
    if not re.search(r"\bmodo (?:de )?(?:desenvolvimento|dev|programacao|trabalho)\b", t):
        return None
    abertos = 0
    exe = find_roblox_studio()
    if exe:
        subprocess.Popen([exe])
        abertos += 1
    for app in APPS_MODO_DEV:
        if open_app(app):
            abertos += 1
    if os.path.isdir(PASTA_PROJETOS):
        os.startfile(PASTA_PROJETOS)
    if abertos == 0:
        return "Modo desenvolvimento ativado, mas não encontrei os programas, senhor."
    return "Modo desenvolvimento ativado, senhor."


# ---------------- sistema: bloquear, volume, mídia ----------------
def h_bloquear(t):
    if re.search(r"\bbloque\w+ (?:o |a )?(?:computador|pc|tela)\b", t):
        ctypes.windll.user32.LockWorkStation()
        return "Bloqueando o computador, senhor."
    return None


def h_volume(t):
    if re.search(r"\b(?:silenc\w+|mutar|mute)\b|\btirar? (?:do )?mudo\b", t):
        keyboard.send("volume mute")
        return "Feito, senhor."
    if "volume" not in t:
        return None
    if re.search(r"\bmaximo\b", t):
        for _ in range(50):
            keyboard.send("volume up")
        return "Volume no máximo, senhor."
    if re.search(r"\bminimo\b", t):
        for _ in range(50):
            keyboard.send("volume down")
        return "Volume no mínimo, senhor."
    if re.search(r"aument|suba|sobe|mais alto|eleve", t):
        for _ in range(5):
            keyboard.send("volume up")
        return "Aumentando o volume, senhor."
    if re.search(r"diminu|abaix|baixe|reduz|mais baixo", t):
        for _ in range(5):
            keyboard.send("volume down")
        return "Diminuindo o volume, senhor."
    return None


def h_midia(t):
    if re.search(r"\b(?:pause|pausa|pausar|retomar|continuar)\b.*\b(?:musica|video)\b", t):
        keyboard.send("play/pause media")
        return "Feito, senhor."
    if re.search(r"\b(?:proxima musica|pular (?:a )?musica)\b", t):
        keyboard.send("next track")
        return "Próxima faixa, senhor."
    if re.search(r"\b(?:musica anterior|voltar (?:a )?musica)\b", t):
        keyboard.send("previous track")
        return "Faixa anterior, senhor."
    return None


# ---------------- hora e data ----------------
def h_hora_data(t):
    now = datetime.now()
    if re.search(r"\bque horas\b|\bhoras sao\b|\bhora atual\b", t):
        h, m = now.hour, now.minute
        verbo = "É" if h == 1 else "São"
        horas = "uma hora" if h == 1 else f"{h} horas"
        if m == 0:
            return f"{verbo} {horas} em ponto, senhor."
        mins = "1 minuto" if m == 1 else f"{m} minutos"
        return f"{verbo} {horas} e {mins}, senhor."
    if re.search(r"\bque dia (?:e )?hoje\b|\bdata de hoje\b|\bqual (?:e )?a data\b", t):
        return (f"Hoje é {DIAS[now.weekday()]}, {now.day} de "
                f"{MESES[now.month - 1]} de {now.year}, senhor.")
    return None


# ---------------- YouTube ----------------
VERBO_BUSCA = r"(?:pesquis\w+|procur\w+|busc\w+|toqu\w+|coloc\w+|ponh\w+|abr\w+|ach\w+)"


def h_youtube(t):
    is_channel = bool(re.search(r"\b(?:canal|canais)\b", t))
    if "youtube" not in t and not is_channel:
        return None
    if not re.search(r"\b" + VERBO_BUSCA + r"\b", t):
        return None
    term = re.sub(r"\b" + VERBO_BUSCA + r"\b", " ", t, count=1)
    term = re.sub(r"\b(?:" + STOP + r"\s+)?youtube\b", " ", term)
    term = re.sub(r"\s+", " ", term).strip()
    term = strip_leading(term, r"|videos?|canal|canais")
    if not term:
        return None   # "abra o youtube" continua abrindo o site normalmente
    url = "https://www.youtube.com/results?search_query=" + quote_plus(term)
    if is_channel:
        url += "&sp=EgIQAg%3D%3D"   # filtro: só canais
    webbrowser.open(url)
    if is_channel:
        return f"Procurando o canal {term} no YouTube, senhor."
    return f"Procurando vídeos de {term} no YouTube, senhor."


# ---------------- Roblox: entrar em jogo ----------------
def resolver_jogo(nome):
    """Procura o jogo pelo nome. Devolve (nome_oficial, place_id) ou None."""
    # 1) favoritos que você cadastrou
    for fav, pid in JOGOS.items():
        f = norm(fav)
        if f in nome or nome in f or difflib.SequenceMatcher(None, f, nome).ratio() >= 0.75:
            return fav, int(pid)

    # 2) busca do Roblox (API não oficial: pode mudar)
    try:
        url = "https://apis.roblox.com/search-api/omni-search?" + urlencode(
            {"searchQuery": nome, "sessionId": str(uuid.uuid4()), "pageType": "all"})
        data = http_json(url)
    except Exception as e:
        print(f"[roblox] busca falhou: {e}")
        return None

    candidatos = []

    def walk(o):
        if isinstance(o, dict):
            if "universeId" in o and "name" in o:
                candidatos.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    if not candidatos:
        return None

    def score(c):
        return difflib.SequenceMatcher(None, norm(str(c["name"])), nome).ratio()

    melhor = max(candidatos[:10], key=score)
    if score(melhor) < 0.35:
        return None   # nada parecido: melhor não arriscar entrar no jogo errado

    pid = melhor.get("rootPlaceId")
    if not pid:
        try:
            info = http_json(f"https://games.roblox.com/v1/games?universeIds={melhor['universeId']}")
            pid = info["data"][0]["rootPlaceId"]
        except Exception as e:
            print(f"[roblox] não consegui o place id: {e}")
            return None
    return str(melhor["name"]), int(pid)


def h_roblox_jogo(t):
    if "roblox" not in t and "jogo" not in t:
        return None
    m = re.search(r"\b(?:entre|entrar|entra|jogue|jogar|joga)\b\s+(.*)", t)
    if not m:
        return None
    term = re.sub(r"\b(?:" + STOP + r"\s+)?roblox\b", " ", m.group(1))
    term = re.sub(r"\s+", " ", term).strip()
    term = strip_leading(term, r"|jogo|game")
    if not term:
        return None
    achado = resolver_jogo(term)
    if achado:
        nome, pid = achado
        os.startfile(f"roblox://placeId={pid}")
        return f"Entrando em {nome}, senhor."
    webbrowser.open("https://www.roblox.com/discover/?Keyword=" + quote_plus(term))
    return "Não achei esse jogo com certeza, senhor. Abri a busca do Roblox para você."


# ---------------- Figma ----------------
def h_figma(t):
    if "figma" not in t:
        return None
    if not re.search(r"\b(?:abr\w+|cri\w+|nov[oa]|comec\w+|inici\w+)\b", t):
        return None
    if not open_app("figma"):
        webbrowser.open("https://www.figma.com/files")
    if re.search(r"\b(?:cri\w+|nov[oa]|comec\w+)\b", t):
        return ("Abri o Figma, senhor. Criar o arquivo sozinho eu ainda não consigo. "
                "É só clicar em novo arquivo de design.")
    return "Abrindo o Figma, senhor."


# ---------------- busca inteligente de documentos ----------------
def h_busca_arquivo(t):
    if not re.search(r"\b(?:arquivo|documento|trabalho|pdf|planilha|apresentacao|redacao|relatorio)\b", t):
        return None
    if not re.search(r"\b(?:abre|abrir|abra|encontre|encontrar|localize|localizar|ache|achar|busque|buscar|procure|procurar)\b", t):
        return None
    try:
        result = open_best_match(t)
    except OSError as error:
        print(f"[arquivos] não consegui abrir o resultado: {error}")
        return "Encontrei o arquivo, mas o Windows não conseguiu abri-lo, senhor."
    if result is None:
        return "Não encontrei um documento parecido em Documentos, Área de Trabalho ou Downloads, senhor."
    status, data = result
    if status == "opened":
        return f"Abri {os.path.basename(data)}, senhor."
    if status in {"ambiguous", "low_confidence"}:
        nomes = ", ".join(os.path.basename(path) for _score, path in data)
        return f"Achei algumas possibilidades: {nomes}. Qual delas o senhor quer abrir?"
    return "A busca por arquivos só está disponível no Windows, senhor."


# ---------------- pesquisa no Google ----------------
def h_google(t):
    m = re.match(r"^(?:pesquis\w+|procur\w+|busc\w+)\s+(.*)$", t)
    if not m:
        return None
    term = re.sub(r"\b(?:" + STOP + r"\s+)?(?:google|internet)\b", " ", m.group(1))
    term = re.sub(r"\s+", " ", term).strip()
    term = strip_leading(term)
    if not term:
        return None
    webbrowser.open("https://www.google.com/search?q=" + quote_plus(term))
    return f"Pesquisando {term} no Google, senhor."


HANDLERS = [h_modo_dev, h_bloquear, h_volume, h_midia, h_hora_data,
            h_youtube, h_roblox_jogo, h_figma, h_busca_arquivo, h_google]


def try_handle(text):
    raw_text = re.sub(r"\s+", " ", str(text)).strip()
    if is_inbox_command(raw_text):
        return handle_inbox_command(raw_text)
    if is_memory_command(raw_text):
        return handle_memory_command(raw_text)
    if is_reminder_command(raw_text):
        return handle_reminder_command(raw_text)
    if is_routine_command(raw_text):
        return run_study_mode()
    t = clean(text)
    print(f"[acoes] texto limpo: {t!r}")
    for handler in HANDLERS:
        reply = handler(t)
        if reply:
            return reply
    return None

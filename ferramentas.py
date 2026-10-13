"""Ferramentas do modo agente do JARVIS.

Regras aplicadas AQUI, no código (não dependem do modelo obedecer ao prompt):
- Escrever e apagar: somente dentro de jarvis_workspace/
- Ler: jarvis_workspace/ + alguns arquivos do projeto (somente leitura). Nunca o .env
- Executar código, apagar, sobrescrever, instalar pacotes e criar/remover plugins pedem autorização
- Plugins são validados (sintaxe + função handle) antes de serem salvos
- Projetos do GitHub: só baixados (zip) e analisados; nada é executado nem instalado sozinho
"""
import io
import os
import re
import ast
import sys
import json
import glob
import shutil
import zipfile
import threading
import subprocess
import importlib
import importlib.util
import urllib.error
import urllib.request
from datetime import datetime

PROJETO = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(PROJETO, "jarvis_workspace")
IMPORTADOS = os.path.join(WORKSPACE, "importados")
PLUGINS = os.path.join(PROJETO, "plugins")
BACKUPS = os.path.join(PROJETO, "backups_jarvis")

os.makedirs(WORKSPACE, exist_ok=True)
os.makedirs(IMPORTADOS, exist_ok=True)
os.makedirs(PLUGINS, exist_ok=True)

# Arquivos do projeto que o JARVIS pode LER (nunca alterar)
LEITURA_PROJETO = {"main.py", "acoes.py", "ferramentas.py",
                   "requirements.txt", "README.md", "jarvis.log"}
EXT_BLOQUEADAS = {".exe", ".bat", ".cmd", ".vbs", ".ps1", ".lnk",
                  ".dll", ".msi", ".scr", ".reg"}
EXT_CODIGO = {".py", ".pyw", ".js", ".mjs", ".ts", ".ps1", ".bat", ".cmd", ".sh", ".vbs"}

MAX_LEITURA = 12000
MAX_ARQUIVO = 200_000
MAX_RESULTADO = 6000
TIMEOUT_EXEC = 20
TIMEOUT_PLUGIN = 10
TIMEOUT_PIP = 300
MANTER_BACKUPS = 15

MAX_DOWNLOAD = 25 * 1024 * 1024          # zip baixado
MAX_DESCOMPACTADO = 120 * 1024 * 1024    # tamanho total depois de extrair
MAX_ARQUIVOS_ZIP = 3000

NEGADO = "[cancelado] O senhor não autorizou esta ação."
NOME_PLUGIN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
URL_GITHUB = re.compile(
    r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/([^/\s]+))?(?:[/?#].*)?$")
PACOTE_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}(\[[A-Za-z0-9,_-]+\])?(==[A-Za-z0-9.]+)?$")

PADROES_RISCO = [(re.compile(p), d) for p, d in [
    (r"\bos\.system\s*\(", "executa comandos do sistema (os.system)"),
    (r"\bsubprocess\.", "executa programas (subprocess)"),
    (r"\beval\s*\(", "usa eval()"),
    (r"\bexec\s*\(", "usa exec()"),
    (r"\b__import__\s*\(", "import dinâmico (__import__)"),
    (r"\bbase64\.b64decode", "decodifica dados em base64 (pode esconder código)"),
    (r"\bpickle\.loads?\s*\(|\bmarshal\.loads?\s*\(", "desserialização insegura (pickle/marshal)"),
    (r"\bsocket\.|\bparamiko\b|\bftplib\b|\bsmtplib\b", "rede de baixo nível, SSH, FTP ou e-mail"),
    (r"\brequests\.(?:get|post|put)|urllib\.request|\bhttpx\b|\baiohttp\b", "acessa a internet"),
    (r"\bshutil\.rmtree|\bos\.remove|\bos\.unlink|\bos\.rmdir", "apaga arquivos ou pastas"),
    (r"\bwinreg\b|\bctypes\b", "mexe no registro do Windows ou em DLLs (winreg/ctypes)"),
    (r"\bkeyboard\.|\bpynput\b|\bpyautogui\b", "captura ou simula teclado/mouse"),
    (r"os\.environ|getenv|\.env\b", "lê variáveis de ambiente ou .env (possível acesso a chaves)"),
    (r"browser_cookie3|Login Data|wallet\.dat|discord.{0,20}token",
     "acessa dados de navegador, carteiras ou tokens"),
]]


# ---------------- utilidades ----------------
def _cortar(texto, limite=MAX_RESULTADO):
    texto = str(texto)
    if len(texto) > limite:
        return texto[:limite] + f"\n[... resultado cortado, {len(texto)} caracteres no total]"
    return texto


def _resolver(base, caminho):
    """Resolve o caminho garantindo que ele fique DENTRO da pasta base."""
    base_real = os.path.realpath(base)
    destino = os.path.realpath(os.path.join(base_real, caminho or "."))
    try:
        dentro = os.path.commonpath([destino, base_real]) == base_real
    except ValueError:
        dentro = False
    if not dentro:
        raise ValueError("caminho fora da pasta permitida")
    return destino


def _guardar_copia(arquivo):
    """Copia um arquivo para backups_jarvis antes de alterá-lo."""
    pasta = os.path.join(BACKUPS, "arquivos_antigos")
    os.makedirs(pasta, exist_ok=True)
    nome = datetime.now().strftime("%Y%m%d_%H%M%S_") + os.path.basename(arquivo)
    destino = os.path.join(pasta, nome)
    shutil.copy2(arquivo, destino)
    return destino


def _python_exe():
    """Sem terminal o Python é o pythonw.exe (sem saída); para subprocessos usa o python.exe."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return exe


def _env_sem_chaves():
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_API_KEY")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ---------------- ferramentas de arquivos ----------------
def listar_diretorio(confirmar, caminho="."):
    destino = _resolver(WORKSPACE, caminho)
    if not os.path.isdir(destino):
        return "[erro] pasta não encontrada."
    itens = []
    for nome in sorted(os.listdir(destino)):
        itens.append(nome + "/" if os.path.isdir(os.path.join(destino, nome)) else nome)
    return "\n".join(itens) or "(pasta vazia)"


def ler_ficheiro(confirmar, caminho, inicio=0):
    c = os.path.normpath(caminho).replace("\\", "/")
    if c in LEITURA_PROJETO:
        destino = os.path.join(PROJETO, c)
    elif c.startswith("plugins/"):
        destino = _resolver(PLUGINS, c[len("plugins/"):])
    else:
        destino = _resolver(WORKSPACE, c)
    if not os.path.isfile(destino):
        return "[erro] arquivo não encontrado."
    with open(destino, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    if c == "jarvis.log":
        return txt[-MAX_LEITURA:]
    inicio = max(0, int(inicio))
    trecho = txt[inicio:inicio + MAX_LEITURA]
    faltam = len(txt) - (inicio + MAX_LEITURA)
    if faltam > 0:
        trecho += f"\n[... faltam {faltam} caracteres; use inicio={inicio + MAX_LEITURA} para continuar]"
    return trecho


def criar_ficheiro(confirmar, caminho, conteudo):
    destino = _resolver(WORKSPACE, caminho)
    if destino == os.path.realpath(WORKSPACE) or os.path.isdir(destino):
        return "[erro] informe o nome de um arquivo."
    if os.path.splitext(destino)[1].lower() in EXT_BLOQUEADAS:
        return "[bloqueado] esse tipo de arquivo não pode ser criado pelo JARVIS."
    if len(conteudo) > MAX_ARQUIVO:
        return "[erro] arquivo grande demais."
    if os.path.exists(destino):
        if not confirmar(f"Sobrescrever o arquivo '{caminho}' ({len(conteudo)} caracteres)?"):
            return NEGADO
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return f"[sucesso] '{caminho}' salvo em jarvis_workspace."


def excluir_ficheiro(confirmar, caminho):
    destino = _resolver(WORKSPACE, caminho)
    if not os.path.isfile(destino):
        return "[erro] arquivo não encontrado."
    if not confirmar(f"Apagar o arquivo '{caminho}'?"):
        return NEGADO
    os.remove(destino)
    return f"[sucesso] '{caminho}' apagado."


def executar_python(confirmar, codigo):
    previa = codigo if len(codigo) <= 1500 else codigo[:1500] + "\n[... código cortado na prévia]"
    if not confirmar("Executar este código Python no computador?\n\n" + previa):
        return NEGADO
    caminho = os.path.join(WORKSPACE, "_execucao_temp.py")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(codigo)
    try:
        r = subprocess.run(
            [_python_exe(), caminho], cwd=WORKSPACE, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT_EXEC, env=_env_sem_chaves(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return f"[erro] o código passou de {TIMEOUT_EXEC} s e foi interrompido."
    finally:
        if os.path.exists(caminho):
            os.remove(caminho)
    if r.returncode == 0:
        return "[sucesso] saída do código:\n" + (r.stdout or "(sem saída)")
    return f"[erro de execução, código {r.returncode}]\n{r.stderr}"


# ---------------- projetos do GitHub ----------------
def _http_get(url, limite=None, timeout=20, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-local", "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read(limite + 1) if limite else r.read()
    if limite and len(dados) > limite:
        raise ValueError("o arquivo passa do tamanho máximo permitido")
    return dados


def _analisar_projeto(raiz):
    """Relatório heurístico de segurança. Alertas não provam que o projeto é malicioso."""
    achados = {}
    executaveis = []
    arquivos = 0
    for atual, pastas, nomes in os.walk(raiz):
        pastas[:] = [p for p in pastas if p not in (".git", "node_modules", "__pycache__")]
        for nome in nomes:
            ext = os.path.splitext(nome)[1].lower()
            caminho = os.path.join(atual, nome)
            rel = os.path.relpath(caminho, raiz).replace("\\", "/")
            if ext in EXT_BLOQUEADAS:
                executaveis.append(rel)
            if ext not in EXT_CODIGO:
                continue
            arquivos += 1
            if arquivos > 400:
                continue
            try:
                if os.path.getsize(caminho) > 400_000:
                    continue
                with open(caminho, "r", encoding="utf-8", errors="replace") as f:
                    for n, linha in enumerate(f, 1):
                        for padrao, desc in PADROES_RISCO:
                            if padrao.search(linha):
                                achados.setdefault(desc, []).append(f"{rel}:{n}")
            except OSError:
                pass

    total = sum(len(v) for v in achados.values())
    linhas = [f"{len(achados)} tipo(s) de alerta ({total} ocorrência(s)) em {min(arquivos, 400)} "
              f"arquivo(s) de código; {len(executaveis)} executável(is)/script(s) de sistema."]
    for desc, locais in sorted(achados.items(), key=lambda kv: -len(kv[1])):
        exemplos = ", ".join(locais[:3])
        linhas.append(f"- {desc}: {len(locais)}x (ex.: {exemplos})")
    if executaveis:
        linhas.append("- executáveis/scripts de sistema no projeto: " + ", ".join(executaveis[:6]))
    linhas.append("Obs.: muitos programas legítimos usam essas funções. O relatório mostra "
                  "o que conferir; ele não prova que o projeto é seguro nem malicioso.")
    return "\n".join(linhas)


def _estrutura(raiz, profundidade=2, limite=70):
    saida = []
    base = raiz.rstrip("\\/")
    for atual, pastas, nomes in os.walk(raiz):
        pastas[:] = sorted(p for p in pastas if not p.startswith(".") and p not in ("node_modules", "__pycache__"))
        nivel = os.path.relpath(atual, base).count(os.sep) if atual != base else 0
        if nivel >= profundidade:
            pastas[:] = []
        recuo = "  " * nivel
        if atual != base:
            saida.append(f"{recuo[:-2]}{os.path.basename(atual)}/")
        for n in sorted(nomes):
            if not n.startswith("."):
                saida.append(f"{recuo}{n}")
        if len(saida) >= limite:
            saida.append("[... lista cortada]")
            break
    return "\n".join(saida)


def _ler_inicio(caminho, limite):
    try:
        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limite)
    except OSError:
        return ""


def baixar_projeto_github(confirmar, url):
    m = URL_GITHUB.match((url or "").strip())
    if not m:
        return "[erro] isso não parece um link de repositório do GitHub (https://github.com/dono/repositorio)."
    dono, repo, ramo = m.group(1), m.group(2), m.group(3)

    try:
        info = json.loads(_http_get(f"https://api.github.com/repos/{dono}/{repo}", 2_000_000,
                                    accept="application/vnd.github+json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "[erro] repositório não encontrado (ou é privado: só repositórios públicos funcionam)."
        if e.code == 403:
            return "[erro] o GitHub limitou as consultas por agora. Tente de novo em alguns minutos."
        return f"[erro] o GitHub respondeu com erro {e.code}."
    except Exception as e:
        return f"[erro] não consegui falar com o GitHub: {e}"

    if info.get("size", 0) * 1024 > MAX_DESCOMPACTADO:
        return "[erro] repositório grande demais para importar."

    nome_completo = info.get("full_name", f"{dono}/{repo}")
    ramo = ramo or info.get("default_branch", "main")
    pasta = re.sub(r"[^\w.-]", "_", nome_completo.replace("/", "_"))
    destino = _resolver(IMPORTADOS, pasta)

    if os.path.exists(destino):
        if not confirmar(f"O projeto '{pasta}' já foi baixado. Substituir pela versão atual do GitHub?"):
            return NEGADO

    zip_url = f"https://codeload.github.com/{nome_completo}/zip/refs/heads/{ramo}"
    try:
        dados = _http_get(zip_url, MAX_DOWNLOAD, timeout=90)
    except urllib.error.HTTPError as e:
        if e.code == 404 and ramo != info.get("default_branch"):
            return f"[erro] o ramo '{ramo}' não existe. O ramo padrão é '{info.get('default_branch')}'."
        return f"[erro] falha ao baixar o projeto (erro {e.code})."
    except Exception as e:
        return f"[erro] falha ao baixar o projeto: {e}"

    if os.path.exists(destino):
        shutil.rmtree(destino)
    os.makedirs(destino)

    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            membros = z.infolist()
            if len(membros) > MAX_ARQUIVOS_ZIP:
                raise ValueError("arquivos demais no projeto")
            if sum(i.file_size for i in membros) > MAX_DESCOMPACTADO:
                raise ValueError("projeto grande demais depois de extraído")
            for item in membros:
                partes = item.filename.split("/", 1)       # o zip do GitHub tem uma pasta raiz
                rel = partes[1] if len(partes) > 1 else ""
                if not rel:
                    continue
                alvo = _resolver(destino, rel)             # bloqueia caminhos que fogem da pasta
                if item.is_dir():
                    os.makedirs(alvo, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(alvo), exist_ok=True)
                with z.open(item) as origem, open(alvo, "wb") as saida:
                    shutil.copyfileobj(origem, saida)
    except Exception as e:
        shutil.rmtree(destino, ignore_errors=True)
        return f"[erro] não consegui extrair o projeto com segurança: {e}"

    relatorio = _analisar_projeto(destino)
    try:
        with open(os.path.join(destino, ".jarvis_scan.txt"), "w", encoding="utf-8") as f:
            f.write(relatorio)
    except OSError:
        pass

    licenca = (info.get("license") or {}).get("spdx_id") or "não informada"
    readme = ""
    for nome in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        if os.path.isfile(os.path.join(destino, nome)):
            readme = _ler_inicio(os.path.join(destino, nome), 2000)
            break
    reqs = _ler_inicio(os.path.join(destino, "requirements.txt"), 1000)

    partes = [
        f"[sucesso] Projeto baixado em jarvis_workspace/importados/{pasta} (nenhum código foi executado nem instalado).",
        f"Repositório: {nome_completo} | linguagem: {info.get('language') or '?'} | "
        f"estrelas: {info.get('stargazers_count', 0)} | licença: {licenca} | "
        f"último push: {info.get('pushed_at', '?')}",
        f"Descrição: {info.get('description') or '(sem descrição)'}",
        "=== Estrutura ===", _estrutura(destino),
        "=== Dependências (requirements.txt) ===", reqs or "(não há requirements.txt)",
        "=== Relatório de segurança (heurístico) ===", relatorio,
        "=== README (início) ===", readme or "(sem README)",
        f"Para ler arquivos use ler_ficheiro com o caminho 'importados/{pasta}/<arquivo>'.",
    ]
    return "\n".join(partes)


def instalar_pacote(confirmar, pacote):
    pacote = (pacote or "").strip()
    if not PACOTE_OK.match(pacote):
        return "[erro] nome de pacote inválido."
    if not confirmar(
            f"Instalar o pacote '{pacote}' do PyPI no ambiente do JARVIS?\n\n"
            "Pacotes podem executar código durante a instalação e ficam disponíveis para todo o "
            "programa. Confira se o nome está exatamente certo (cuidado com nomes parecidos com "
            "pacotes famosos)."):
        return NEGADO
    try:
        r = subprocess.run(
            [_python_exe(), "-m", "pip", "install", "--disable-pip-version-check", pacote],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_PIP, env=_env_sem_chaves(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return f"[erro] a instalação passou de {TIMEOUT_PIP} s e foi interrompida."
    importlib.invalidate_caches()
    saida = (r.stdout + "\n" + r.stderr).strip()
    if r.returncode == 0:
        return f"[sucesso] '{pacote}' instalado.\n{saida[-600:]}"
    return f"[erro] a instalação falhou:\n{saida[-1200:]}"


def remover_projeto_importado(confirmar, nome):
    destino = _resolver(IMPORTADOS, nome)
    if destino == os.path.realpath(IMPORTADOS) or not os.path.isdir(destino):
        return "[erro] projeto não encontrado em importados."
    if not confirmar(f"Apagar o projeto importado '{nome}'? Plugins que dependem dele deixam de funcionar."):
        return NEGADO
    shutil.rmtree(destino)
    return f"[sucesso] projeto '{nome}' removido."


# ---------------- plugins ----------------
def _validar_plugin(codigo):
    try:
        arvore = ast.parse(codigo)
    except SyntaxError as e:
        return f"erro de sintaxe na linha {e.lineno}: {e.msg}"
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name == "handle" and len(no.args.args) >= 1:
            return None
    return "o plugin precisa definir a função handle(texto) no nível principal do arquivo"


def _carregar(arquivo):
    nome = "jarvis_plugin_" + os.path.splitext(os.path.basename(arquivo))[0]
    spec = importlib.util.spec_from_file_location(nome, arquivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _aviso_importados(codigo):
    """Se o plugin usa código baixado da internet, o pedido de autorização mostra um alerta."""
    mencionados = []
    try:
        for pasta in sorted(os.listdir(IMPORTADOS)):
            if pasta in codigo:
                mencionados.append(pasta)
    except OSError:
        pass
    if not mencionados and "importados" not in codigo:
        return ""
    linhas = ["⚠ ATENÇÃO: este plugin EXECUTA código de projeto baixado da internet."]
    for pasta in mencionados:
        resumo = "(sem relatório de segurança)"
        rel = os.path.join(IMPORTADOS, pasta, ".jarvis_scan.txt")
        if os.path.isfile(rel):
            resumo = _ler_inicio(rel, 400).split("\n")[0]
        linhas.append(f"- {pasta}: {resumo}")
    linhas.append("Autorize só se leu o resumo do que o projeto faz e confia nele.")
    return "\n".join(linhas) + "\n\n"


def criar_plugin(confirmar, nome, codigo):
    nome = nome.strip().lower()
    if nome.endswith(".py"):
        nome = nome[:-3]
    if not NOME_PLUGIN.match(nome):
        return "[erro] nome inválido: use letras minúsculas, números e _ (ex.: modo_cinema)."
    if len(codigo) > MAX_ARQUIVO:
        return "[erro] plugin grande demais."
    problema = _validar_plugin(codigo)
    if problema:
        return f"[erro] {problema}"

    destino = os.path.join(PLUGINS, nome + ".py")
    existe = os.path.exists(destino)
    previa = codigo if len(codigo) <= 4000 else codigo[:4000] + "\n[... código cortado na prévia]"
    verbo = "ATUALIZAR" if existe else "CRIAR"
    if not confirmar(f"{verbo} o plugin '{nome}'? Ele passa a rodar dentro do JARVIS, "
                     f"com as suas permissões.\n\n{_aviso_importados(codigo)}{previa}"):
        return NEGADO

    copia = _guardar_copia(destino) if existe else None
    with open(destino, "w", encoding="utf-8") as f:
        f.write(codigo)
    try:
        _carregar(destino)   # teste: o plugin precisa ao menos carregar sem erro
    except BaseException as e:
        if copia:
            shutil.copy2(copia, destino)
        else:
            os.remove(destino)
        return f"[erro] o plugin falhou ao carregar e foi desfeito: {e!r}"
    return f"[sucesso] plugin '{nome}' ativo. Já vale para os próximos comandos, sem reiniciar."


def remover_plugin(confirmar, nome):
    nome = nome.strip().lower().removesuffix(".py")
    destino = os.path.join(PLUGINS, nome + ".py")
    if not NOME_PLUGIN.match(nome) or not os.path.isfile(destino):
        return "[erro] plugin não encontrado."
    if not confirmar(f"Remover o plugin '{nome}'? (uma cópia fica em backups_jarvis)"):
        return NEGADO
    copia = _guardar_copia(destino)
    os.remove(destino)
    return f"[sucesso] plugin '{nome}' removido. Cópia em {os.path.relpath(copia, PROJETO)}."


def listar_plugins(confirmar):
    nomes = [os.path.basename(p)[:-3] for p in sorted(glob.glob(os.path.join(PLUGINS, "*.py")))]
    return "\n".join(nomes) or "(nenhum plugin instalado)"


def _chamar_plugin(arquivo, texto):
    """Roda um plugin com limite de tempo. Qualquer falha é registrada e ignorada."""
    nome = os.path.basename(arquivo)
    resultado = {}

    def alvo():
        try:
            modulo = _carregar(arquivo)
            fn = getattr(modulo, "handle", None)
            if callable(fn):
                resultado["resp"] = fn(texto)
        except BaseException as e:
            print(f"[plugin] {nome} falhou: {e!r}")

    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    t.join(TIMEOUT_PLUGIN)
    if t.is_alive():
        print(f"[plugin] {nome} passou de {TIMEOUT_PLUGIN} s e foi ignorado.")
        return None
    return resultado.get("resp")


def rodar_plugins(texto):
    """Chamado pelo main.py para cada comando que as ações normais não entenderam."""
    for arquivo in sorted(glob.glob(os.path.join(PLUGINS, "*.py"))):
        resp = _chamar_plugin(arquivo, texto)
        if resp:
            return str(resp)
    return None


# ---------------- backup do código ----------------
def backup_codigo(confirmar=None):
    """Zip só do código (.py, .md, .txt e plugins). Nunca inclui .env, .venv nem models."""
    os.makedirs(BACKUPS, exist_ok=True)
    nome = datetime.now().strftime("codigo_%Y%m%d_%H%M%S.zip")
    destino = os.path.join(BACKUPS, nome)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for padrao in ("*.py", "*.md", "*.txt"):
            for arq in glob.glob(os.path.join(PROJETO, padrao)):
                z.write(arq, os.path.basename(arq))
        for arq in glob.glob(os.path.join(PLUGINS, "*.py")):
            z.write(arq, "plugins/" + os.path.basename(arq))
    antigos = sorted(glob.glob(os.path.join(BACKUPS, "codigo_*.zip")))
    for velho in antigos[:-MANTER_BACKUPS]:
        os.remove(velho)
    return f"[sucesso] backup criado: backups_jarvis/{nome}"


# ---------------- registro das ferramentas ----------------
_FUNCOES = {
    "listar_diretorio": listar_diretorio,
    "ler_ficheiro": ler_ficheiro,
    "criar_ficheiro": criar_ficheiro,
    "excluir_ficheiro": excluir_ficheiro,
    "executar_python": executar_python,
    "baixar_projeto_github": baixar_projeto_github,
    "instalar_pacote": instalar_pacote,
    "remover_projeto_importado": remover_projeto_importado,
    "criar_plugin": criar_plugin,
    "remover_plugin": remover_plugin,
    "listar_plugins": listar_plugins,
    "backup_codigo": backup_codigo,
}


def executar(nome, args, confirmar):
    """Executa uma ferramenta pedida pelo modelo. Sempre devolve texto, nunca levanta erro."""
    func = _FUNCOES.get(nome)
    if func is None:
        return f"[erro] ferramenta desconhecida: {nome}"
    if not isinstance(args, dict):
        args = {}
    try:
        return _cortar(func(confirmar, **args))
    except TypeError as e:
        return f"[erro] argumentos inválidos: {e}"
    except Exception as e:
        return f"[erro] {e}"


def _t(nome, descricao, props=None, obrigatorios=None):
    return {"type": "function", "function": {
        "name": nome, "description": descricao,
        "parameters": {"type": "object", "properties": props or {},
                       "required": obrigatorios or []}}}


_S = {"type": "string"}

ESQUEMA = [
    _t("listar_diretorio",
       "Lista arquivos e pastas dentro de jarvis_workspace (inclui importados/).",
       {"caminho": {**_S, "description": "Subpasta (padrão '.')"}}),
    _t("ler_ficheiro",
       "Lê um arquivo de jarvis_workspace (inclusive importados/<projeto>/...), ou um destes arquivos do "
       "projeto (somente leitura): main.py, acoes.py, ferramentas.py, requirements.txt, README.md, "
       "jarvis.log, plugins/<nome>.py. Arquivos grandes vêm em partes: use 'inicio' para continuar.",
       {"caminho": _S, "inicio": {"type": "integer", "description": "Posição inicial (padrão 0)"}},
       ["caminho"]),
    _t("criar_ficheiro",
       "Cria ou sobrescreve um arquivo de texto dentro de jarvis_workspace. Sobrescrever pede autorização.",
       {"caminho": _S, "conteudo": _S}, ["caminho", "conteudo"]),
    _t("excluir_ficheiro",
       "Apaga um arquivo de jarvis_workspace. Pede autorização do senhor.",
       {"caminho": _S}, ["caminho"]),
    _t("executar_python",
       "Executa um script Python (limite de 20 s) dentro de jarvis_workspace e devolve a saída. "
       "Pede autorização do senhor.",
       {"codigo": _S}, ["codigo"]),
    _t("baixar_projeto_github",
       "Baixa um repositório PÚBLICO do GitHub (zip) para jarvis_workspace/importados/ sem executar nada, "
       "e devolve estrutura, dependências, relatório de segurança e início do README. Use quando o senhor "
       "enviar um link do GitHub.",
       {"url": _S}, ["url"]),
    _t("instalar_pacote",
       "Instala UM pacote do PyPI no ambiente do JARVIS (pip install). Pede autorização do senhor a cada pacote.",
       {"pacote": {**_S, "description": "Nome do pacote, ex.: 'pyperclip' ou 'requests==2.32.3'"}},
       ["pacote"]),
    _t("remover_projeto_importado",
       "Apaga um projeto da pasta importados. Pede autorização do senhor.",
       {"nome": {**_S, "description": "Nome da pasta em importados"}}, ["nome"]),
    _t("criar_plugin",
       "Cria ou atualiza um plugin que dá uma nova habilidade ao JARVIS por voz. O arquivo precisa "
       "definir def handle(texto): que recebe o comando (minúsculo) e devolve a frase que o JARVIS deve "
       "falar, ou None se o comando não for do plugin. Pede autorização do senhor.",
       {"nome": {**_S, "description": "letras minúsculas, números e _"}, "codigo": _S},
       ["nome", "codigo"]),
    _t("remover_plugin", "Remove um plugin (guarda uma cópia). Pede autorização.",
       {"nome": _S}, ["nome"]),
    _t("listar_plugins", "Lista os plugins instalados."),
    _t("backup_codigo",
       "Cria um backup zip do código do JARVIS (sem .env, .venv ou models) em backups_jarvis."),
]
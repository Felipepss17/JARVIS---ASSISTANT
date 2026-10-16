"""Busca local por nome em pastas pessoais selecionadas; nunca lê o conteúdo dos arquivos."""
import difflib
import os
import re
import unicodedata

EXTENSOES_DOCUMENTO = {
    ".doc", ".docx", ".odt", ".rtf", ".pdf", ".txt", ".md",
    ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp",
}
IGNORAR = {".git", ".venv", "node_modules", "__pycache__", "appdata", "windows"}
MAX_PASTAS = 2500
MAX_RESULTADOS = 5
STOP_WORDS = {"abre", "abrir", "abra", "encontre", "encontrar", "localize", "localizar",
              "ache", "achar", "busque", "buscar", "procure", "procurar", "arquivo",
              "documento", "trabalho", "o", "a", "os", "as", "um", "uma", "de", "do",
              "da", "dos", "das", "em", "no", "na", "para", "por", "meu", "minha"}


def normalizar(texto):
    texto = unicodedata.normalize("NFD", str(texto).casefold())
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def get_search_roots():
    """Roots from env override defaults; never searches the whole drive."""
    configured = os.environ.get("JARVIS_FILE_SEARCH_DIRS", "").strip()
    home = os.path.expanduser("~")
    if configured:
        roots = [os.path.expandvars(os.path.expanduser(p.strip().strip('"')))
                 for p in configured.split(os.pathsep) if p.strip()]
    else:
        roots = [os.path.join(home, name) for name in ("Documents", "Desktop", "Downloads")]
        # Windows may redirect known folders to OneDrive/localized locations.
        roots.append(os.path.join(home, "OneDrive", "Documents"))
    unique = []
    seen = set()
    for root in roots:
        real = os.path.realpath(root)
        key = os.path.normcase(real)
        if key not in seen and os.path.isdir(real):
            unique.append(real)
            seen.add(key)
    return unique


def _query_tokens(query):
    return {word for word in normalizar(query).split() if word not in STOP_WORDS and len(word) > 1}


def _score(query_tokens, label):
    candidate = normalizar(label)
    candidate_tokens = set(candidate.split())
    if not candidate_tokens or not query_tokens:
        return 0.0
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
    joined_query = " ".join(sorted(query_tokens))
    exact_prefix = 1.0 if all(token in candidate_tokens for token in query_tokens) else 0.0
    fuzzy = difflib.SequenceMatcher(None, joined_query, candidate).ratio()
    return max(overlap * 0.82 + exact_prefix * 0.18, fuzzy * 0.72)


def search_files(query, roots=None, limit=MAX_RESULTADOS):
    tokens = _query_tokens(query)
    if not tokens:
        return []
    roots = roots if roots is not None else get_search_roots()
    ranked = []
    dirs_seen = 0
    for root in roots:
        root = os.path.realpath(root)
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs_seen += 1
            dirs[:] = [d for d in dirs if d.casefold() not in IGNORAR
                       and not d.startswith(".") and not os.path.islink(os.path.join(folder, d))]
            if dirs_seen > MAX_PASTAS:
                break
            for name in files:
                if os.path.splitext(name)[1].casefold() not in EXTENSOES_DOCUMENTO:
                    continue
                path = os.path.join(folder, name)
                if os.path.islink(path):
                    continue
                relative = os.path.relpath(path, root)
                score = _score(tokens, os.path.splitext(name)[0])
                # Parent folder can disambiguate similar filenames without dominating the name.
                score = max(score, _score(tokens, relative.replace(os.sep, " ")) * 0.92)
                if score >= 0.42:
                    ranked.append((score, path))
        if dirs_seen > MAX_PASTAS:
            break
    ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1].casefold()))
    return ranked[:max(1, int(limit))]


def open_best_match(query, opener=None, roots=None):
    matches = search_files(query, roots=roots)
    if not matches:
        return None
    best_score, best_path = matches[0]
    # Avoid opening a guess when multiple candidates are similarly plausible.
    if best_score < 0.54:
        return "low_confidence", matches[:3]
    if len(matches) > 1 and matches[1][0] >= best_score - 0.09:
        return "ambiguous", matches[:3]
    if opener is None:
        opener = getattr(os, "startfile", None)
    if opener is None:
        return "unsupported", best_path
    opener(best_path)
    return "opened", best_path

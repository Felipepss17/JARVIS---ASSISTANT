"""Memória pessoal local do J.A.R.V.I.S., armazenada em SQLite."""
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from .settings import PROJECT_ROOT

MEMORY_DIR = os.path.join(PROJECT_ROOT, "jarvis_workspace")
MEMORY_DB = os.path.join(MEMORY_DIR, "memoria.sqlite3")
MAX_MEMORIES = 100
MAX_MEMORY_LENGTH = 500
CONFIRM_CLEAR_ALL = "__CONFIRMAR_APAGAR_MEMORIAS__"


def normalize(text):
    text = unicodedata.normalize("NFD", str(text).casefold())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


class MemoryStore:
    """Armazena somente fatos que o usuário pede explicitamente para lembrar."""

    def __init__(self, db_path=MEMORY_DB):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        content TEXT NOT NULL,
                        normalized_content TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    )
                """)
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _category(content):
        text = normalize(content)
        if any(term in text for term in ("prefiro", "gosto", "nao gosto", "me agrada")):
            return "preferência"
        if any(term in text for term in ("meu nome", "me chame", "sou o ", "sou a ")):
            return "pessoal"
        return "contexto"

    def add(self, content):
        content = re.sub(r"\s+", " ", str(content)).strip(" \t\r\n.,!?;:")
        if not content:
            raise ValueError("Diga o que devo guardar na memória.")
        if len(content) > MAX_MEMORY_LENGTH:
            raise ValueError(f"A memória deve ter no máximo {MAX_MEMORY_LENGTH} caracteres.")

        normalized = normalize(content)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM memories WHERE normalized_content = ?", (normalized,)
            ).fetchone()
            if existing:
                return "Essa informação já está guardada, senhor."
            count = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if count >= MAX_MEMORIES:
                raise ValueError("A memória está cheia. Apague alguma informação antes de adicionar outra.")
            connection.execute(
                "INSERT INTO memories(category, content, normalized_content, created_at) VALUES (?, ?, ?, ?)",
                (self._category(content), content, normalized, datetime.now(timezone.utc).isoformat()),
            )
        return "Anotado na memória local, senhor."

    def list_all(self, limit=MAX_MEMORIES):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, category, content, created_at FROM memories ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), MAX_MEMORIES)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_matching(self, query):
        needle = normalize(query)
        if not needle:
            return []
        rows = self.list_all()
        matches = [row for row in rows if needle in normalize(row["content"])]
        if len(matches) == 1:
            with self._connect() as connection:
                connection.execute("DELETE FROM memories WHERE id = ?", (matches[0]["id"],))
        elif len(matches) > 1:
            return matches
        return matches

    def clear(self):
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM memories")
            return cursor.rowcount

    def prompt_context(self, limit=20, max_chars=3000):
        rows = self.list_all(limit=limit)
        lines = []
        total = 0
        for row in reversed(rows):
            line = f"- [{row['category']}] {row['content']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)


_store = MemoryStore()


def is_memory_command(text):
    text = normalize(text)
    patterns = (
        r"^(?:o que voce (?:lembra|sabe) (?:de|sobre) mim|(?:listar|mostrar|ver|consultar)(?: minhas?)? memorias?)\??$",
        r"^(?:lembre(?:-se)?|guarde|memorize|salve)(?: de)?(?: que)?\s+.+$",
        r"^(?:esqueca|apague|delete|remova|limpe|limpar)\b.*(?:memor\w+|tudo que voce sabe sobre mim)$",
        r"^(?:esqueca|apague|delete|remova)(?: a)? memoria(?: sobre| de| que)?\s+.+$",
        r"^esqueca\s+.+$",
    )
    return any(re.match(pattern, text) for pattern in patterns)


def handle_command(text, store=None):
    """Executa comandos locais de adicionar, consultar e apagar memórias."""
    store = store or _store
    raw_text = re.sub(r"\s+", " ", str(text)).strip(" ?.!;,:")
    text = normalize(raw_text).strip(" ?.!;,:")

    if re.search(r"\b(?:todas as memorias|todas minhas memorias|tudo que voce sabe sobre mim)\b", text):
        return CONFIRM_CLEAR_ALL

    if re.match(
        r"^(?:o que voce (?:lembra|sabe) (?:de|sobre) mim|(?:listar|mostrar|ver|consultar).*\bmemorias?)$",
        text,
    ):
        rows = store.list_all(limit=20)
        if not rows:
            return "Ainda não guardei nenhuma informação, senhor."
        items = [f"{row['id']}. [{row['category']}] {row['content']}" for row in rows]
        suffix = "\nMostrando as 20 mais recentes." if len(store.list_all()) > len(rows) else ""
        return "Estas são as informações guardadas localmente:\n" + "\n".join(items) + suffix

    add_match = re.match(r"^(?:lembre(?:-se)?|guarde|memorize|salve)(?: de)?(?: que)?\s+(.+)$", raw_text, re.I)
    if add_match:
        try:
            return store.add(add_match.group(1))
        except ValueError as error:
            return str(error)

    delete_all = re.match(
        r"^(?:esqueca|apague|delete|remova|limpe|limpar)(?: a| o| todas? as?| tudo)?(?: minhas?)? memorias(?: sobre mim)?$",
        text,
    )
    if delete_all:
        return CONFIRM_CLEAR_ALL

    delete_match = re.match(
        r"^(?:esqueca|apague|delete|remova)(?: a)? memoria(?: sobre| de| que)?\s+(.+)$", text
    )
    if not delete_match:
        delete_match = re.match(r"^(?:esqueca|apague|delete|remova)\s+(.+)$", text)
    if delete_match:
        query = re.sub(r"^(?:de )?que\s+", "", delete_match.group(1))
        matches = store.delete_matching(query)
        if not matches:
            return "Não encontrei essa informação na memória, senhor."
        if len(matches) > 1:
            options = "\n".join(f"{row['id']}. {row['content']}" for row in matches[:10])
            return "Encontrei mais de uma informação. Diga 'esqueça' seguido de um trecho mais específico:\n" + options
        return "Apaguei essa informação da memória, senhor."

    return None


def clear_all_memories():
    return _store.clear()


def prompt_context():
    return _store.prompt_context()

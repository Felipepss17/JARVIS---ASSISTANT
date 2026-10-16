"""Caixa local de ideias e tarefas para organizar depois."""
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from .settings import PROJECT_ROOT

INBOX_DB = os.path.join(PROJECT_ROOT, "jarvis_workspace", "caixa_ideias.sqlite3")
MAX_ITEMS = 500
MAX_CONTENT_LENGTH = 500


def normalize(text):
    value = unicodedata.normalize("NFD", str(text).casefold())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", value).strip(" ?.!;,:\t\r\n")


class IdeaInbox:
    def __init__(self, db_path=INBOX_DB):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS inbox_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind TEXT NOT NULL CHECK(kind IN ('ideia', 'tarefa')),
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        completed_at TEXT
                    )
                """)
                yield connection
        finally:
            connection.close()

    def add(self, kind, content):
        kind = normalize(kind)
        content = re.sub(r"\s+", " ", str(content)).strip(" \t\r\n.,!?;:")
        if kind not in {"ideia", "tarefa"}:
            raise ValueError("O item deve ser uma ideia ou uma tarefa.")
        if not content:
            raise ValueError("Diga o que devo anotar.")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(f"A anotação deve ter no máximo {MAX_CONTENT_LENGTH} caracteres.")
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM inbox_items").fetchone()[0]
            if count >= MAX_ITEMS:
                raise ValueError("A caixa está cheia. Apague alguns itens antes de adicionar outros.")
            cursor = connection.execute(
                "INSERT INTO inbox_items(kind, content, created_at) VALUES (?, ?, ?)",
                (kind, content, datetime.now(timezone.utc).isoformat()),
            )
            return cursor.lastrowid

    def list_items(self, kind=None, include_completed=False, limit=30):
        clauses = []
        params = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if not include_completed:
            clauses.append("completed_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 100)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, kind, content, created_at, completed_at FROM inbox_items" + where
                + " ORDER BY id DESC LIMIT ?", params,
            ).fetchall()
        return [dict(row) for row in rows]

    def complete(self, item_id):
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE inbox_items SET completed_at = ? WHERE id = ? AND completed_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), int(item_id)),
            )
            return cursor.rowcount > 0

    def delete(self, item_id):
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM inbox_items WHERE id = ?", (int(item_id),))
            return cursor.rowcount > 0


_store = IdeaInbox()
_ADD = re.compile(
    r"^(?:anote|anota|anotar|guarde|guarda|guardar|registre|registra|adicionar|adicione|"
    r"adiciona|coloque|coloca|salve|salva)\s+(?:(?:uma?|a)\s+)?(ideia|tarefa)"
    r"\s*(?:(?:de|para|que)\s*)?[:,-]?\s*(.*)$", re.I,
)
_ADD_PREFIX = re.compile(
    r"^(?:anote|anota|anotar|guarde|guarda|guardar|registre|registra|adicionar|adicione|"
    r"adiciona|coloque|coloca|salve|salva)\s+(?:(?:uma?|a)\s+)?(?:ideia|tarefa)\b"
)


def is_inbox_command(text):
    value = normalize(text)
    if _ADD_PREFIX.match(value):
        return True
    return bool(
        re.match(r"^(?:caixa de (?:ideias|tarefas)|minhas? (?:ideias|tarefas)|"
                 r"(?:listar|mostrar|ver|consultar) (?:minhas? )?(?:ideias|tarefas)|"
                 r"organizar caixa de ideias|organize caixa de ideias)$", value)
        or re.match(r"^(?:conclua|concluir|finalize|finalizar|terminei|marque como concluida?)\s+"
                    r"(?:a )?(?:ideia|tarefa)\s+#?\d+$", value)
        or re.match(r"^(?:apague|delete|remova|exclua)\s+(?:a )?(?:ideia|tarefa)\s+#?\d+$", value)
    )


def handle_command(text, store=None):
    store = store or _store
    raw = re.sub(r"\s+", " ", str(text)).strip(" ?.!;,:\t\r\n")
    value = normalize(raw)
    match = _ADD.match(raw)
    if match:
        kind, content = match.groups()
        try:
            item_id = store.add(normalize(kind), content)
        except ValueError as error:
            return str(error)
        return f"Anotei {normalize(kind)} #{item_id}: {content.strip()}, senhor."

    listing = re.match(r"^(?:caixa de (ideias|tarefas)|minhas? (ideias|tarefas)|"
                       r"(?:listar|mostrar|ver|consultar) (?:minhas? )?(ideias|tarefas)|"
                       r"organizar caixa de ideias|organize caixa de ideias)$", value)
    if listing:
        selected = next((group for group in listing.groups() if group), None)
        kind = selected[:-1] if selected in {"ideias", "tarefas"} else None
        rows = store.list_items(kind=kind, limit=20)
        if not rows:
            return "A caixa está vazia por enquanto, senhor."
        lines = [f"{row['id']}. [{row['kind'].capitalize()}] {row['content']}" for row in rows]
        return "Sua caixa de ideias e tarefas:\n" + "\n".join(lines)

    done = re.match(r"^(?:conclua|concluir|finalize|finalizar|terminei|marque como concluida?)\s+"
                    r"(?:a )?(?:ideia|tarefa)\s+#?(\d+)$", value)
    if done:
        return ("Marquei como concluído, senhor." if store.complete(int(done.group(1)))
                else "Não encontrei esse item pendente, senhor.")

    delete = re.match(r"^(?:apague|delete|remova|exclua)\s+(?:a )?(?:ideia|tarefa)\s+#?(\d+)$", value)
    if delete:
        return ("Removi o item da caixa, senhor." if store.delete(int(delete.group(1)))
                else "Não encontrei esse item na caixa, senhor.")
    return None

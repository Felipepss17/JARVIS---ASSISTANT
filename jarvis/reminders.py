"""Lembretes locais em SQLite, com datas interpretadas no fuso do Windows."""
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .settings import PROJECT_ROOT

REMINDER_DB = os.path.join(PROJECT_ROOT, "jarvis_workspace", "lembretes.sqlite3")
CONFIRM_PREFIX = "__CONFIRMAR_LEMBRETE__:"


def normalize(text):
    value = unicodedata.normalize("NFD", str(text).casefold())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", value).strip()


class ReminderStore:
    def __init__(self, db_path=REMINDER_DB):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        due_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        notified INTEGER NOT NULL DEFAULT 0
                    )
                """)
                yield connection
        finally:
            connection.close()

    def add(self, title, due_at):
        now = datetime.now(timezone.utc)
        if due_at.tzinfo is None:
            raise ValueError("O horário do lembrete precisa incluir o fuso local.")
        if due_at <= now.astimezone(due_at.tzinfo):
            raise ValueError("Esse horário já passou. Diga um horário futuro.")
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO reminders(title, due_at, created_at) VALUES (?, ?, ?)",
                (title, due_at.astimezone(timezone.utc).isoformat(), now.isoformat()),
            )
            return cursor.lastrowid

    def list_pending(self, limit=20):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, due_at FROM reminders WHERE notified = 0 ORDER BY due_at LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, reminder_id):
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM reminders WHERE id = ?", (int(reminder_id),))
            return cursor.rowcount > 0

    def pop_due(self, now=None):
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, due_at FROM reminders WHERE notified = 0 AND due_at <= ? ORDER BY due_at",
                (now_utc,),
            ).fetchall()
            if rows:
                connection.executemany(
                    "UPDATE reminders SET notified = 1 WHERE id = ?", [(row["id"],) for row in rows]
                )
        return [dict(row) for row in rows]


_store = ReminderStore()


def is_reminder_command(text):
    value = normalize(text)
    return bool(
        re.match(r"^(?:jarvis[, ]+)?(?:me lembre|me lembra|lembre-me|lembra-me|crie um lembrete|criar lembrete|adicione um lembrete|adicionar lembrete)\b", value)
        or re.match(r"^(?:listar|mostrar|ver|consultar)(?: meus?)? lembretes?\b", value)
        or re.match(r"^(?:meus lembretes|quais sao meus lembretes)\b", value)
        or re.match(r"^(?:cancele|apague|delete|remova) lembrete\s+#?\d+\b", value)
    )


def _parse_due(text, now=None):
    now = now or datetime.now().astimezone()
    normalized = normalize(text)
    due = None

    relative = re.search(r"\b(?:daqui a|em)\s+(\d+)\s+(minutos?|horas?|dias?)\b", normalized)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        delta = timedelta(minutes=amount) if unit.startswith("minuto") else (
            timedelta(hours=amount) if unit.startswith("hora") else timedelta(days=amount)
        )
        due = now + delta
        normalized = normalized[:relative.start()] + " " + normalized[relative.end():]
    else:
        date_match = re.search(r"\b(hoje|amanha)\b", normalized)
        day_offset = 1 if date_match and date_match.group(1) == "amanha" else 0
        if date_match:
            normalized = normalized[:date_match.start()] + " " + normalized[date_match.end():]

        time_match = re.search(
            r"\b(?:as|a|para|por volta das)\s*(\d{1,2})(?:(?::|h)\s*(\d{2}))?h?\s*(da manha|da tarde|da noite)?\b",
            normalized,
        )
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            period = time_match.group(3) or ""
            if period in ("da tarde", "da noite") and 1 <= hour <= 11:
                hour += 12
            if hour > 23 or minute > 59:
                return None, "Esse horário não é válido. Diga, por exemplo, às 19h ou às 19:30."
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
            if day_offset == 0 and due <= now:
                due += timedelta(days=1)
            normalized = normalized[:time_match.start()] + " " + normalized[time_match.end():]

    title = re.sub(
        r"^(?:jarvis[, ]+)?(?:me lembre|me lembra|lembre-me|lembra-me|crie um lembrete|criar lembrete|adicione um lembrete|adicionar lembrete)\s*(?:de|para|que)?\s*",
        "", normalized,
    )
    title = re.sub(r"\b(?:por favor|amanha|hoje|as|a|para|da manha|da tarde|da noite)\b", " ", title)
    title = re.sub(r"\b\d{1,2}(?::\d{2})?h?\b", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" ,.!?;:")
    if due is None:
        return None, "Não identifiquei o horário. Tente: 'me lembre de estudar amanhã às 19h'."
    if not title:
        return None, "O que devo lembrar? Diga, por exemplo: 'me lembre de estudar amanhã às 19h'."
    return (title, due), None


def format_due(value):
    due = datetime.fromisoformat(value)
    local = due.astimezone()
    return local.strftime("%d/%m/%Y às %H:%M")


def handle_command(text, store=None, now=None):
    store = store or _store
    normalized = normalize(text).strip(" ?.!;,: ")

    delete_match = re.match(r"^(?:cancele|apague|delete|remova) lembrete\s+#?(\d+)$", normalized)
    if delete_match:
        return ("Lembrete cancelado." if store.delete(int(delete_match.group(1)))
                else "Não encontrei esse lembrete.")

    if re.match(r"^(?:listar|mostrar|ver|consultar)(?: meus?)? lembretes?$|^(?:meus lembretes|quais sao meus lembretes)$", normalized):
        reminders = store.list_pending()
        if not reminders:
            return "Você não tem lembretes pendentes."
        return "Seus próximos lembretes:\n" + "\n".join(
            f"{item['id']}. {item['title']} — {format_due(item['due_at'])}" for item in reminders
        )

    parsed, error = _parse_due(text, now)
    if error:
        return error
    title, due = parsed
    return CONFIRM_PREFIX + json.dumps({"title": title, "due_at": due.isoformat()}, ensure_ascii=False)


def confirm_reminder(proposal, store=None):
    store = store or _store
    due = datetime.fromisoformat(proposal["due_at"])
    reminder_id = store.add(proposal["title"], due)
    return f"Lembrete {reminder_id} salvo para {format_due(due.isoformat())}: {proposal['title']}."


def due_reminders(store=None):
    store = store or _store
    return store.pop_due()

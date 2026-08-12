"""
Юрга-Подработка — Telegram-бот для подработок
Production version.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Iterable, List, Optional, Tuple

import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    _GSPREAD_AVAILABLE = True
except ImportError:
    _GSPREAD_AVAILABLE = False


class Role(str, Enum):
    WORKER = "rabotnik"
    CUSTOMER = "zakazchik"
    MODERATOR = "moderator"


class OrderStatus(str, Enum):
    OPEN = "open"
    READY_TO_PAY = "ready_to_pay"
    PAID = "paid"
    WORKING = "working"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_PAYOUT = "waiting_payout"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Config:
    token: str
    moderator_ids: Tuple[int, ...]
    sbp_phone: str
    commission_per_hour: int
    price_per_hour: int
    bot_name: str
    db_path: str = "rabota.db"
    google_credentials: Optional[Dict[str, Any]] = None
    spreadsheet_id: Optional[str] = None
    log_level: str = "INFO"
    state_ttl_minutes: int = 30

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("TOKEN")
        if not token:
            raise ValueError("TOKEN не задан в окружении!")

        mod_raw = os.getenv("MODERATOR_IDS", "8746212340")
        try:
            mod_ids = tuple(int(x.strip()) for x in mod_raw.split(",") if x.strip())
        except ValueError as e:
            raise ValueError(f"MODERATOR_IDS: {e}") from e

        try:
            commission = int(os.getenv("COMMISSION_PER_HOUR", "50"))
            price = int(os.getenv("PRICE_PER_HOUR", "500"))
        except ValueError as e:
            raise ValueError(f"COMMISSION/PRICE: {e}") from e

        google_creds = None
        creds_json = os.getenv("GOOGLE_CREDENTIALS")
        if creds_json:
            try:
                google_creds = json.loads(creds_json)
            except json.JSONDecodeError as e:
                logging.getLogger(__name__).warning(f"GOOGLE_CREDENTIALS: {e}")

        return cls(
            token=token,
            moderator_ids=mod_ids,
            sbp_phone=os.getenv("SBP_PHONE", "+7XXXXXXXXXX"),
            commission_per_hour=commission,
            price_per_hour=price,
            bot_name=os.getenv("BOT_NAME", "Юрга-Подработка"),
            db_path=os.getenv("DB_PATH", "rabota.db"),
            google_credentials=google_creds,
            spreadsheet_id=os.getenv("SPREADSHEET_ID"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )


def setup_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("yurga")
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        "bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("oauth2client").setLevel(logging.WARNING)

    return logger


_PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{9,18}$")
_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z\s\-\.]{2,100}$")


def validate_phone(phone: str) -> bool:
    return bool(phone and _PHONE_RE.match(phone.strip()))


def validate_name(name: str) -> bool:
    return bool(name and _NAME_RE.match(name.strip()))


def validate_initials(initials: str) -> bool:
    if not initials:
        return False
    stripped = initials.strip()
    return 2 <= len(stripped) <= 60


def validate_positive_int(value: Any, max_value: int = 10_000) -> Optional[int]:
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    return n if 0 < n <= max_value else None


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[Tuple[int, str], List[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: int, action: str, max_per_minute: int = 30) -> bool:
        now = time.time()
        key = (user_id, action)
        with self._lock:
            bucket = self._buckets.setdefault(key, [])
            cutoff = now - 60
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= max_per_minute:
                return False
            bucket.append(now)
            return True


USER_UPDATABLE_FIELDS = frozenset({
    "name", "phone", "bank", "initials", "role", "rating", "customer_rating",
    "on_shift", "agreement_accepted", "blocked", "notify",
})


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init_lock = threading.Lock()
        self._initialized = False
        self._ensure_schema()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self, max_retries: int = 5):
        for attempt in range(max_retries):
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
                conn.close()
                return
            except sqlite3.OperationalError as e:
                conn.close()
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(random.uniform(0.1, 0.5) * (attempt + 1))
                    continue
                raise
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                conn.close()
                raise

    def _ensure_schema(self) -> None:
        with self._init_lock:
            if self._initialized:
                return
            with self.connection() as conn:
                conn.executescript(SCHEMA_SQL)
            self._initialized = True


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    name TEXT,
    phone TEXT,
    bank TEXT,
    initials TEXT,
    role TEXT CHECK(role IN ('rabotnik','zakazchik','moderator')),
    rating INTEGER DEFAULT 10,
    customer_rating INTEGER DEFAULT 10,
    on_shift INTEGER DEFAULT 1,
    agreement_accepted INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    notify INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    last_active_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zakazchik_id INTEGER NOT NULL REFERENCES users(id),
    zakazchik_name TEXT,
    address TEXT NOT NULL,
    work_description TEXT NOT NULL,
    hours INTEGER NOT NULL CHECK(hours > 0),
    people INTEGER NOT NULL CHECK(people > 0),
    total_sum INTEGER NOT NULL,
    commission INTEGER NOT NULL,
    payout_per_person INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    photo_file_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    paid_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    payout INTEGER NOT NULL,
    confirmed INTEGER DEFAULT 0,
    confirmed_at TEXT,
    photo_file_id TEXT,
    UNIQUE(order_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL REFERENCES users(id),
    to_user_id INTEGER NOT NULL REFERENCES users(id),
    order_id INTEGER REFERENCES orders(id),
    text TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    read INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS temp_states (
    user_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS moderator_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moderator_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_user_id INTEGER,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_blocked ON users(blocked);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_zakazchik ON orders(zakazchik_id);
CREATE INDEX IF NOT EXISTS idx_assignments_order ON assignments(order_id);
CREATE INDEX IF NOT EXISTS idx_assignments_user ON assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_user_id, read);
CREATE INDEX IF NOT EXISTS idx_states_expires ON temp_states(expires_at);
"""


@dataclass
class UserDTO:
    id: int
    telegram_id: int
    name: Optional[str] = None
    phone: Optional[str] = None
    bank: Optional[str] = None
    initials: Optional[str] = None
    role: Optional[str] = None
    rating: int = 10
    customer_rating: int = 10
    on_shift: int = 1
    agreement_accepted: int = 0
    blocked: int = 0
    notify: int = 1
    created_at: Optional[str] = None
    last_active_at: Optional[str] = None


def _row_to_user(row: sqlite3.Row) -> Optional[UserDTO]:
    if row is None:
        return None
    return UserDTO(**dict(row))


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_by_telegram(self, tg_id: int) -> Optional[UserDTO]:
        with self.db.connection() as c:
            row = c.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (tg_id,)
            ).fetchone()
        return _row_to_user(row)

    def get_by_id(self, user_id: int) -> Optional[UserDTO]:
        with self.db.connection() as c:
            row = c.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return _row_to_user(row)

    def get_by_phone(self, phone: str) -> List[UserDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM users WHERE phone = ?", (phone,)
            ).fetchall()
        return [_row_to_user(r) for r in rows if r]

    def ensure(self, tg_id: int) -> UserDTO:
        with self.db.transaction() as c:
            c.execute(
                "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (tg_id,)
            )
            row = c.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (tg_id,)
            ).fetchone()
        return _row_to_user(row)

    def update_field(self, tg_id: int, field_name: str, value: Any) -> bool:
        if field_name not in USER_UPDATABLE_FIELDS:
            raise ValueError(f"Поле '{field_name}' не разрешено для обновления")
        with self.db.transaction() as c:
            c.execute(
                f"UPDATE users SET {field_name} = ?, last_active_at = datetime('now') "
                f"WHERE telegram_id = ?",
                (value, tg_id),
            )
        return True

    def update_fields_by_id(self, user_id: int, fields: Dict[str, Any]) -> bool:
        invalid = set(fields.keys()) - USER_UPDATABLE_FIELDS
        if invalid:
            raise ValueError(f"Недопустимые поля: {invalid}")
        if not fields:
            return True
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [user_id]
        with self.db.transaction() as c:
            c.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        return True

    def change_rating(self, user_id: int, delta: int) -> int:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE users SET rating = MAX(0, rating + ?) WHERE id = ?",
                (delta, user_id),
            )
            row = c.execute("SELECT rating FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row else 0

    def change_customer_rating(self, user_id: int, delta: int) -> int:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE users SET customer_rating = MAX(0, customer_rating + ?) WHERE id = ?",
                (delta, user_id),
            )
            row = c.execute("SELECT customer_rating FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row else 0

    def list_workers(self, limit: int = 50) -> List[UserDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM users WHERE role = 'rabotnik' ORDER BY rating DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_user(r) for r in rows if r]

    def list_customers(self, limit: int = 50) -> List[UserDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM users WHERE role = 'zakazchik' "
                "ORDER BY customer_rating DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_user(r) for r in rows if r]

    def active_workers_for_notify(self) -> List[int]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT telegram_id FROM users "
                "WHERE role = 'rabotnik' AND blocked = 0 "
                "AND agreement_accepted = 1 AND notify = 1"
            ).fetchall()
        return [r[0] for r in rows]

    def count(self) -> Dict[str, int]:
        with self.db.connection() as c:
            total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            workers = c.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'rabotnik'"
            ).fetchone()[0]
            customers = c.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'zakazchik'"
            ).fetchone()[0]
            orders = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        return {"total": total, "workers": workers, "customers": customers, "orders": orders}

    def log_moderator_action(
        self, moderator_id: int, action: str,
        target_user_id: Optional[int] = None, details: Optional[str] = None
    ) -> None:
        try:
            with self.db.transaction() as c:
                c.execute(
                    "INSERT INTO moderator_actions "
                    "(moderator_id, action, target_user_id, details) "
                    "VALUES (?, ?, ?, ?)",
                    (moderator_id, action, target_user_id, details),
                )
        except Exception as e:
            logging.getLogger("yurga").warning(f"moderator action log: {e}")


@dataclass
class OrderDTO:
    id: int
    zakazchik_id: int
    zakazchik_name: Optional[str]
    address: str
    work_description: str
    hours: int
    people: int
    total_sum: int
    commission: int
    payout_per_person: int
    status: str
    photo_file_id: Optional[str] = None
    created_at: Optional[str] = None
    paid_at: Optional[str] = None
    completed_at: Optional[str] = None


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, order_id: int) -> Optional[OrderDTO]:
        with self.db.connection() as c:
            row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return OrderDTO(**dict(row)) if row else None

    def create(self, *, customer: UserDTO, address: str, description: str,
               hours: int, people: int, price_per_hour: int, commission_per_hour: int) -> OrderDTO:
        total = hours * people * price_per_hour
        commission = hours * people * commission_per_hour
        payout = (total - commission) // people
        with self.db.transaction() as c:
            c.execute(
                """INSERT INTO orders
                (zakazchik_id, zakazchik_name, address, work_description,
                 hours, people, total_sum, commission, payout_per_person, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (customer.id, customer.name or "Заказчик", address, description,
                 hours, people, total, commission, payout, OrderStatus.OPEN.value),
            )
            new_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = c.execute("SELECT * FROM orders WHERE id = ?", (new_id,)).fetchone()
        return OrderDTO(**dict(row))

    def update_status(self, order_id: int, new_status: OrderStatus) -> bool:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                (new_status.value, order_id),
            )
        return True

    def set_paid_at(self, order_id: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE orders SET paid_at = datetime('now') WHERE id = ?",
                (order_id,),
            )

    def set_completed_at(self, order_id: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE orders SET completed_at = datetime('now') WHERE id = ?",
                (order_id,),
            )

    def list_active(self, limit: int = 50) -> List[OrderDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM orders WHERE status NOT IN (?, ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value, limit),
            ).fetchall()
        return [OrderDTO(**dict(r)) for r in rows]

    def list_open(self, limit: int = 20) -> List[OrderDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (OrderStatus.OPEN.value, limit),
            ).fetchall()
        return [OrderDTO(**dict(r)) for r in rows]

    def list_completed(self, limit: int = 20) -> List[OrderDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (OrderStatus.COMPLETED.value, limit),
            ).fetchall()
        return [OrderDTO(**dict(r)) for r in rows]

    def list_by_customer(self, customer_internal_id: int, limit: int = 100) -> List[OrderDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM orders WHERE zakazchik_id = ? ORDER BY created_at DESC LIMIT ?",
                (customer_internal_id, limit),
            ).fetchall()
        return [OrderDTO(**dict(r)) for r in rows]

    def total_payouts(self) -> Tuple[int, int]:
        with self.db.connection() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(payout),0), COUNT(*) FROM assignments"
            ).fetchone()
        return int(row[0]), int(row[1])


@dataclass
class AssignmentDTO:
    order_id: int
    user_id: int
    payout: int
    confirmed: int
    confirmed_at: Optional[str]
    photo_file_id: Optional[str]


class AssignmentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def take_order(self, order_id: int, user_id: int, payout: int) -> bool:
        try:
            with self.db.transaction() as c:
                row = c.execute(
                    "SELECT people FROM orders WHERE id = ? AND status = ?",
                    (order_id, OrderStatus.OPEN.value),
                ).fetchone()
                if not row:
                    return False
                current = c.execute(
                    "SELECT COUNT(*) FROM assignments WHERE order_id = ?",
                    (order_id,),
                ).fetchone()[0]
                if current >= row[0]:
                    return False
                c.execute(
                    """INSERT OR IGNORE INTO assignments (order_id, user_id, payout)
                       VALUES (?, ?, ?)""",
                    (order_id, user_id, payout),
                )
            return True
        except Exception:
            return False

    def list_by_order(self, order_id: int) -> List[AssignmentDTO]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT * FROM assignments WHERE order_id = ?", (order_id,)
            ).fetchall()
        return [AssignmentDTO(**dict(r)) for r in rows]

    def list_user_ids(self, order_id: int) -> List[int]:
        with self.db.connection() as c:
            rows = c.execute(
                "SELECT user_id FROM assignments WHERE order_id = ?", (order_id,)
            ).fetchall()
        return [r[0] for r in rows]

    def confirm_place(self, order_id: int, user_id: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE assignments SET confirmed = 1, confirmed_at = datetime('now') "
                "WHERE order_id = ? AND user_id = ?",
                (order_id, user_id),
            )

    def set_photo(self, order_id: int, user_id: int, file_id: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "UPDATE assignments SET photo_file_id = ? "
                "WHERE order_id = ? AND user_id = ?",
                (file_id, order_id, user_id),
            )

    def all_have_photos(self, order_id: int) -> bool:
        with self.db.connection() as c:
            row = c.execute(
                """SELECT COUNT(*) FROM assignments
                   WHERE order_id = ? AND photo_file_id IS NULL""",
                (order_id,),
            ).fetchone()
        return row[0] == 0

    def all_confirmed(self, order_id: int) -> bool:
        with self.db.connection() as c:
            row = c.execute(
                """SELECT COUNT(*) FROM assignments
                   WHERE order_id = ? AND confirmed = 0""",
                (order_id,),
            ).fetchone()
        return row[0] == 0

    def count(self, order_id: int) -> int:
        with self.db.connection() as c:
            return c.execute(
                "SELECT COUNT(*) FROM assignments WHERE order_id = ?", (order_id,)
            ).fetchone()[0]

    def delete(self, order_id: int, user_id: int) -> None:
        with self.db.transaction() as c:
            c.execute(
                "DELETE FROM assignments WHERE order_id = ? AND user_id = ?",
                (order_id, user_id),
            )

    def list_worker_orders(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self.db.connection() as c:
            rows = c.execute(
                """SELECT o.id, o.status, a.payout, o.zakazchik_name,
                          o.address, o.work_description, a.confirmed
                   FROM assignments a JOIN orders o ON a.order_id = o.id
                   WHERE a.user_id = ?
                   ORDER BY o.created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def total_for_user(self, user_id: int) -> Tuple[int, int]:
        with self.db.connection() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(payout),0), COUNT(*) FROM assignments WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row[0]), int(row[1])


class StateRepository:
    def __init__(self, db: Database, ttl_minutes: int = 30) -> None:
        self.db = db
        self.ttl = ttl_minutes
        self._cleanup_counter = 0

    def set(self, user_id: int, state: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._maybe_cleanup()
        now = datetime.utcnow()
        expires = now + timedelta(minutes=self.ttl)
        with self.db.transaction() as c:
            c.execute(
                """INSERT OR REPLACE INTO temp_states
                   (user_id, state, data, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, state, json.dumps(data or {}, ensure_ascii=False),
                 now.isoformat(), expires.isoformat()),
            )

    def get(self, user_id: int) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        with self.db.connection() as c:
            row = c.execute(
                "SELECT state, data FROM temp_states "
                "WHERE user_id = ? AND expires_at > datetime('now')",
                (user_id,),
            ).fetchone()
        if not row:
            return None, None
        try:
            return row[0], json.loads(row[1])
        except json.JSONDecodeError:
            return row[0], {}

    def clear(self, user_id: int) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM temp_states WHERE user_id = ?", (user_id,))

    def _maybe_cleanup(self) -> None:
        self._cleanup_counter += 1
        if self._cleanup_counter % 50 != 0:
            return
        try:
            with self.db.transaction() as c:
                c.execute(
                    "DELETE FROM temp_states WHERE expires_at <= datetime('now')"
                )
        except Exception:
            pass


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, from_user_id: int, to_user_id: int, order_id: Optional[int], text: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO messages (from_user_id, to_user_id, order_id, text) "
                "VALUES (?, ?, ?, ?)",
                (from_user_id, to_user_id, order_id, text),
            )
class SheetsService:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._sheet = None
        self._available = _GSPREAD_AVAILABLE and bool(config.google_credentials and config.spreadsheet_id)
        self._logger = logging.getLogger("yurga.sheets")

    def _get_sheet(self):
        if not self._available:
            return None
        if self._sheet is not None:
            return self._sheet
        try:
            scope = ["https://spreadsheets.google.com/feeds",
                     "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(
                self._config.google_credentials, scope
            )
            client = gspread.authorize(creds)
            self._sheet = client.open_by_key(self._config.spreadsheet_id)
            return self._sheet
        except Exception as e:
            self._logger.warning(f"Google Sheets: {e}")
            self._available = False
            return None

    def _retry(self, fn, *args, retries: int = 3):
        for attempt in range(retries):
            try:
                return fn(*args)
            except Exception as e:
                self._logger.warning(f"Sheets retry {attempt+1}/{retries}: {e}")
                if attempt == retries - 1:
                    return False
                time.sleep(0.5 * (attempt + 1))
        return False

    def append_order(self, data: Dict[str, Any]) -> bool:
        if not self._available:
            return False
        def _do():
            ws = self._get_sheet().worksheet("Заказы")
            ws.append_row([
                data.get("id", ""), data.get("created_at", ""),
                data.get("zakazchik_name", ""), data.get("phone", ""),
                data.get("address", ""), data.get("work_description", ""),
                data.get("hours", ""), data.get("people", ""),
                data.get("total_sum", ""), data.get("commission", ""),
                data.get("payout_per_person", ""), data.get("status", "Open"),
                data.get("paid_at", ""), data.get("completed_at", ""),
            ])
        return self._retry(_do)

    def append_user(self, data: Dict[str, Any]) -> bool:
        if not self._available:
            return False
        def _do():
            ws = self._get_sheet().worksheet("Пользователи")
            ws.append_row([
                data.get("telegram_id", ""), data.get("name", ""),
                data.get("phone", ""), data.get("role", ""),
                data.get("registered_at", ""),
            ])
        return self._retry(_do)

    def append_payout(self, data: Dict[str, Any]) -> bool:
        if not self._available:
            return False
        def _do():
            ws = self._get_sheet().worksheet("Выплаты")
            ws.append_row([
                data.get("date", ""), data.get("order_id", ""),
                data.get("customer_name", ""), data.get("address", ""),
                data.get("worker_name", ""), data.get("amount", ""),
                data.get("moderator_name", ""),
            ])
        return self._retry(_do)

    def append_commission(self, data: Dict[str, Any]) -> bool:
        if not self._available:
            return False
        def _do():
            ws = self._get_sheet().worksheet("Комиссия")
            ws.append_row([
                data.get("date", ""), data.get("order_id", ""),
                data.get("amount", ""),
            ])
        return self._retry(_do)

    def update_order_status(self, order_id: int, status: str,
                            paid_at: Optional[str] = None,
                            completed_at: Optional[str] = None) -> bool:
        if not self._available:
            return False
        def _do():
            ws = self._get_sheet().worksheet("Заказы")
            try:
                cell = ws.find(str(order_id))
            except gspread.exceptions.CellNotFound:
                return False
            ws.update_cell(cell.row, 12, status)
            if paid_at:
                ws.update_cell(cell.row, 13, paid_at)
            if completed_at:
                ws.update_cell(cell.row, 14, completed_at)
            return True
        return self._retry(_do)


class SafeBot:
    def __init__(self, bot: telebot.TeleBot) -> None:
        self.bot = bot
        self._logger = logging.getLogger("yurga.bot")

    def send(self, chat_id: Optional[int], text: str, **kwargs) -> Any:
        if not chat_id:
            return None
        try:
            return self.bot.send_message(chat_id, text, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code in (403, 400):
                return None
            self._logger.warning(f"send({chat_id}): {e}")
            return None
        except Exception as e:
            self._logger.error(f"send({chat_id}): {e}")
            return None

    def edit(self, text: str, chat_id: int, msg_id: int, **kwargs) -> Any:
        try:
            return self.bot.edit_message_text(text, chat_id, msg_id, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                return None
            self._logger.warning(f"edit({chat_id}/{msg_id}): {e}")
            return None
        except Exception as e:
            self._logger.error(f"edit: {e}")
            return None

    def send_photo(self, chat_id: int, photo: Any, caption: Optional[str] = None, **kwargs) -> Any:
        try:
            return self.bot.send_photo(chat_id, photo, caption=caption, **kwargs)
        except Exception as e:
            self._logger.warning(f"send_photo({chat_id}): {e}")
            return None

    def answer_callback(self, call, text: str = "", show_alert: bool = False) -> None:
        try:
            self.bot.answer_callback_query(call.id, text, show_alert=show_alert)
        except Exception as e:
            self._logger.debug(f"answer_callback: {e}")


def main_kb(telegram_id: int, moderator_ids: Iterable[int]) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    if telegram_id in moderator_ids:
        kb.row(KeyboardButton("🛡️ Я модератор"))
    return kb


def worker_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
    kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("📋 Мои заказы"))
    kb.row(KeyboardButton("👤 Профиль"), KeyboardButton("🔄 Сменить смену"))
    kb.row(KeyboardButton("🔔 Уведомления"), KeyboardButton("📞 Связаться с модератором"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb


def customer_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📝 Создать заказ"))
    kb.row(KeyboardButton("📋 Мои заказы"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("📞 Связаться с модератором"), KeyboardButton("⚠️ Пожаловаться"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb


def moderator_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    kb.row(KeyboardButton("🏢 Заказчики"), KeyboardButton("📊 Статистика"))
    kb.row(KeyboardButton("⭐ Оценить работника"), KeyboardButton("⭐ Оценить заказчика"))
    kb.row(KeyboardButton("🔒 Блокировка"), KeyboardButton("🔓 Разблокировка"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb


def blocked_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📞 Связь с модератором"))
    return kb


def order_inline_kb(order_id: int, is_customer: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    if is_customer:
        kb.add(InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{order_id}"))
        kb.add(InlineKeyboardButton("📞 Написать работнику",
                                    callback_data=f"contact_worker_order_{order_id}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{order_id}"))
        kb.add(InlineKeyboardButton("📞 Написать заказчику",
                                    callback_data=f"contact_customer_order_{order_id}"))
    return kb


def confirm_take_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📍 Я на месте", callback_data=f"confirm_place_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отказаться", callback_data=f"cancel_take_{order_id}"))
    return kb


def payment_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Я оплатил", callback_data=f"i_paid_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{order_id}"))
    return kb


def worker_photo_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📸 Отправить фото", callback_data=f"send_photo_{order_id}"))
    return kb


def approve_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Работа выполнена", callback_data=f"approve_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}"))
    return kb


def moderator_payment_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить оплату",
                                callback_data=f"confirm_payment_{order_id}"))
    return kb


def moderator_payout_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Выплатил работникам",
                                callback_data=f"confirm_payout_{order_id}"))
    return kb


_CB_PATTERNS = {
    "take":              re.compile(r"^take_(\d+)$"),
    "confirm_place":     re.compile(r"^confirm_place_(\d+)$"),
    "cancel_take":       re.compile(r"^cancel_take_(\d+)$"),
    "i_paid":            re.compile(r"^i_paid_(\d+)$"),
    "confirm_payment":   re.compile(r"^confirm_payment_(\d+)$"),
    "send_photo":        re.compile(r"^send_photo_(\d+)$"),
    "approve":           re.compile(r"^approve_(\d+)$"),
    "reject":            re.compile(r"^reject_(\d+)$"),
    "confirm_payout":    re.compile(r"^confirm_payout_(\d+)$"),
    "cancel":            re.compile(r"^cancel_(\d+)$"),
    "complete":          re.compile(r"^complete_(\d+)$"),
    "contact_mod":       re.compile(r"^contact_mod_(\d+)$"),
    "contact_customer_order": re.compile(r"^contact_customer_order_(\d+)$"),
    "contact_worker_order":   re.compile(r"^contact_worker_order_(\d+)$"),
    "send_msg":          re.compile(r"^send_msg_(\d+)(?:_(\d+))?$"),
}


def parse_callback(data: str) -> Tuple[Optional[str], List[int]]:
    for action, pattern in _CB_PATTERNS.items():
        m = pattern.match(data)
        if m:
            return action, [int(g) for g in m.groups() if g is not None]
    return None, []


class OrderService:
    def __init__(self, users: UserRepository, orders: OrderRepository,
                 assignments: AssignmentRepository, sheets: SheetsService,
                 config: Config) -> None:
        self.users = users
        self.orders = orders
        self.assign = assignments
        self.sheets = sheets
        self.config = config

    def is_fully_staffed(self, order_id: int) -> bool:
        order = self.orders.get(order_id)
        if not order:
            return False
        return self.assign.count(order_id) >= order.people

    def are_all_confirmed(self, order_id: int) -> bool:
        return self.assign.all_confirmed(order_id)

    def are_all_photos(self, order_id: int) -> bool:
        return self.assign.all_have_photos(order_id)


class YurgaBot:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = logging.getLogger("yurga")

        self.bot = telebot.TeleBot(config.token, threaded=True)
        self.safe = SafeBot(self.bot)
        self.db = Database(config.db_path)

        self.users = UserRepository(self.db)
        self.orders = OrderRepository(self.db)
        self.assign = AssignmentRepository(self.db)
        self.states = StateRepository(self.db, config.state_ttl_minutes)
        self.messages_repo = MessageRepository(self.db)
        self.sheets = SheetsService(config)
        self.service = OrderService(
            self.users, self.orders, self.assign, self.sheets, config
        )
        self.limiter = RateLimiter()

        self._running = True
        self._register_handlers()

    def _is_moderator(self, user_id: int) -> bool:
        return user_id in self.config.moderator_ids

    def _get_user_or_none(self, tg_id: int) -> Optional[UserDTO]:
        return self.users.get_by_telegram(tg_id)

    def _require_not_blocked(self, user: Optional[UserDTO], chat_id: int) -> bool:
        if not user:
            self.safe.send(chat_id, "Нажмите /start")
            return False
        if user.blocked:
            self.safe.send(chat_id, "Ваш аккаунт заблокирован.",
                           reply_markup=blocked_kb())
            return False
        return True

    def _require_role(self, user: UserDTO, role: Role, chat_id: int) -> bool:
        if user.role != role.value:
            self.safe.send(chat_id, f"Эта функция доступна только роли '{role.value}'.")
            return False
        return True

    def _require_registered(self, user: UserDTO, chat_id: int) -> bool:
        if not user.agreement_accepted:
            self.safe.send(chat_id, "Вы не зарегистрированы. Нажмите 'Регистрация'.")
            return False
        return True

    def _notify_moderators(self, text: str) -> None:
        for m_id in self.config.moderator_ids:
            self.safe.send(m_id, text)

    def _notify_workers(self, text: str) -> None:
        for tg_id in self.users.active_workers_for_notify():
            self.safe.send(tg_id, text)

    def _register_handlers(self) -> None:
        b = self.bot

        @b.message_handler(commands=["start"])
        def cmd_start(m): self._on_start(m)

        @b.message_handler(commands=["cancel"])
        def cmd_cancel(m): self._on_cancel(m)

        @b.message_handler(func=lambda m: m.text in ("👷 Я работник", "🏢 Я заказчик", "🛡️ Я модератор"))
        def on_role_choice(m): self._on_role_choice(m)

        @b.message_handler(func=lambda m: m.text == "⬅️ Назад")
        def on_back(m): self._on_back(m)

        for text, fn in (
            ("📝 Регистрация", self._worker_reg_start),
            ("📋 Свободные заказы", self._worker_free_orders),
            ("📋 Мои заказы", self._worker_my_orders),
            ("💰 Мои выплаты", self._worker_my_payouts),
            ("👤 Профиль", self._profile),
            ("🔄 Сменить смену", self._worker_toggle_shift),
            ("🔔 Уведомления", self._worker_toggle_notify),
            ("📞 Связаться с модератором", self._contact_mod_start),
        ):
            @b.message_handler(func=lambda m, t=text: m.text == t)
            def h(m, _fn=fn): _fn(m)

        for text, fn in (
            ("📝 Создать заказ", self._customer_create_start),
            ("⚠️ Пожаловаться", self._customer_complain),
        ):
            @b.message_handler(func=lambda m, t=text: m.text == t)
            def h(m, _fn=fn): _fn(m)

        @b.message_handler(func=lambda m: m.text == "📞 Связь с модератором")
        def on_blocked_contact(m): self._blocked_contact_mod(m)

        mod_texts = ("💰 Выплаты", "🟡 Активные", "✅ Завершённые",
                     "👥 Работники", "🏢 Заказчики", "📊 Статистика",
                     "⭐ Оценить работника", "⭐ Оценить заказчика",
                     "🔒 Блокировка", "🔓 Разблокировка")

        @b.message_handler(func=lambda m: m.text in mod_texts and self._is_moderator(m.from_user.id))
        def on_mod_cmd(m): self._on_mod_command(m)

        @b.message_handler(content_types=["photo"])
        def on_photo(m): self._on_photo(m)

        @b.message_handler(func=lambda m: m.text is not None)
        def on_text(m): self._on_free_text(m)

        @b.callback_query_handler(func=lambda c: True)
        def on_callback(c): self._on_callback(c)

    def _on_start(self, m) -> None:
        uid = m.from_user.id
        user = self._get_user_or_none(uid)
        if not user:
            self.users.ensure(uid)
            self.safe.send(m.chat.id,
                           f"Добро пожаловать в бот {self.config.bot_name}!\n\n"
                           f"Выберите свою роль:",
                           reply_markup=main_kb(uid, self.config.moderator_ids))
            return
        if user.blocked:
            self.safe.send(m.chat.id, "Ваш аккаунт заблокирован.",
                           reply_markup=blocked_kb())
            return
        if user.role == Role.WORKER.value:
            status = "на смене" if user.on_shift else "не на смене"
            notify = "вкл" if user.notify else "выкл"
            self.safe.send(m.chat.id,
                           f"Меню работника\n\nСтатус: {status}\n"
                           f"Уведомления: {notify}",
                           reply_markup=worker_kb())
        elif user.role == Role.CUSTOMER.value:
            self.safe.send(m.chat.id, "Меню заказчика",
                           reply_markup=customer_kb())
        elif user.role == Role.MODERATOR.value:
            self.safe.send(m.chat.id, "Панель модератора",
                           reply_markup=moderator_kb())
        else:
            self.safe.send(m.chat.id, "Выберите роль:",
                           reply_markup=main_kb(uid, self.config.moderator_ids))

    def _on_cancel(self, m) -> None:
        self.states.clear(m.from_user.id)
        self.safe.send(m.chat.id, "Действие отменено.",
                       reply_markup=main_kb(m.from_user.id, self.config.moderator_ids))

    def _on_back(self, m) -> None:
        uid = m.from_user.id
        self.safe.send(m.chat.id, "Главное меню:\n\nВыберите роль:",
                       reply_markup=main_kb(uid, self.config.moderator_ids))

    def _on_role_choice(self, m) -> None:
        uid = m.from_user.id
        user = self._get_user_or_none(uid)
        if not self._require_not_blocked(user, m.chat.id):
            return
        mapping = {"👷 Я работник": Role.WORKER.value,
                   "🏢 Я заказчик": Role.CUSTOMER.value,
                   "🛡️ Я модератор": Role.MODERATOR.value}
        new_role = mapping[m.text]
        if new_role == Role.MODERATOR.value and not self._is_moderator(uid):
            self.safe.send(m.chat.id, "У вас нет прав модератора.")
            return
        self.users.update_field(uid, "role", new_role)
        if new_role == Role.WORKER.value:
            self.safe.send(m.chat.id, "Вы переключились на роль работника!",
                           reply_markup=worker_kb())
        elif new_role == Role.CUSTOMER.value:
            self.safe.send(m.chat.id, "Вы переключились на роль заказчика!",
                           reply_markup=customer_kb())
        else:
            self.safe.send(m.chat.id, "Вы переключились на панель модератора!",
                           reply_markup=moderator_kb())

    def _worker_reg_start(self, m) -> None:
        uid = m.from_user.id
        user = self._get_user_or_none(uid)
        if not self._require_not_blocked(user, m.chat.id):
            return
        if user.agreement_accepted:
            self.safe.send(m.chat.id, "Вы уже зарегистрированы!")
            return
        if user.role not in (Role.WORKER.value, Role.CUSTOMER.value):
            self.safe.send(m.chat.id, "Сначала выберите роль через главное меню.")
            return
        self.states.set(uid, "agreement", {"role": user.role})
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("✅ Принимаю"), KeyboardButton("❌ Отмена"))
        if user.role == Role.WORKER.value:
            text = (
                "УСЛОВИЯ СЕРВИСА (ДЛЯ РАБОТНИКОВ)\n\n"
                "1. Вы берёте заказ только если готовы его выполнить.\n"
                "2. ОБЯЗАТЕЛЬНО подтвердите, что вы на месте "
                "(кнопка 'Я на месте').\n"
                "3. После работы отправьте ФОТО выполненной работы.\n"
                "4. Без фото и подтверждения заказчик не сможет подтвердить "
                "работу, и вы не получите выплату.\n"
                "5. Сервис гарантирует выплату после подтверждения заказчиком.\n"
                "6. Сервис не отвечает за травмы, кражи, качество вашей работы.\n\n"
                "Принимаете условия?"
            )
        else:
            text = (
                "УСЛОВИЯ СЕРВИСА (ДЛЯ ЗАКАЗЧИКОВ)\n\n"
                "Вы платите ДО начала работы — деньги замораживаются "
                "на счёте сервиса.\n"
                "Это гарантирует, что работники получат оплату "
                "после выполнения.\n"
                "После того как работники подтвердят, что они на месте, "
                "вы переводите деньги.\n"
                "Если работа выполнена качественно, вы подтверждаете это — "
                "деньги перечисляются работникам.\n"
                "Если работа выполнена плохо или не выполнена — "
                "вы можете отклонить, и мы вернём вам деньги "
                "(после проверки модератором).\n"
                "Сервис защищает и вас, и работников "
                "от недобросовестных исполнителей.\n\n"
                "Принимаете условия?"
            )
        self.safe.send(m.chat.id, text, reply_markup=kb)

    def _on_free_text(self, m) -> None:
        uid = m.from_user.id
        if not m.text:
            return
        state, data = self.states.get(uid)
        if state is None:
            return
        try:
            if state == "agreement":
                self._handle_agreement(m, data or {})
            elif state == "reg_name":
                self._reg_name(m, data or {})
            elif state == "reg_phone":
                self._reg_phone(m, data or {})
            elif state == "reg_bank":
                self._reg_bank(m, data or {})
            elif state == "reg_initials":
                self._reg_initials(m, data or {})
            elif state == "order_city":
                self._order_city(m, data or {})
            elif state == "order_city_other":
                data["city"] = m.text.strip()
                self.states.set(m.from_user.id, "order_address", data)
                self.safe.send(m.chat.id, "Введите адрес выполнения работы:")
            elif state == "order_address":
                self._order_address(m, data or {})
            elif state == "order_description":
                self._order_description(m, data or {})
            elif state == "order_hours":
                self._order_hours(m, data or {})
            elif state == "order_people":
                self._order_people(m, data or {})
            elif state == "msg_to_mod":
                self._msg_to_mod(m, data or {})
            elif state == "msg_to_user":
                self._msg_to_user(m, data or {})
            elif state == "mod_rate_worker":
                self._mod_rate_worker_apply(m, data or {})
            elif state == "mod_rate_customer":
                self._mod_rate_customer_apply(m, data or {})
            elif state == "mod_block_method":
                self._mod_block_choose_method(m, data or {})
            elif state == "mod_block_by_id":
                self._mod_block_by_id(m)
            elif state == "mod_block_by_phone":
                self._mod_block_by_phone(m)
            elif state == "mod_unblock_by_id":
                self._mod_unblock_by_id(m)
            else:
                self.logger.warning(f"Unknown state '{state}' for user {uid}")
                self.states.clear(uid)
        except Exception as e:
            self.logger.exception(f"State '{state}' error for {uid}: {e}")
            self.safe.send(m.chat.id, "Ошибка. Попробуйте позже.")
            self.states.clear(uid)

    def _handle_agreement(self, m, data: Dict) -> None:
        uid = m.from_user.id
        if m.text == "❌ Отмена":
            self.states.clear(uid)
            self.safe.send(m.chat.id, "Регистрация отменена.",
                           reply_markup=main_kb(uid, self.config.moderator_ids))
            return
        if m.text != "✅ Принимаю":
            self.safe.send(m.chat.id, "Нажмите кнопку 'Принимаю' или 'Отмена'.")
            return
        role = data.get("role")
        self.users.update_field(uid, "agreement_accepted", 1)
        self.states.set(uid, "reg_name", {"role": role})
        self.safe.send(m.chat.id, "Введите ваше ФИО:")

    def _reg_name(self, m, data: Dict) -> None:
        if not validate_name(m.text):
            self.safe.send(m.chat.id, "Некорректное имя. Используйте буквы, 2-100 символов.")
            return
        data["name"] = m.text.strip()
        self.states.set(m.from_user.id, "reg_phone", data)
        self.safe.send(m.chat.id, "Введите номер телефона (+7XXXXXXXXXX):")

    def _reg_phone(self, m, data: Dict) -> None:
        if not validate_phone(m.text):
            self.safe.send(m.chat.id, "Некорректный телефон. Пример: +79991234567")
            return
        data["phone"] = m.text.strip()
        if data.get("role") == Role.WORKER.value:
            self.states.set(m.from_user.id, "reg_bank", data)
            self.safe.send(m.chat.id, "Введите номер карты для выплат:")
        else:
            self._finish_customer_reg(m, data)

    def _reg_bank(self, m, data: Dict) -> None:
        bank = m.text.strip()
        if len(bank) < 5 or len(bank) > 50:
            self.safe.send(m.chat.id, "Некорректные реквизиты.")
            return
        data["bank"] = bank
        self.states.set(m.from_user.id, "reg_initials", data)
        self.safe.send(m.chat.id, "Введите инициалы (Иванов И.И.):")

    def _reg_initials(self, m, data: Dict) -> None:
        if not validate_initials(m.text):
            self.safe.send(m.chat.id, "Неверный формат. Пример: Иванов И.И.")
            return
        data["initials"] = m.text.strip()
        self._finish_worker_reg(m, data)

    def _finish_worker_reg(self, m, data: Dict) -> None:
        uid = m.from_user.id
        user = self.users.get_by_telegram(uid)
        if not user:
            return
        try:
            self.users.update_fields_by_id(user.id, {
                "name": data.get("name"),
                "phone": data.get("phone"),
                "bank": data.get("bank"),
                "initials": data.get("initials"),
                "on_shift": 1,
            })
        except ValueError as e:
            self.safe.send(m.chat.id, f"Ошибка: {e}")
            return
        self.states.clear(uid)
        self.safe.send(m.chat.id, "Регистрация завершена! Вы на смене",
                       reply_markup=worker_kb())
        self.sheets.append_user({
            "telegram_id": uid,
            "name": data.get("name"),
            "phone": data.get("phone"),
            "role": "rabotnik",
            "registered_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        })

    def _finish_customer_reg(self, m, data: Dict) -> None:
        uid = m.from_user.id
        user = self.users.get_by_telegram(uid)
        if not user:
            return
        try:
            self.users.update_fields_by_id(user.id, {
                "name": data.get("name"),
                "phone": data.get("phone"),
            })
        except ValueError as e:
            self.safe.send(m.chat.id, f"Ошибка: {e}")
            return
        self.states.clear(uid)
        self.safe.send(m.chat.id, "Регистрация заказчика завершена!",
                       reply_markup=customer_kb())
        self.sheets.append_user({
            "telegram_id": uid,
            "name": data.get("name"),
            "phone": data.get("phone"),
            "role": "zakazchik",
            "registered_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        })

    def _customer_create_start(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id): return
        if not self._require_role(user, Role.CUSTOMER, m.chat.id): return
        if not self._require_registered(user, m.chat.id): return
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("Новосибирск"), KeyboardButton("Томск"))
        kb.row(KeyboardButton("Кемерово"), KeyboardButton("Юрга"))
        kb.row(KeyboardButton("Другой город"))
        self.states.set(m.from_user.id, "order_city", {})
        self.safe.send(m.chat.id, "Выберите город:", reply_markup=kb)

    def _order_city(self, m, data: Dict) -> None:
        if m.text not in ("Новосибирск", "Томск", "Кемерово", "Юрга", "Другой город"):
            self.safe.send(m.chat.id, "Выберите город из списка.")
            return
        if m.text == "Другой город":
            self.safe.send(m.chat.id, "Введите название города:")
            self.states.set(m.from_user.id, "order_city_other", data)
            return
        data["city"] = m.text
        self.states.set(m.from_user.id, "order_address", data)
        self.safe.send(m.chat.id, "Введите адрес выполнения работы:")

    def _order_address(self, m, data: Dict) -> None:
        if not m.text or len(m.text.strip()) < 5:
            self.safe.send(m.chat.id, "Слишком короткий адрес.")
            return
        data["address"] = f"{data.get('city', '')}, {m.text.strip()}"
        self.states.set(m.from_user.id, "order_description", data)
        self.safe.send(m.chat.id, "Введите описание работы (что нужно сделать):")

    def _order_description(self, m, data: Dict) -> None:
        if not m.text or len(m.text.strip()) < 3:
            self.safe.send(m.chat.id, "Слишком короткое описание.")
            return
        data["work_description"] = m.text.strip()
        self.states.set(m.from_user.id, "order_hours", data)
        self.safe.send(m.chat.id, "Введите количество часов (число):")

    def _order_hours(self, m, data: Dict) -> None:
        n = validate_positive_int(m.text, 24)
        if n is None:
            self.safe.send(m.chat.id, "Введите целое число от 1 до 24.")
            return
        data["hours"] = n
        self.states.set(m.from_user.id, "order_people", data)
        self.safe.send(m.chat.id, "Введите количество человек:")

    def _order_people(self, m, data: Dict) -> None:
        n = validate_positive_int(m.text, 50)
        if n is None:
            self.safe.send(m.chat.id, "Введите целое число от 1 до 50.")
            return
        user = self.users.get_by_telegram(m.from_user.id)
        if not user:
            self.safe.send(m.chat.id, "Пользователь не найден.")
            self.states.clear(m.from_user.id)
            return
        order = self.orders.create(
            customer=user,
            address=data["address"],
            description=data["work_description"],
            hours=data["hours"],
            people=n,
            price_per_hour=self.config.price_per_hour,
            commission_per_hour=self.config.commission_per_hour,
        )
        self.states.clear(m.from_user.id)
        self.safe.send(
            m.chat.id,
            f"ЗАКАЗ #{order.id} СОЗДАН!\n\n"
            f"{order.address}\n{order.work_description}\n"
            f"{order.hours} ч.  {order.people} чел.\n"
            f"{order.total_sum} руб",
            reply_markup=customer_kb(),
        )
        self.sheets.append_order({
            "id": order.id,
            "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "zakazchik_name": order.zakazchik_name,
            "phone": user.phone or "не указан",
            "address": order.address,
            "work_description": order.work_description,
            "hours": order.hours,
            "people": order.people,
            "total_sum": order.total_sum,
            "commission": order.commission,
            "payout_per_person": order.payout_per_person,
            "status": "Open",
        })
        self._notify_workers(
            f"НОВЫЙ ЗАКАЗ!\n#{order.id}\n{order.payout_per_person} руб\n"
            f"{order.address}\n{order.work_description}\n"
            f"{order.hours} ч.  {order.people} чел."
        )
        self._notify_moderators(
            f"НОВЫЙ ЗАКАЗ #{order.id}\n\n"
            f"{order.zakazchik_name}\n{order.address}\n"
            f"{order.work_description}\n{order.hours} ч.  "
            f"{order.people} чел.\n{order.total_sum} руб"
        )

    def _customer_complain(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id): return
        if not self._require_role(user, Role.CUSTOMER, m.chat.id): return
        self.states.set(m.from_user.id, "msg_to_mod", {"complaint": True})
        self.safe.send(m.chat.id, "Опишите жалобу:\n(для отмены /cancel)")
    def _worker_toggle_shift(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id):
            return
        if not self._require_role(user, Role.WORKER, m.chat.id):
            return
        new_val = 0 if user.on_shift else 1
        self.users.update_field(m.from_user.id, "on_shift", new_val)
        status = "на смене" if new_val else "не на смене"
        self.safe.send(m.chat.id, f"Статус: {status}", reply_markup=worker_kb())

    def _worker_toggle_notify(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id):
            return
        if not self._require_role(user, Role.WORKER, m.chat.id):
            return
        new_val = 0 if user.notify else 1
        self.users.update_field(m.from_user.id, "notify", new_val)
        status = "включены" if new_val else "выключены"
        self.safe.send(m.chat.id, f"Уведомления {status}", reply_markup=worker_kb())

    def _worker_free_orders(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id): return
        if not self._require_role(user, Role.WORKER, m.chat.id): return
        if not self._require_registered(user, m.chat.id): return

        if not self.limiter.check(m.from_user.id, "free_orders", 15):
            self.safe.send(m.chat.id, "Слишком часто. Подождите минуту.")
            return

        rows = self.orders.list_open(20)
        if not rows:
            self.safe.send(m.chat.id, "Нет свободных заказов.")
            return
        for o in rows:
            text = (f"Заказ #{o.id}\n{o.payout_per_person} руб\n"
                    f"{o.address}\n{o.work_description}\n"
                    f"{o.hours} ч.  {o.people} чел.")
            self.safe.send(m.chat.id, text,
                           reply_markup=order_inline_kb(o.id, is_customer=False))

    def _worker_my_orders(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id): return

        if user.role == Role.WORKER.value:
            orders = self.assign.list_worker_orders(user.id)
            if not orders:
                self.safe.send(m.chat.id, "Нет активных заказов.")
                return
            labels = {
                OrderStatus.OPEN.value: "Открыт",
                OrderStatus.READY_TO_PAY.value: "Ожидает оплаты",
                OrderStatus.PAID.value: "Оплачен",
                OrderStatus.WORKING.value: "В работе",
                OrderStatus.WAITING_APPROVAL.value: "Ждёт подтверждения",
                OrderStatus.WAITING_PAYOUT.value: "Ждёт выплаты",
                OrderStatus.COMPLETED.value: "Завершён",
            }
            for o in orders:
                st = labels.get(o["status"], o["status"])
                text = (f"Заказ #{o['id']}\n{st}\n{o['payout']} руб\n"
                        f"{o['zakazchik_name']}\n{o['address']}\n"
                        f"{o['work_description']}")
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton(
                    "Написать заказчику",
                    callback_data=f"contact_customer_order_{o['id']}"))
                self.safe.send(m.chat.id, text, reply_markup=kb)
        elif user.role == Role.CUSTOMER.value:
            orders = self.orders.list_by_customer(user.id, 100)
            if not orders:
                self.safe.send(m.chat.id, "У вас нет заказов.")
                return
            labels = {
                OrderStatus.OPEN.value: "Открыт",
                OrderStatus.READY_TO_PAY.value: "Ожидает оплаты",
                OrderStatus.PAID.value: "Оплачен",
                OrderStatus.WORKING.value: "В работе",
                OrderStatus.WAITING_APPROVAL.value: "Ждёт подтверждения",
                OrderStatus.WAITING_PAYOUT.value: "Ждёт выплаты",
                OrderStatus.COMPLETED.value: "Завершён",
                OrderStatus.CANCELLED.value: "Отменён",
            }
            for o in orders:
                st = labels.get(o.status, o.status)
                text = (f"Заказ #{o.id}\n{o.total_sum} руб\n{st}\n"
                        f"{o.address}\n{o.work_description}")
                kb = InlineKeyboardMarkup()
                worker_ids = self.assign.list_user_ids(o.id)
                if worker_ids:
                    kb.add(InlineKeyboardButton(
                        "Написать работнику",
                        callback_data=f"contact_worker_order_{o.id}"))
                if o.status not in (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value):
                    kb.add(InlineKeyboardButton(
                        "Отменить заказ", callback_data=f"cancel_{o.id}"))
                self.safe.send(m.chat.id, text, reply_markup=kb)
        else:
            self.safe.send(m.chat.id, "Неизвестная роль.")

    def _worker_my_payouts(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id): return
        if not self._require_role(user, Role.WORKER, m.chat.id): return
        total, count = self.assign.total_for_user(user.id)
        self.safe.send(m.chat.id,
                       f"ВАШИ ВЫПЛАТЫ\n\nВсего: {total} руб\nЗаказов: {count}")

    def _profile(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not user:
            return
        if user.blocked:
            self.safe.send(m.chat.id, "Вы заблокированы.", reply_markup=blocked_kb())
            return
        labels = {Role.WORKER.value: "Работник",
                  Role.CUSTOMER.value: "Заказчик",
                  Role.MODERATOR.value: "Модератор"}
        rating = user.rating if user.role == Role.WORKER.value else user.customer_rating
        text = (
            f"ПРОФИЛЬ\n\n"
            f"Имя: {user.name or 'не указано'}\n"
            f"Телефон: {user.phone or 'не указан'}\n"
            f"Роль: {labels.get(user.role, user.role or '—')}\n"
            f"Рейтинг: {rating}"
        )
        self.safe.send(m.chat.id, text)

    def _contact_mod_start(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not self._require_not_blocked(user, m.chat.id): return
        if user.role not in (Role.WORKER.value, Role.CUSTOMER.value):
            self.safe.send(m.chat.id, "Функция недоступна.")
            return
        self.states.set(m.from_user.id, "msg_to_mod", {})
        self.safe.send(m.chat.id, "Напишите сообщение модератору:\n(для отмены /cancel)")

    def _msg_to_mod(self, m, data: Dict) -> None:
        user = self.users.get_by_telegram(m.from_user.id)
        text = (f"СООБЩЕНИЕ ОТ {user.role if user else '?'}\n\n"
                f"От: {user.name if user and user.name else 'без имени'} "
                f"(ID {user.id if user else m.from_user.id})\n"
                f"Телефон: {user.phone if user and user.phone else 'не указан'}\n\n"
                f"{m.text}")
        self._notify_moderators(text)
        self.safe.send(m.chat.id, "Сообщение отправлено модератору.",
                       reply_markup=main_kb(m.from_user.id, self.config.moderator_ids))
        self.states.clear(m.from_user.id)

    def _blocked_contact_mod(self, m) -> None:
        user = self._get_user_or_none(m.from_user.id)
        if not user or not user.blocked:
            return
        self._notify_moderators(
            f"Пользователь {m.from_user.id} "
            f"({user.name or 'без имени'}) просит связи."
        )
        self.safe.send(m.chat.id, "Запрос отправлен модератору.")

    def _on_mod_command(self, m) -> None:
        uid = m.from_user.id
        text = m.text
        try:
            if text == "💰 Выплаты":
                total, count = self.orders.total_payouts()
                self.safe.send(m.chat.id,
                               f"ВСЕГО ВЫПЛАЧЕНО\n\n{total} руб\n{count} выплат")
            elif text == "🟡 Активные":
                orders = self.orders.list_active(10)
                if not orders:
                    self.safe.send(m.chat.id, "Нет активных заказов.")
                    return
                for o in orders:
                    self.safe.send(
                        m.chat.id,
                        f"Заказ #{o.id}\n{o.zakazchik_name}\n"
                        f"{o.address}\n{o.work_description}\n"
                        f"{o.status}\n{o.total_sum} руб",
                    )
            elif text == "✅ Завершённые":
                orders = self.orders.list_completed(20)
                if not orders:
                    self.safe.send(m.chat.id, "Нет завершённых заказов.")
                    return
                for o in orders:
                    self.safe.send(
                        m.chat.id,
                        f"Заказ #{o.id}\n{o.zakazchik_name}\n"
                        f"{o.address}\n{o.work_description}\n"
                        f"{o.total_sum} руб",
                    )
            elif text == "👥 Работники":
                workers = self.users.list_workers(20)
                if not workers:
                    self.safe.send(m.chat.id, "Нет работников.")
                    return
                msg = "РАБОТНИКИ:\n\n"
                for w in workers:
                    s = "на смене" if w.on_shift else "не на смене"
                    b = "заблокирован" if w.blocked else "активен"
                    msg += (f"ID {w.id}: {w.name}\n"
                            f"{w.phone}, рейтинг {w.rating}\n"
                            f"{s}, {b}\n")
                self.safe.send(m.chat.id, msg)
            elif text == "🏢 Заказчики":
                customers = self.users.list_customers(20)
                if not customers:
                    self.safe.send(m.chat.id, "Нет заказчиков.")
                    return
                msg = "ЗАКАЗЧИКИ:\n\n"
                for c in customers:
                    b = "заблокирован" if c.blocked else "активен"
                    msg += (f"ID {c.id}: {c.name}\n"
                            f"{c.phone}, рейтинг {c.customer_rating}\n"
                            f"{b}\n")
                self.safe.send(m.chat.id, msg)
            elif text == "📊 Статистика":
                stats = self.users.count()
                self.safe.send(
                    m.chat.id,
                    f"СТАТИСТИКА\n\n"
                    f"Всего: {stats['total']}\n"
                    f"Работников: {stats['workers']}\n"
                    f"Заказчиков: {stats['customers']}\n"
                    f"Заказов: {stats['orders']}",
                )
            elif text == "⭐ Оценить работника":
                self.states.set(uid, "mod_rate_worker", {"awaiting_id": True})
                self.safe.send(m.chat.id, "Введите ID работника:")
            elif text == "⭐ Оценить заказчика":
                self.states.set(uid, "mod_rate_customer", {"awaiting_id": True})
                self.safe.send(m.chat.id, "Введите ID заказчика:")
            elif text == "🔒 Блокировка":
                kb = ReplyKeyboardMarkup(resize_keyboard=True)
                kb.row(KeyboardButton("По ID"), KeyboardButton("По телефону"))
                kb.row(KeyboardButton("⬅️ Назад"))
                self.states.set(uid, "mod_block_method", {})
                self.safe.send(m.chat.id, "Выберите способ:", reply_markup=kb)
            elif text == "🔓 Разблокировка":
                self.states.set(uid, "mod_unblock_by_id", {})
                self.safe.send(m.chat.id, "Введите ID пользователя:")
        except Exception as e:
            self.logger.exception(f"mod cmd '{text}': {e}")
            self.safe.send(m.chat.id, "Ошибка.")

    def _mod_rate_worker_apply(self, m, data: Dict) -> None:
        if data.get("awaiting_id"):
            n = validate_positive_int(m.text, 1_000_000)
            if not n:
                self.safe.send(m.chat.id, "Введите число.",
                               reply_markup=moderator_kb())
                self.states.clear(m.from_user.id)
                return
            u = self.users.get_by_id(n)
            if not u or u.role != Role.WORKER.value:
                self.safe.send(m.chat.id, "Работник не найден.",
                               reply_markup=moderator_kb())
                self.states.clear(m.from_user.id)
                return
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton("+1"), KeyboardButton("-1"), KeyboardButton("0"))
            kb.row(KeyboardButton("⬅️ Назад"))
            self.states.set(m.from_user.id, "mod_rate_worker", {"user_id": u.id})
            self.safe.send(m.chat.id, f"{u.name} (рейтинг: {u.rating})",
                           reply_markup=kb)
            return
        if m.text not in ("+1", "-1", "0"):
            if m.text == "⬅️ Назад":
                self.states.clear(m.from_user.id)
                self.safe.send(m.chat.id, "Панель модератора:",
                               reply_markup=moderator_kb())
            else:
                self.safe.send(m.chat.id, "Нажмите кнопку.")
            return
        delta = {"+1": 1, "-1": -1, "0": 0}[m.text]
        user_id = data.get("user_id")
        new_rating = self.users.change_rating(user_id, delta)
        self.users.log_moderator_action(
            m.from_user.id, "rate_worker", user_id, f"delta={delta}"
        )
        self.states.clear(m.from_user.id)
        self.safe.send(m.chat.id, f"Рейтинг: {new_rating}",
                       reply_markup=moderator_kb())

    def _mod_rate_customer_apply(self, m, data: Dict) -> None:
        if data.get("awaiting_id"):
            n = validate_positive_int(m.text, 1_000_000)
            if not n:
                self.safe.send(m.chat.id, "Введите число.",
                               reply_markup=moderator_kb())
                self.states.clear(m.from_user.id)
                return
            u = self.users.get_by_id(n)
            if not u or u.role != Role.CUSTOMER.value:
                self.safe.send(m.chat.id, "Заказчик не найден.",
                               reply_markup=moderator_kb())
                self.states.clear(m.from_user.id)
                return
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton("+1"), KeyboardButton("-1"), KeyboardButton("0"))
            kb.row(KeyboardButton("⬅️ Назад"))
            self.states.set(m.from_user.id, "mod_rate_customer", {"user_id": u.id})
            self.safe.send(m.chat.id, f"{u.name} (рейтинг: {u.customer_rating})",
                           reply_markup=kb)
            return
        if m.text not in ("+1", "-1", "0"):
            if m.text == "⬅️ Назад":
                self.states.clear(m.from_user.id)
                self.safe.send(m.chat.id, "Панель модератора:",
                               reply_markup=moderator_kb())
            else:
                self.safe.send(m.chat.id, "Нажмите кнопку.")
            return
        delta = {"+1": 1, "-1": -1, "0": 0}[m.text]
        user_id = data.get("user_id")
        new_rating = self.users.change_customer_rating(user_id, delta)
        self.users.log_moderator_action(
            m.from_user.id, "rate_customer", user_id, f"delta={delta}"
        )
        self.states.clear(m.from_user.id)
        self.safe.send(m.chat.id, f"Рейтинг заказчика: {new_rating}",
                       reply_markup=moderator_kb())

    def _mod_block_choose_method(self, m, data: Dict) -> None:
        if m.text == "⬅️ Назад":
            self.states.clear(m.from_user.id)
            self.safe.send(m.chat.id, "Панель модератора:",
                           reply_markup=moderator_kb())
            return
        if m.text == "По ID":
            self.states.set(m.from_user.id, "mod_block_by_id", {})
            self.safe.send(m.chat.id, "Введите ID пользователя:")
        elif m.text == "По телефону":
            self.states.set(m.from_user.id, "mod_block_by_phone", {})
            self.safe.send(m.chat.id, "Введите номер телефона:")
        else:
            self.safe.send(m.chat.id, "Нажмите кнопку.")

    def _mod_block_by_id(self, m) -> None:
        n = validate_positive_int(m.text, 1_000_000)
        if not n:
            self.safe.send(m.chat.id, "Введите число.",
                           reply_markup=moderator_kb())
            self.states.clear(m.from_user.id)
            return
        u = self.users.get_by_id(n)
        if not u:
            self.safe.send(m.chat.id, "Пользователь не найден.",
                           reply_markup=moderator_kb())
            self.states.clear(m.from_user.id)
            return
        self.users.update_fields_by_id(u.id, {"blocked": 1})
        self.users.log_moderator_action(m.from_user.id, "block", u.id, "by_id")
        self.states.clear(m.from_user.id)
        self.safe.send(m.chat.id, f"{u.name} заблокирован.",
                       reply_markup=moderator_kb())
        self.safe.send(u.telegram_id, "Вы заблокированы.")

    def _mod_block_by_phone(self, m) -> None:
        phone = m.text.strip() if m.text else ""
        if not validate_phone(phone):
            self.safe.send(m.chat.id, "Некорректный телефон.",
                           reply_markup=moderator_kb())
            self.states.clear(m.from_user.id)
            return
        users = self.users.get_by_phone(phone)
        if not users:
            self.safe.send(m.chat.id, "Пользователь не найден.",
                           reply_markup=moderator_kb())
            self.states.clear(m.from_user.id)
            return
        for u in users:
            self.users.update_fields_by_id(u.id, {"blocked": 1})
            self.users.log_moderator_action(
                m.from_user.id, "block", u.id, f"by_phone={phone}"
            )
            self.safe.send(u.telegram_id, "Вы заблокированы.")
        self.states.clear(m.from_user.id)
        self.safe.send(m.chat.id, f"Заблокировано: {len(users)}.",
                       reply_markup=moderator_kb())

    def _mod_unblock_by_id(self, m) -> None:
        n = validate_positive_int(m.text, 1_000_000)
        if not n:
            self.safe.send(m.chat.id, "Введите число.",
                           reply_markup=moderator_kb())
            self.states.clear(m.from_user.id)
            return
        u = self.users.get_by_id(n)
        if not u or not u.blocked:
            self.safe.send(m.chat.id, "Заблокированный пользователь не найден.",
                           reply_markup=moderator_kb())
            self.states.clear(m.from_user.id)
            return
        self.users.update_fields_by_id(u.id, {"blocked": 0})
        self.users.log_moderator_action(m.from_user.id, "unblock", u.id, "")
        self.states.clear(m.from_user.id)
        self.safe.send(m.chat.id, f"{u.name} разблокирован.",
                       reply_markup=moderator_kb())
        self.safe.send(u.telegram_id, "Вы разблокированы.")

    def _on_callback(self, call) -> None:
        try:
            if not call.message:
                self.safe.answer_callback(call, "Сообщение устарело", True)
                return
            user = self._get_user_or_none(call.from_user.id)
            if not user or user.blocked:
                self.safe.answer_callback(call, "Доступ запрещён", True)
                return
            if not self.limiter.check(call.from_user.id, "callback", 40):
                self.safe.answer_callback(call, "Слишком часто", True)
                return

            action, ids = parse_callback(call.data)
            if not action:
                self.safe.answer_callback(call, "Неизвестная команда", True)
                return

            handler = {
                "take": self._cb_take,
                "confirm_place": self._cb_confirm_place,
                "cancel_take": self._cb_cancel_take,
                "i_paid": self._cb_i_paid,
                "confirm_payment": self._cb_confirm_payment,
                "send_photo": self._cb_send_photo,
                "approve": self._cb_approve,
                "reject": self._cb_reject,
                "confirm_payout": self._cb_confirm_payout,
                "cancel": self._cb_cancel_order,
                "complete": self._cb_complete,
                "contact_mod": self._cb_contact_mod,
                "contact_customer_order": self._cb_contact_customer_order,
                "contact_worker_order": self._cb_contact_worker_order,
                "send_msg": self._cb_send_msg,
            }.get(action)
            if handler:
                handler(call, user, ids)
            else:
                self.safe.answer_callback(call, "Неизвестная команда", True)
        except Exception as e:
            self.logger.exception(f"callback error: {e}")
            try:
                self.safe.answer_callback(call, "Ошибка", True)
            except Exception:
                pass

    def _cb_take(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.OPEN.value:
            self.safe.answer_callback(call, "Заказ уже не доступен", True)
            return
        if user.role != Role.WORKER.value:
            self.safe.answer_callback(call, "Только для работников", True)
            return
        if not user.agreement_accepted:
            self.safe.answer_callback(call, "Пройдите регистрацию", True)
            return
        ok = self.assign.take_order(order_id, user.id, order.payout_per_person)
        if not ok:
            self.safe.answer_callback(call, "Не удалось взять заказ", True)
            return
        if self.service.is_fully_staffed(order_id):
            self.orders.update_status(order_id, OrderStatus.READY_TO_PAY)
            self.safe.answer_callback(call, f"Заказ #{order_id} укомплектован!", True)
            self.safe.send(
                order.zakazchik_id,
                f"ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                f"Все работники собраны.\n{order.address}\n"
                f"{order.work_description}\n{order.total_sum} руб\n"
                f"Переведите по СБП: {self.config.sbp_phone}",
                reply_markup=payment_kb(order_id),
            )
            for wid in self.assign.list_user_ids(order_id):
                w = self.users.get_by_id(wid)
                if w:
                    self.safe.send(
                        w.telegram_id,
                        f"ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n"
                        f"{order.address}\n{order.work_description}\n"
                        f"{order.payout_per_person} руб",
                    )
            self._notify_moderators(
                f"ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n"
                f"{order.zakazchik_name}\n{order.address}\n"
                f"{order.work_description}\n{order.people} чел.\n"
                f"{order.total_sum} руб"
            )
        else:
            self.safe.answer_callback(call, f"Вы взяли заказ #{order_id}!", True)
        self.safe.edit(
            f"Вы взяли заказ #{order_id}!\nПодтвердите, что вы на месте.",
            call.message.chat.id, call.message.message_id,
            reply_markup=confirm_take_kb(order_id),
        )

    def _cb_confirm_place(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.status not in (
            OrderStatus.OPEN.value, OrderStatus.READY_TO_PAY.value
        ):
            self.safe.answer_callback(call, "Заказ уже не в этой стадии", True)
            return
        self.assign.confirm_place(order_id, user.id)
        self.safe.answer_callback(call, "Вы подтвердили место!", True)
        self.safe.edit(
            f"Вы на месте!\nВаша выплата: {order.payout_per_person} руб",
            call.message.chat.id, call.message.message_id,
        )
        if (order.status == OrderStatus.OPEN.value
                and self.service.are_all_confirmed(order_id)
                and self.service.is_fully_staffed(order_id)):
            self.orders.update_status(order_id, OrderStatus.READY_TO_PAY)
            self.safe.send(
                order.zakazchik_id,
                f"ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                f"Все подтвердили место.\n{order.address}\n"
                f"{order.work_description}\n{order.total_sum} руб\n"
                f"{self.config.sbp_phone}",
                reply_markup=payment_kb(order_id),
            )
            for wid in self.assign.list_user_ids(order_id):
                w = self.users.get_by_id(wid)
                if w:
                    self.safe.send(
                        w.telegram_id,
                        f"ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n"
                        f"{order.address}\n{order.work_description}\n"
                        f"{order.payout_per_person} руб",
                    )
            self._notify_moderators(
                f"ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n"
                f"{order.zakazchik_name}\n{order.address}\n"
                f"{order.work_description}\n{order.people} чел.\n"
                f"{order.total_sum} руб"
            )

    def _cb_cancel_take(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        self.assign.delete(order_id, user.id)
        self.safe.answer_callback(call, "Отказ от заказа", True)
        self.safe.edit("Вы отказались от заказа",
                       call.message.chat.id, call.message.message_id)

    def _cb_i_paid(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.READY_TO_PAY.value:
            self.safe.answer_callback(call, "Заказ не в статусе оплаты", True)
            return
        if user.id != order.zakazchik_id:
            self.safe.answer_callback(call, "Это не ваш заказ", True)
            return
        self.orders.update_status(order_id, OrderStatus.PAID)
        self.orders.set_paid_at(order_id)
        self.safe.answer_callback(call, "Оплата подтверждена!", True)
        self.safe.edit(
            f"Оплата заказа #{order_id} подтверждена!",
            call.message.chat.id, call.message.message_id,
        )
        self._notify_moderators(
            f"ЗАКАЗ #{order_id} ОПЛАЧЕН!\n"
            f"{order.zakazchik_name}\n{order.address}\n"
            f"{order.work_description}\n{order.total_sum} руб",
        )
        for m_id in self.config.moderator_ids:
            self.safe.send(
                m_id,
                f"ЗАКАЗ #{order_id} ОПЛАЧЕН!\n"
                f"{order.zakazchik_name}\n{order.address}\n"
                f"{order.work_description}\n{order.total_sum} руб",
                reply_markup=moderator_payment_kb(order_id),
            )

    def _cb_confirm_payment(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        if not self._is_moderator(user.telegram_id):
            self.safe.answer_callback(call, "Нет прав", True)
            return
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.PAID.value:
            self.safe.answer_callback(call, "Заказ не в статусе оплаты", True)
            return
        self.orders.update_status(order_id, OrderStatus.WORKING)
        self.users.log_moderator_action(
            user.telegram_id, "confirm_payment", None, f"order={order_id}"
        )
        self.safe.answer_callback(call, "Оплата подтверждена!", True)
        self.safe.edit(
            f"Оплата заказа #{order_id} подтверждена!",
            call.message.chat.id, call.message.message_id,
        )
        for wid in self.assign.list_user_ids(order_id):
            w = self.users.get_by_id(wid)
            if w:
                self.safe.send(
                    w.telegram_id,
                    f"ЗАКАЗ #{order_id} ОПЛАЧЕН!\n{order.address}\n"
                    f"{order.work_description}\n{order.hours} ч.\n"
                    f"После выполнения отправьте фото:",
                    reply_markup=worker_photo_kb(order_id),
                )
        self.safe.send(
            order.zakazchik_id,
            f"ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН!\n"
            f"{order.address}\n{order.work_description}\n"
            f"{order.hours} ч.",
        )

    def _cb_send_photo(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.WORKING.value:
            self.safe.answer_callback(call, "Заказ не в статусе работы", True)
            return
        self.states.set(user.telegram_id, f"waiting_photo_{order_id}", {})
        self.safe.answer_callback(call, "Отправьте фото", True)
        self.safe.send(call.message.chat.id, f"Отправьте фото для заказа #{order_id}")

    def _cb_approve(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.WAITING_APPROVAL.value:
            self.safe.answer_callback(call, "Заказ не ждёт подтверждения", True)
            return
        if user.id != order.zakazchik_id:
            self.safe.answer_callback(call, "Это не ваш заказ", True)
            return
        self.orders.update_status(order_id, OrderStatus.WAITING_PAYOUT)
        self.orders.set_completed_at(order_id)
        self.safe.answer_callback(call, "Работа подтверждена!", True)
        self.safe.edit(f"Заказ #{order_id} выполнен!",
                       call.message.chat.id, call.message.message_id)
        self._notify_moderators(
            f"ЗАКАЗ #{order_id} ВЫПОЛНЕН!\n{order.address}\n"
            f"{order.work_description}\n{order.total_sum} руб\n"
            f"{order.payout_per_person} руб/чел"
        )
        for m_id in self.config.moderator_ids:
            self.safe.send(
                m_id,
                f"ЗАКАЗ #{order_id} ВЫПОЛНЕН!\n{order.address}\n"
                f"{order.work_description}\n{order.total_sum} руб\n"
                f"{order.payout_per_person} руб/чел",
                reply_markup=moderator_payout_kb(order_id),
            )
        for wid in self.assign.list_user_ids(order_id):
            w = self.users.get_by_id(wid)
            if w:
                self.safe.send(
                    w.telegram_id,
                    f"Заказ #{order_id} одобрен!\n{order.payout_per_person} руб",
                )

    def _cb_reject(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.WAITING_APPROVAL.value:
            self.safe.answer_callback(call, "Заказ не ждёт подтверждения", True)
            return
        if user.id != order.zakazchik_id:
            self.safe.answer_callback(call, "Это не ваш заказ", True)
            return
        self.safe.answer_callback(call, "Работа отклонена", True)
        self.safe.edit(f"Работа по заказу #{order_id} отклонена.",
                       call.message.chat.id, call.message.message_id)
        self._notify_moderators(
            f"ЗАКАЗ #{order_id} ОТКЛОНЁН!\n{order.zakazchik_name}"
        )

    def _cb_confirm_payout(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        if not self._is_moderator(user.telegram_id):
            self.safe.answer_callback(call, "Нет прав", True)
            return
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.WAITING_PAYOUT.value:
            self.safe.answer_callback(call, "Заказ не в статусе выплаты", True)
            return
        self.orders.update_status(order_id, OrderStatus.COMPLETED)
        self.users.log_moderator_action(
            user.telegram_id, "confirm_payout", None, f"order={order_id}"
        )
        self.safe.answer_callback(call, "Выплата подтверждена!", True)
        self.safe.edit(
            f"Выплата по заказу #{order_id} подтверждена!",
            call.message.chat.id, call.message.message_id,
        )
        self.safe.send(order.zakazchik_id,
                       f"ЗАКАЗ #{order_id} ЗАВЕРШЁН!\nРаботники получили оплату.")
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        for wid in self.assign.list_user_ids(order_id):
            w = self.users.get_by_id(wid)
            if w:
                self.safe.send(
                    w.telegram_id,
                    f"ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n{order.payout_per_person} руб",
                )
                self.sheets.append_payout({
                    "date": now_str,
                    "order_id": order_id,
                    "customer_name": order.zakazchik_name,
                    "address": order.address,
                    "worker_name": w.name or "Работник",
                    "amount": order.payout_per_person,
                    "moderator_name": user.name or "Модератор",
                })
        self.sheets.append_commission({
            "date": now_str, "order_id": order_id, "amount": order.commission,
        })
        self.sheets.update_order_status(
            order_id, "Completed", completed_at=now_str
        )

    def _cb_cancel_order(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.zakazchik_id != user.id:
            self.safe.answer_callback(call, "Это не ваш заказ", True)
            return
        if order.status in (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value):
            self.safe.answer_callback(call, "Заказ уже завершён или отменён", True)
            return
        self.orders.update_status(order_id, OrderStatus.CANCELLED)
        self.safe.answer_callback(call, f"Заказ #{order_id} отменён!", True)
        self.safe.edit(f"ЗАКАЗ #{order_id} ОТМЕНЁН",
                       call.message.chat.id, call.message.message_id)
        for wid in self.assign.list_user_ids(order_id):
            w = self.users.get_by_id(wid)
            if w:
                self.safe.send(w.telegram_id, f"Заказ #{order_id} отменён заказчиком.")
        self.sheets.update_order_status(order_id, "Cancelled")

    def _cb_complete(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order or order.zakazchik_id != user.id:
            self.safe.answer_callback(call, "Это не ваш заказ", True)
            return
        if order.status != OrderStatus.WORKING.value:
            self.safe.answer_callback(call, "Заказ не в работе", True)
            return
        if not self.service.are_all_photos(order_id):
            self.safe.answer_callback(call, "Работники ещё не отправили фото.", True)
            return
        self.orders.update_status(order_id, OrderStatus.WAITING_APPROVAL)
        self.safe.answer_callback(call, "Заказ ожидает подтверждения!", True)
        self.safe.edit(
            f"Заказ #{order_id} выполнен!\nПодтвердите качество:",
            call.message.chat.id, call.message.message_id,
            reply_markup=approve_kb(order_id),
        )
        self.sheets.update_order_status(order_id, "Waiting approval")

    def _cb_contact_mod(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        self.states.set(user.telegram_id, "msg_to_mod", {"order_id": order_id})
        self.safe.answer_callback(call, "Напишите сообщение")
        self.safe.send(
            call.message.chat.id,
            f"Напишите сообщение модератору по заказу #{order_id}:\n"
            f"(для отмены /cancel)",
        )

    def _cb_contact_customer_order(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        order = self.orders.get(order_id)
        if not order:
            self.safe.answer_callback(call, "Заказ не найден", True)
            return
        self.states.set(user.telegram_id, "msg_to_user",
                        {"target_id": order.zakazchik_id, "order_id": order_id})
        self.safe.answer_callback(call, "Напишите сообщение")
        self.safe.send(
            call.message.chat.id,
            f"Напишите сообщение по заказу #{order_id}:\n(для отмены /cancel)",
        )

    def _cb_contact_worker_order(self, call, user: UserDTO, ids: List[int]) -> None:
        order_id = ids[0]
        worker_ids = self.assign.list_user_ids(order_id)
        if not worker_ids:
            self.safe.answer_callback(call, "Нет работников", True)
            return
        if len(worker_ids) > 1:
            kb = InlineKeyboardMarkup()
            for wid in worker_ids:
                w = self.users.get_by_id(wid)
                if w:
                    kb.add(InlineKeyboardButton(
                        f"{w.name or 'Работник'}",
                        callback_data=f"send_msg_{wid}_{order_id}"))
            self.safe.send(call.message.chat.id, "Выберите работника:", reply_markup=kb)
            self.safe.answer_callback(call)
        else:
            self.states.set(user.telegram_id, "msg_to_user",
                            {"target_id": worker_ids[0], "order_id": order_id})
            self.safe.answer_callback(call, "Напишите сообщение")
            self.safe.send(
                call.message.chat.id,
                f"Напишите сообщение по заказу #{order_id}:\n(для отмены /cancel)",
            )

    def _cb_send_msg(self, call, user: UserDTO, ids: List[int]) -> None:
        target_id = ids[0]
        order_id = ids[1] if len(ids) > 1 else 0
        self.states.set(user.telegram_id, "msg_to_user",
                        {"target_id": target_id, "order_id": order_id})
        self.safe.answer_callback(call, "Напишите сообщение")
        self.safe.send(call.message.chat.id, "Напишите сообщение:\n(для отмены /cancel)")

    def _on_photo(self, m) -> None:
        uid = m.from_user.id
        state, _ = self.states.get(uid)
        if not state or not state.startswith("waiting_photo_"):
            self.safe.send(m.chat.id, "Нет активного запроса на фото.")
            return
        try:
            order_id = int(state.split("_")[2])
        except (ValueError, IndexError):
            self.states.clear(uid)
            return
        file_id = m.photo[-1].file_id
        user = self.users.get_by_telegram(uid)
        if not user:
            return
        self.assign.set_photo(order_id, user.id, file_id)
        self.states.clear(uid)
        self.safe.send(m.chat.id, f"Фото для заказа #{order_id} сохранено!")
        order = self.orders.get(order_id)
        if order and order.status == OrderStatus.WORKING.value \
                and self.service.are_all_photos(order_id):
            self.orders.update_status(order_id, OrderStatus.WAITING_APPROVAL)
            self.safe.send(
                order.zakazchik_id,
                f"Все работники отправили фото!\nПодтвердите выполнение:",
                reply_markup=approve_kb(order_id),
            )
            self._notify_moderators(
                f"Все работники отправили фото по заказу #{order_id}!"
            )

    def _msg_to_user(self, m, data: Dict) -> None:
        target_id = data.get("target_id")
        order_id = data.get("order_id", 0)
        target = self.users.get_by_id(target_id) if target_id else None
        if not target:
            self.safe.send(m.chat.id, "Пользователь не найден.")
            self.states.clear(m.from_user.id)
            return
        order_text = f" по заказу #{order_id}" if order_id else ""
        self.safe.send(
            target.telegram_id,
            f"НОВОЕ СООБЩЕНИЕ{order_text}\n\nОт: {m.from_user.first_name}\n\n{m.text}",
        )
        self.messages_repo.save(
            from_user_id=self.users.get_by_telegram(m.from_user.id).id,
            to_user_id=target.id,
            order_id=order_id or None,
            text=m.text,
        )
        self.safe.send(m.chat.id, "Сообщение отправлено!")
        self.states.clear(m.from_user.id)

    def run(self) -> None:
        self.logger.info("Бот запущен!")
        self.logger.info(f"Модераторы: {self.config.moderator_ids}")
        self.logger.info(f"СБП: {self.config.sbp_phone}")

        def _shutdown(*_):
            self.logger.info("Получен сигнал завершения")
            self._running = False
            self.bot.stop_polling()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        while self._running:
            try:
                self.bot.polling(
                    none_stop=True, interval=1, timeout=60, long_polling_timeout=30
                )
            except Exception as e:
                if not self._running:
                    break
                self.logger.warning(f"Polling error: {e}. Рестарт через 5 сек.")
                time.sleep(5)
        self.logger.info("Бот остановлен корректно.")


def main() -> int:
    try:
        config = Config.from_env()
    except ValueError as e:
        print(f"\n{e}\n", file=sys.stderr)
        return 2

    logger = setup_logging(config.log_level)
    try:
        app = YurgaBot(config)
        app.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

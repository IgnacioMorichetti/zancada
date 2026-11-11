"""
Memoria de Zancada: historial de conversación en SQLite.

Cada mensaje (del usuario o del modelo) se guarda como una fila de la tabla
`mensajes`. Se usa aiosqlite, la versión asíncrona de sqlite3, para que las
operaciones sobre la base no bloqueen al bot mientras atiende a otros
usuarios.
"""

from pathlib import Path

import aiosqlite  # SQLite con soporte para async/await

# Archivo de la base de datos, al lado de este módulo. Usar la carpeta del
# archivo (y no la carpeta desde la que se ejecuta el bot) evita que se cree
# una base distinta si alguien corre "python zancada/bot.py" desde otro lugar.
# Está excluido del repositorio por .gitignore (*.db).
RUTA_DB = Path(__file__).resolve().parent / "zancada.db"

# Sentencias SQL que definen la estructura de la base.
# IF NOT EXISTS hace que puedan ejecutarse en cada arranque sin error.
ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensajes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,                -- orden de llegada
    user_id  INTEGER NOT NULL,                                 -- id de Telegram del usuario
    rol      TEXT    NOT NULL CHECK (rol IN ('user', 'model')), -- quién escribió
    texto    TEXT    NOT NULL,                                 -- contenido del mensaje
    fecha    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP        -- cuándo se guardó
);
-- Índice que acelera la búsqueda de los mensajes de un usuario en orden.
CREATE INDEX IF NOT EXISTS idx_mensajes_usuario ON mensajes (user_id, id);
"""


async def inicializar() -> None:
    """Crea la tabla y el índice si todavía no existen."""
    async with aiosqlite.connect(RUTA_DB) as db:
        await db.executescript(ESQUEMA)
        await db.commit()


async def guardar_intercambio(user_id: int, pregunta: str, respuesta: str) -> None:
    """Guarda juntos el mensaje del usuario y la respuesta del modelo."""
    async with aiosqlite.connect(RUTA_DB) as db:
        # Los signos ? son parámetros: SQLite inserta los valores de forma
        # segura, lo que evita la inyección de SQL.
        await db.executemany(
            "INSERT INTO mensajes (user_id, rol, texto) VALUES (?, ?, ?)",
            [(user_id, "user", pregunta), (user_id, "model", respuesta)],
        )
        await db.commit()


async def obtener_historial(user_id: int, limite: int) -> list[tuple[str, str]]:
    """Devuelve los últimos `limite` mensajes del usuario, del más viejo al más nuevo."""
    async with aiosqlite.connect(RUTA_DB) as db:
        # DESC + LIMIT trae los más recientes; después se invierten para que
        # el modelo lea la conversación en orden cronológico.
        cursor = await db.execute(
            "SELECT rol, texto FROM mensajes WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limite),
        )
        filas = await cursor.fetchall()
    return list(reversed(filas))


async def borrar_historial(user_id: int) -> int:
    """Borra la conversación de un usuario y devuelve cuántos mensajes eliminó."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute("DELETE FROM mensajes WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount

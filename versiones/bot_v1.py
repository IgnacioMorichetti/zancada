"""
Zancada v1 · tu coach de running en Telegram.

Qué hace esta versión (Clase 1, todavía sin IA):
  /start  -> saludo personalizado
  /help   -> lista de comandos
  /ritmo  -> calcula ritmo y predice tiempos (comando propio del dominio)
  texto   -> eco (lo reemplaza Gemini en la Clase 2)
  errores -> se registran en consola y el usuario recibe un aviso amable

Se ejecuta con:  python bot.py   (con el entorno virtual activado)
"""

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Etapa 1 · Leer el token desde .env (nunca escrito en el código)
# ---------------------------------------------------------------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zancada")
# httpx registra cada petición a Telegram en nivel INFO: lo bajamos para que
# la consola no se llene de ruido (y para no imprimir la URL con el token).
logging.getLogger("httpx").setLevel(logging.WARNING)

TEXTO_AYUDA = (
    "Esto es lo que puedo hacer por ahora:\n\n"
    "/start - Presentación\n"
    "/help - Esta ayuda\n"
    "/ritmo <km> <tiempo> - Calculo tu ritmo y te estimo otras distancias\n"
    "    Ejemplo: /ritmo 10 52:30\n\n"
    "Si me escribís cualquier otra cosa, por ahora te la repito. "
    "Muy pronto voy a poder conversar de verdad, consultar el clima "
    "para tu salida y registrar tus entrenamientos."
)

DISTANCIAS_CLASICAS = {"5K": 5.0, "10K": 10.0, "21K": 21.0975, "42K": 42.195}


# ---------------------------------------------------------------------------
# Lógica del dominio (funciones comunes, sin Telegram).
# Se pueden probar solas y en la Clase 3 Gemini las va a invocar.
# ---------------------------------------------------------------------------
def parsear_tiempo(texto: str) -> float:
    """Convierte '45', '45:30' o '1:05:00' en minutos (float)."""
    partes = texto.strip().split(":")
    if not 1 <= len(partes) <= 3 or not all(p.isdigit() for p in partes):
        raise ValueError(f"Tiempo inválido: {texto!r}")
    numeros = [int(p) for p in partes]
    if len(numeros) == 1:            # '45'      -> 45 minutos
        horas, minutos, segundos = 0, numeros[0], 0
    elif len(numeros) == 2:          # '45:30'   -> 45 min 30 s
        horas, (minutos, segundos) = 0, numeros
    else:                            # '1:05:00' -> 1 h 5 min
        horas, minutos, segundos = numeros
        if minutos >= 60:
            raise ValueError(f"Tiempo inválido: {texto!r}")
    if segundos >= 60:
        raise ValueError(f"Tiempo inválido: {texto!r}")
    total = horas * 60 + minutos + segundos / 60
    if total <= 0:
        raise ValueError("El tiempo tiene que ser mayor a cero")
    return total


def formatear_minutos(minutos: float) -> str:
    """45.5 -> '45:30'; 125.0 -> '2:05:00'."""
    total_seg = round(minutos * 60)
    h, resto = divmod(total_seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def calcular_ritmo(distancia_km: float, minutos: float) -> dict:
    """Ritmo (min/km), velocidad (km/h) y predicción de Riegel: T2 = T1 * (D2/D1)^1.06."""
    if distancia_km <= 0 or minutos <= 0:
        raise ValueError("Distancia y tiempo tienen que ser mayores a cero")
    predicciones = {
        nombre: formatear_minutos(minutos * (km / distancia_km) ** 1.06)
        for nombre, km in DISTANCIAS_CLASICAS.items()
    }
    return {
        "ritmo_min_km": formatear_minutos(minutos / distancia_km),
        "velocidad_kmh": round(distancia_km / (minutos / 60), 2),
        "predicciones": predicciones,
    }


# ---------------------------------------------------------------------------
# Etapas 2 a 4 · Handlers (cada uno es una corrutina: async def + await)
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /start."""
    nombre = update.effective_user.first_name
    logger.info("Nuevo /start de %s (id %s)", nombre, update.effective_user.id)
    await update.message.reply_text(
        f"¡Hola, {nombre}! 🏃 Soy Zancada, tu coach de running.\n\n"
        "Te ayudo a calcular ritmos, elegir el mejor horario para salir a correr "
        "y llevar el registro de tus entrenamientos.\n\n"
        "Probá con /ritmo 10 52:30 o escribí /help para ver todo lo que sé hacer."
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /help."""
    await update.message.reply_text(TEXTO_AYUDA)


async def ritmo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ritmo <km> <tiempo>. context.args trae las palabras que siguen al comando."""
    uso = "Usalo así: /ritmo <km> <tiempo>\nEjemplos: /ritmo 5 25  ·  /ritmo 21.1 1:52:00"
    if len(context.args) != 2:
        await update.message.reply_text(uso)
        return
    try:
        distancia = float(context.args[0].replace(",", "."))
        minutos = parsear_tiempo(context.args[1])
        resultado = calcular_ritmo(distancia, minutos)
    except ValueError:
        # Error esperable (el usuario escribió mal): se le explica, no se cae el bot.
        await update.message.reply_text("No pude entender esos datos. " + uso)
        return

    lineas = [
        f"📏 {distancia:g} km en {formatear_minutos(minutos)}",
        f"⏱️ Ritmo: {resultado['ritmo_min_km']} min/km",
        f"🚀 Velocidad: {resultado['velocidad_kmh']} km/h",
        "",
        "Con ese nivel podrías hacer aproximadamente:",
    ]
    lineas += [f"  • {nombre}: {t}" for nombre, t in resultado["predicciones"].items()]
    lineas.append("\n(Estimación de Riegel: más confiable entre distancias parecidas.)")
    await update.message.reply_text("\n".join(lineas))


async def eco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repite el texto. Solo recibe texto que NO es comando (ver filtro en main)."""
    await update.message.reply_text(f"Dijiste: {update.message.text}")


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier /comando que no registramos."""
    await update.message.reply_text("No conozco ese comando 🤔. Escribí /help para ver la lista.")


# ---------------------------------------------------------------------------
# Etapa 5 · Manejo de errores
# ---------------------------------------------------------------------------
async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Se llama cuando un handler lanza una excepción no controlada."""
    logger.error("Error procesando un update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Uy, me tropecé 😅. Ya quedó registrado el problema; probá de nuevo en un rato."
        )


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise SystemExit(
            "Falta TELEGRAM_TOKEN. Copiá .env.example como .env y pegá el token de BotFather."
        )

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # El orden importa: la Application entrega el update al primer handler que lo acepta.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("ritmo", ritmo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, eco))  # texto y NO comando
    app.add_handler(MessageHandler(filters.COMMAND, comando_desconocido))  # va último
    app.add_error_handler(manejar_error)

    logger.info("Zancada está en línea. Presioná Ctrl+C para detenerlo.")
    # Polling: el bot le pregunta a Telegram, una y otra vez, si hay mensajes nuevos.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

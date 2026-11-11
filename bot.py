"""
Zancada v3 · tu coach de running en Telegram, con Gemini y memoria.

Qué hace esta versión (Clase 2):
  /start   -> saludo personalizado
  /help    -> lista de comandos
  /ritmo   -> calcula ritmo y predice tiempos (comando propio del dominio)
  /olvidar -> borra la conversación guardada del usuario
  texto    -> lo responde Gemini (Interactions API sin estado), con el prompt
              de sistema de prompts.py y los últimos mensajes del usuario,
              que se guardan en SQLite (db.py) y sobreviven a los reinicios
  errores  -> se registran en consola y el usuario recibe un aviso amable

Se ejecuta con:  python bot.py   (con el entorno virtual activado)
"""

import logging
import os

from dotenv import load_dotenv
from google import genai                      # SDK oficial de Gemini
from telegram import Update
from telegram.constants import ChatAction     # acción "escribiendo..."
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db                                     # módulo propio: historial en SQLite
from prompts import PROMPT_SISTEMA            # prompt de sistema (prompts.py)

# ---------------------------------------------------------------------------
# Configuración: todo lo sensible o cambiante se lee del .env
# ---------------------------------------------------------------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Leer el modelo del .env permite cambiarlo sin tocar el código.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Cantidad de mensajes anteriores que se envían al modelo en cada consulta
# (20 mensajes = 10 preguntas y sus respuestas). Más memoria = consultas más
# lentas y más consumo de cuota.
MAX_MENSAJES_HISTORIAL = 20

# Longitud máxima de un mensaje de Telegram, en caracteres.
LIMITE_TELEGRAM = 4096

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("zancada")
# httpx registra cada petición en nivel INFO: lo bajamos para que la consola
# no se llene de ruido (y para no imprimir la URL con el token).
# "httpx" lo usa python-telegram-bot y "httpx2", el SDK de Gemini.
for nombre_logger in ("httpx", "httpx2"):
    logging.getLogger(nombre_logger).setLevel(logging.WARNING)

TEXTO_AYUDA = (
    "Esto es lo que puedo hacer:\n\n"
    "/start - Presentación\n"
    "/help - Esta ayuda\n"
    "/ritmo <km> <tiempo> - Calculo tu ritmo y te estimo otras distancias\n"
    "    Ejemplo: /ritmo 10 52:30\n"
    "/olvidar - Borro nuestra conversación y empezamos de cero\n\n"
    "Y, sobre todo, podés escribirme lo que quieras sobre tu entrenamiento: "
    "planes, ritmos, carreras, descanso o zapatillas. Me acuerdo de lo que hablamos."
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
# Conexión con Gemini (Interactions API, sin estado)
# ---------------------------------------------------------------------------
# Un único cliente para todo el programa: guarda la clave y reutiliza las
# conexiones HTTP en lugar de abrir una nueva en cada mensaje.
# Se crea en main(), después de verificar que la clave esté en el .env.
cliente_gemini: genai.Client | None = None


def armar_entrada(historial: list[tuple[str, str]], mensaje_nuevo: str) -> list[dict]:
    """
    Convierte el historial guardado en la lista de pasos (steps) que espera
    la Interactions API y agrega al final el mensaje nuevo del usuario.
    """
    tipo_de_paso = {"user": "user_input", "model": "model_output"}
    pasos = [
        {"type": tipo_de_paso[rol], "content": [{"type": "text", "text": texto}]}
        for rol, texto in historial
    ]
    pasos.append({"type": "user_input", "content": [{"type": "text", "text": mensaje_nuevo}]})
    return pasos


async def consultar_gemini(historial: list[tuple[str, str]], mensaje: str) -> str:
    """Envía a Gemini la conversación completa y devuelve el texto de la respuesta."""
    # .aio es la versión asíncrona: mientras Gemini piensa, el bot sigue
    # atendiendo a otros usuarios.
    interaccion = await cliente_gemini.aio.interactions.create(
        model=GEMINI_MODEL,
        system_instruction=PROMPT_SISTEMA,         # personalidad y reglas de Zancada
        input=armar_entrada(historial, mensaje),   # historial + mensaje nuevo
        store=False,                               # la memoria la maneja el bot, no Google
    )
    # Si la respuesta llega vacía, el bot nunca manda un mensaje en blanco.
    return interaccion.output_text or "No se me ocurrió qué responderte 🤔 ¿Me lo decís de otra forma?"


def describir_error(error: Exception) -> str:
    """Traduce un error de la API a un mensaje comprensible para el usuario."""
    codigo = getattr(error, "status_code", None)
    if codigo == 429:            # cuota superada
        return "Estoy recibiendo demasiadas consultas. Probá de nuevo en un minuto, por favor. ⏳"
    # Clave inválida o sin permiso: 401 o 403. Con una clave mal copiada la
    # API responde 400 "API key not valid", así que también se contempla.
    if codigo in (401, 403) or (codigo == 400 and "API key" in str(error)):
        return "Tengo un problema de configuración. Avisale a quien me administra. 🔧"
    # Cualquier otro caso: falla de red, error del servicio, modelo inexistente.
    return "Tuve un problema para pensar la respuesta. ¿Me lo preguntás de nuevo? 🙏"


# ---------------------------------------------------------------------------
# Handlers (cada uno es una corrutina: async def + await)
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /start."""
    nombre = update.effective_user.first_name
    logger.info("Nuevo /start de %s (id %s)", nombre, update.effective_user.id)
    await update.message.reply_text(
        f"¡Hola, {nombre}! 🏃 Soy Zancada, tu coach de running.\n\n"
        "Contame cómo venís corriendo y qué objetivo tenés: te ayudo a armar "
        "entrenamientos, elegir ritmos y preparar tu próxima carrera.\n\n"
        "Escribí /help para ver todo lo que sé hacer."
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


async def olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /olvidar: borra el historial del usuario."""
    borrados = await db.borrar_historial(update.effective_user.id)
    logger.info("Usuario %s borró %d mensajes", update.effective_user.id, borrados)
    await update.message.reply_text(
        "Listo, borré nuestra conversación y empezamos de cero. ¿En qué te ayudo? 🙂"
    )


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde con Gemini, teniendo en cuenta la conversación previa."""
    user_id = update.effective_user.id
    texto = update.message.text
    logger.info("Mensaje de %s: %s", user_id, texto)

    await update.message.chat.send_action(ChatAction.TYPING)

    # Paso 1: recuperar lo que ya se habló con este usuario.
    historial = await db.obtener_historial(user_id, MAX_MENSAJES_HISTORIAL)

    # Paso 2: consultar al modelo con el historial más el mensaje nuevo.
    try:
        respuesta = await consultar_gemini(historial, texto)
    except Exception as error:
        logger.error("Error al consultar a Gemini: %s", error)    # detalle, para quien desarrolla
        await update.message.reply_text(describir_error(error))   # mensaje amable, para el usuario
        # Si la consulta falló no se guarda nada: el historial nunca queda
        # con una pregunta sin su respuesta.
        return

    # Paso 3: guardar la pregunta y la respuesta para la próxima consulta.
    await db.guardar_intercambio(user_id, texto, respuesta)

    # Si la respuesta supera el límite de Telegram, se envía en partes.
    for inicio in range(0, len(respuesta), LIMITE_TELEGRAM):
        await update.message.reply_text(respuesta[inicio:inicio + LIMITE_TELEGRAM])


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier /comando que no registramos."""
    await update.message.reply_text("No conozco ese comando 🤔. Escribí /help para ver la lista.")


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Se llama cuando un handler lanza una excepción no controlada."""
    logger.error("Error procesando un update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Uy, me tropecé 😅. Ya quedó registrado el problema; probá de nuevo en un rato."
        )


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
async def al_iniciar(app: Application) -> None:
    """Se ejecuta una sola vez, dentro del bucle de eventos, antes del primer mensaje."""
    await db.inicializar()
    logger.info("Base de datos lista (%s).", db.RUTA_DB.name)


def main() -> None:
    global cliente_gemini

    faltantes = [
        nombre
        for nombre, valor in [("TELEGRAM_TOKEN", TELEGRAM_TOKEN), ("GEMINI_API_KEY", GEMINI_API_KEY)]
        if not valor
    ]
    if faltantes:
        raise SystemExit(
            f"Faltan variables en el .env: {', '.join(faltantes)}. "
            "Copiá .env.example como .env y completalas."
        )

    cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)

    # post_init corre al_iniciar cuando ya existe el bucle de eventos.
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(al_iniciar).build()

    # El orden importa: la Application entrega el update al primer handler que lo acepta.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("ritmo", ritmo))
    app.add_handler(CommandHandler("olvidar", olvidar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))  # texto y NO comando
    app.add_handler(MessageHandler(filters.COMMAND, comando_desconocido))         # va último
    app.add_error_handler(manejar_error)

    logger.info("Zancada v3 en línea con el modelo %s. Presioná Ctrl+C para detenerlo.", GEMINI_MODEL)
    # Polling: el bot le pregunta a Telegram, una y otra vez, si hay mensajes nuevos.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

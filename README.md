# Zancada 🏃 · coach de running en Telegram

Proyecto final de Sistemas Inteligentes Aplicados (ITU UNCuyo). Versión actual: **v3**: conversa con Gemini (Interactions API sin estado), tiene personalidad propia definida en un prompt de sistema y recuerda la conversación de cada usuario en SQLite, aunque el bot se reinicie.

## Archivos

| Archivo | Qué contiene |
|---|---|
| `bot.py` | El bot: comandos, consulta a Gemini y manejo de errores |
| `prompts.py` | El prompt de sistema (identidad, tarea y alcance, estilo, formato, honestidad) |
| `db.py` | El historial en SQLite: `inicializar`, `obtener_historial`, `guardar_intercambio`, `borrar_historial` |
| `prueba_gemini.py` | Prueba aislada de la clave y el modelo de Gemini |
| `prueba_db.py` | Prueba aislada del módulo de base de datos |
| `versiones/bot_v1.py` | Respaldo de la v1 (Hito 1, eco sin IA) |
| `.env.example` | Variables que necesita el bot, sin valores reales |
| `comandos_botfather.txt` | Textos para configurar el bot en BotFather |

El `.env` y la base `zancada.db` no se suben al repositorio (están en `.gitignore`): uno guarda las claves y la otra, conversaciones de personas reales.

## Puesta en marcha

1. **Creá tu bot de prueba** en Telegram con [@BotFather](https://t.me/BotFather): `/newbot`, un nombre visible (`Zancada`) y un usuario único que termine en `bot`. Guardá el token.
2. **Configurá el bot** en BotFather con los textos de `comandos_botfather.txt` (`/setcommands`, `/setdescription`, `/setabouttext`).
3. **Creá tu clave de Gemini** en [Google AI Studio](https://aistudio.google.com/apikey) (*Get API key*).
4. **Prepará el entorno** (en la terminal, dentro de esta carpeta):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows (PowerShell)
   source .venv/bin/activate       # Linux / macOS
   pip install -r requirements.txt
   ```

5. **Cargá las claves**: copiá `.env.example` como `.env` y completá `TELEGRAM_TOKEN` y `GEMINI_API_KEY`. El modelo se elige con `GEMINI_MODEL`.
6. **Probá la conexión con Gemini**: `python prueba_gemini.py` tiene que imprimir un consejo de una oración.
7. **Ejecutá** `python bot.py`. Cuando veas `Zancada v3 en línea`, escribile `/start` a tu bot.

## Qué responde la v3

| Mensaje | Handler | Respuesta |
|---|---|---|
| `/start` | `start` | Saludo personalizado con tu nombre |
| `/help` | `ayuda` | Lista de comandos |
| `/ritmo 10 52:30` | `ritmo` | Ritmo, velocidad y tiempos estimados para 5K a 42K |
| `/olvidar` | `olvidar` | Borra tu conversación guardada |
| texto común | `responder` | Respuesta de Gemini, con el prompt de sistema y tus últimos 20 mensajes |
| `/otracosa` | `comando_desconocido` | Sugiere `/help` |
| una excepción | `manejar_error` | La registra en consola y avisa al usuario |

## Cómo funciona la memoria

El modelo no recuerda nada entre una consulta y otra. En cada mensaje, el bot:

1. recupera de SQLite los últimos 20 mensajes de ese usuario (`MAX_MENSAJES_HISTORIAL`);
2. le envía a Gemini el prompt de sistema, ese historial y el mensaje nuevo, con `store=False`;
3. si la consulta salió bien, guarda la pregunta y la respuesta.

Si Gemini falla no se guarda nada, así el historial nunca queda con una pregunta sin respuesta. Según el error, el usuario recibe un aviso distinto: cuota superada (429), problema de clave (400, 401 o 403) o cualquier otra falla.

## Problemas frecuentes

- **`Faltan variables en el .env`**: el `.env` no existe, no está en la carpeta del proyecto o alguna variable está vacía o mal escrita.
- **`InvalidToken` / `Unauthorized`**: el token de Telegram está incompleto o fue revocado. Pedí uno nuevo en BotFather.
- **`Conflict: terminated by other getUpdates request`**: hay dos copias del bot corriendo con el mismo token. Cerrá una (por eso cada integrante usa su propio bot).
- **El bot responde "Tengo un problema de configuración"**: la clave de Gemini es inválida. Copiala de nuevo desde AI Studio.
- **El bot responde "Tuve un problema para pensar la respuesta" y la terminal muestra 404**: el nombre del modelo en `GEMINI_MODEL` no existe.
- **El bot responde "Estoy recibiendo demasiadas consultas"**: se superó la cuota del plan gratuito (429). Esperá un minuto.
- **`AttributeError: 'Client' object has no attribute 'interactions'`**: versión vieja del SDK. `pip install -U google-genai`.
- **En PowerShell, `Activate.ps1` no se puede ejecutar**: corré `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` una sola vez.

## Privacidad

Mientras se use el plan gratuito de Gemini, lo que se le envía puede usarse para mejorar los productos de Google: no le escribas al bot datos personales ni sensibles. Cada usuario puede borrar su conversación con `/olvidar`.

## Hoja de ruta

~~v2 Gemini con prompt de sistema~~ → ~~v3 historial en SQLite~~ → v4 function calling (clima con Open-Meteo, ritmo, registro) → v5 extracción estructurada de entrenamientos → v6 módulos avanzados → v7 webhooks.

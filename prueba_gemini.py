"""
Prueba aislada de la conexión con Gemini (Etapa 2.1).

Se ejecuta antes de levantar el bot para confirmar que la clave de API y el
modelo funcionan:
    python prueba_gemini.py

Un error 400, 401 o 403 indica un problema con la clave; un 404, un nombre de
modelo inexistente.
"""

import os

from dotenv import load_dotenv
from google import genai

load_dotenv()
cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Versión síncrona (sin await): en un script de prueba no hay otros usuarios.
interaccion = cliente.interactions.create(
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    input="Dame un consejo para mi primera salida a correr, en una sola oración.",
    store=False,
)
print(interaccion.output_text)

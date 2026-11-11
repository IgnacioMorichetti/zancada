"""
Prueba aislada del módulo db.py (Etapa 3.1).

Usa un usuario ficticio (id 1) y borra sus mensajes al terminar, así que no
toca las conversaciones reales:
    python prueba_db.py
"""

import asyncio

import db


async def main():
    await db.inicializar()
    await db.guardar_intercambio(1, "Hola", "¡Hola! Soy Zancada.")
    await db.guardar_intercambio(1, "¿Corro hoy?", "Depende de cómo te sientas.")
    print(await db.obtener_historial(1, 20))   # los cuatro mensajes, en orden
    print(await db.obtener_historial(1, 2))    # solo los dos últimos
    print("Borrados:", await db.borrar_historial(1))
    print(await db.obtener_historial(1, 20))   # lista vacía


asyncio.run(main())

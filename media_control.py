#!/usr/bin/env python3

import sys
from time import sleep

import Ice

# Cargamos el contrato v2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

# Credenciales del enunciado (deben estar en tu users.json)
USERNAME = "user"
PASSWORD = "secret"

def get_proxy(ic, property, cls):
    proxy = ic.propertyToProxy(property)
    if not proxy:
        raise RuntimeError(f'Property {property} not set')

    for _ in range(5):
        try:
            proxy.ice_ping()
            break
        except Ice.ConnectionRefusedException:
            sleep(0.5)

    object = cls.checkedCast(proxy)
    if object is None:
        raise RuntimeError(f'Invalid proxy for {property}')

    return object

# --- NUEVO MÉTODO HITO 2 ---
def authenticate_and_bind(server, render):
    """
    Realiza el flujo de autenticación del Hito 2:
    1. Autentica al usuario en el servidor.
    2. Obtiene la sesión (SecureStreamManager).
    3. Vincula el render pasando el servidor Y la sesión.
    """
    print(f"--- AUTENTICACIÓN (Usuario: {USERNAME}) ---")
    
    try:
        # 1. Autenticación (Factory pattern)
        # El cliente pide permiso al portero (AuthManager)
        session = server.authenticate(render, USERNAME, PASSWORD)
        print("¡Autenticación correcta! Sesión obtenida.")

        # 2. Vinculación (Ahora requiere 2 argumentos)
        # Le damos al render el servidor (para búsquedas) y la sesión (para streaming)
        render.bind_media_server(server, session)
        print("Render vinculado con sesión segura.")
        
        return session

    except Spotifice.AuthError as e:
        print(f"ERROR: Fallo de autenticación: {e.reason}")
        return None
    except Spotifice.BadReference as e:
        print(f"ERROR: Referencia inválida: {e.reason}")
        return None
# ---------------------------

def main(ic):
    try:
        server = get_proxy(ic, 'MediaServer.Proxy', Spotifice.MediaServerPrx)
        render = get_proxy(ic, 'MediaRender.Proxy', Spotifice.MediaRenderPrx)

        # Limpieza inicial
        render.stop()

        # --- PASO 1: AUTENTICACIÓN Y VINCULACIÓN (HITO 2) ---
        session = authenticate_and_bind(server, render)
        if not session:
            print("Abortando prueba debido a fallo de autenticación.")
            return

        print("\n--- 2. PROBANDO 'MediaServer' (PlaylistManager) ---")
        # Esto sigue funcionando igual (es público)
        playlists = server.get_all_playlists()
        if not playlists:
            print("ERROR: El servidor no devolvió playlists.")
            return

        print(f"Playlists encontradas ({len(playlists)}):")
        for p in playlists:
            print(f"  - {p.name} (ID: {p.id})")
        
        playlist_id = playlists[0].id
        print(f"\nObteniendo primera playlist: '{playlist_id}'")
        playlist = server.get_playlist(playlist_id)
        
        print("\n--- 3. PROBANDO 'MediaRender' (Reproducción Segura) ---")
        print(f"Cargando playlist '{playlist_id}'...")
        
        # El render internamente usará la 'session' que le pasamos en el bind
        render.load_playlist(playlist_id)
        
        print("Iniciando reproducción (play)...")
        render.play()
        sleep(5)

        print("Pausando...")
        render.pause()
        sleep(2)

        print("Reanudando...")
        render.play()
        sleep(3)

        print("Parando...")
        render.stop()

        # --- PASO 4: LIMPIEZA (HITO 2) ---
        print("\n--- 4. CERRANDO SESIÓN ---")
        # Al desvincular, el render debería cerrar la sesión si lo implementamos así
        render.unbind_media_server()
        
        # Opcionalmente, podemos cerrar la sesión explícitamente desde el cliente
        # para probar que el método existe, aunque el render ya debería haberlo hecho.
        try:
            session.close() 
            print("Sesión cerrada correctamente.")
        except Ice.ObjectNotExistException:
            print("La sesión ya fue cerrada por el render (Comportamiento correcto).")

        print("\n--- ¡Prueba de Hito 2 superada! ---")

    except Exception as e:
        print(f"\n--- !!! HA OCURRIDO UN ERROR !!! ---")
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit("Usage: media_control.py <config-file>")

    with Ice.initialize(sys.argv[1]) as communicator:
        main(communicator)
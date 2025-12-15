#!/usr/bin/env python3

import logging
import sys
from pathlib import Path
import json  # --- NUEVO HITO 1 ---
import hashlib  # --- NUEVO HITO 2 ---
import secrets  # --- NUEVO HITO 2 ---

import Ice
from Ice import identityToString as id2str

# --- MODIFICADO HITO 1 ---
# Cargamos el nuevo contrato v1
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MediaServer")


class StreamedFile:
    def __init__(self, track_info, media_dir):
        self.track = track_info
        filepath = media_dir / track_info.filename

        try:
            self.file = open(filepath, 'rb')
        except Exception as e:
            raise Spotifice.IOError(track_info.filename, f"Error opening media file: {e}")

    def read(self, size):
        return self.file.read(size)

    def close(self):
        try:
            if self.file:
                self.file.close()
        except Exception as e:
            logger.error(f"Error closing file for track '{self.track.id}': {e}")

    def __repr__(self):
        return f"<StreamState '{self.track.id}'>"

class SecureStreamManagerI(Spotifice.SecureStreamManager):
    def __init__(self, username, user_data, media_dir, tracks):
        """
        Representa una sesión autenticada.
        Maneja el streaming para UN único usuario.
        """
        self.username = username
        self.user_data = user_data
        self.media_dir = media_dir
        self.tracks = tracks
        
        # HITO 2: Usamos una variable simple, no un diccionario.
        # Solo gestionamos un fichero a la vez para este usuario.
        self.current_stream: StreamedFile = None

    # --- Interfaz Session ---

    def get_user_info(self, current=None):
        logger.info(f"Retrieving info for user '{self.username}'")
        return Spotifice.UserInfo(
            username=self.username,
            fullname=self.user_data.get('fullname', ''),
            email=self.user_data.get('email', ''),
            is_premium=self.user_data.get('is_premium', False),
            created_at=0 
        )

    def close(self, current=None):
        logger.info(f"Closing session for user '{self.username}'")
        self.close_stream(current)
        # Nos eliminamos del adaptador para liberar memoria
        current.adapter.remove(current.id)

    # --- Interfaz SecureStreamManager (Adaptada del Hito 1) ---

    def open_stream(self, track_id, current=None):
        # 1. Validación de pista (igual que antes)
        if track_id not in self.tracks:
            raise Spotifice.TrackError(track_id, "Track not found")

        # 2. Si ya había uno abierto, lo cerramos primero (lógica nueva)
        self.close_stream(current)

        # 3. Abrimos el nuevo fichero (sin usar render_id)
        try:
            self.current_stream = StreamedFile(self.tracks[track_id], self.media_dir)
            logger.info(f"Stream opened for track '{track_id}' (User: {self.username})")
        except Exception as e:
            # Capturamos error al abrir fichero
            raise Spotifice.IOError(track_id, f"Could not open file: {e}")

    def close_stream(self, current=None):
        # Lógica simplificada: solo miramos la variable local
        if self.current_stream:
            self.current_stream.close()
            track_id = self.current_stream.track.id
            self.current_stream = None
            logger.info(f"Stream closed for track '{track_id}' (User: {self.username})")

    def get_audio_chunk(self, chunk_size, current=None):
        # Comprobación simple
        if not self.current_stream:
            raise Spotifice.StreamError(reason="No stream open")

        try:
            data = self.current_stream.read(chunk_size)
            if not data:
                logger.info(f"Track finished: {self.current_stream.track.id}")
                self.close_stream(current)
            return data

        except Exception as e:
            raise Spotifice.IOError(
                self.current_stream.track.filename, f"Error reading file: {e}")
        
class MediaServerI(Spotifice.MediaServer):
    # --- MODIFICADO HITO 1 ---
    # El constructor ahora también acepta el directorio de playlists
    def __init__(self, media_dir, playlists_dir, users_file):
        self.media_dir = Path(media_dir)
        self.tracks = {}
        

        # --- NUEVO HITO 1 ---
        self.playlists_dir = Path(playlists_dir)
        self.playlists = {}  # Diccionario para almacenar las playlists cargadas
        # ---------------------
        self.users_file = Path(users_file)
        self.users = {}
        # Cargamos primero la música
        self.load_media()
        # Y después las playlists (para poder validar los tracks)
        self.load_playlists()  # --- NUEVO HITO 1 ---
        self.load_users()      # --- NUEVO HITO 2 ---

    def ensure_track_exists(self, track_id):
        if track_id not in self.tracks:
            raise Spotifice.TrackError(track_id, "Track not found")

    def load_media(self):
        for filepath in sorted(Path(self.media_dir).iterdir()):
            if not filepath.is_file() or filepath.suffix.lower() != ".mp3":
                continue

            self.tracks[filepath.name] = self.track_info(filepath)

        logger.info(f"Load media:  {len(self.tracks)} tracks")

    # --- MÉTODO TOTALMENTE NUEVO HITO 1 ---
    def load_playlists(self):
        """
        Carga las definiciones de las playlists desde los ficheros JSON.
        Valida que las pistas existan en self.tracks.
        """
        logger.info(f"Loading playlists from '{self.playlists_dir}'...")
        try:
            for filepath in self.playlists_dir.glob('*.playlist'):
                logger.info(f"Processing playlist: {filepath.name}")
                with open(filepath, 'r') as f:
                    data = json.load(f)

                    # --- Validación Hito 1 ---
                    # El enunciado pide omitir pistas que no existan.
                    valid_track_ids = []
                    for track_id in data.get('track_ids', []):
                        if track_id in self.tracks:
                            valid_track_ids.append(track_id)
                        else:
                            logger.warning(
                                f"Track '{track_id}' in playlist '{data.get('id')}' not found. Skipping.")

                    # El struct Playlist define created_at como 'long' (int).
                    # El JSON de ejemplo tiene un string ("25-05-2011").
                    # Para evitar errores de tipo, lo dejaremos en 0 por ahora.
                    playlist = Spotifice.Playlist(
                        id=data.get('id', ''),
                        name=data.get('name', ''),
                        description=data.get('description', ''),
                        owner=data.get('owner', ''),
                        created_at=0,  # Placeholder por el tipo 'long'
                        track_ids=valid_track_ids  # Usamos la lista validada
                    )
                    
                    if playlist.id:
                        self.playlists[playlist.id] = playlist
                    else:
                        logger.warning(f"Skipping playlist {filepath.name} with no ID.")

        except Exception as e:
            logger.error(f"Failed to load playlists: {e}")

        logger.info(f"Load playlists: {len(self.playlists)} playlists")
    # ------------------------------------

    # --- NUEVO MÉTODO HITO 2 ---
    def load_users(self):
        """
        Carga la base de datos de usuarios desde el fichero JSON.
        """
        logger.info(f"Loading users from '{self.users_file}'...")
        try:
            with open(self.users_file, 'r') as f:
                # El JSON es un diccionario donde la clave es el username
                self.users = json.load(f)
                
            logger.info(f"Loaded {len(self.users)} users.")
            
        except FileNotFoundError:
            logger.error(f"Users file not found: {self.users_file}")
            # Dependiendo de lo estricto que quieras ser, podrías lanzar error o iniciar vacío
            self.users = {} 
        except json.JSONDecodeError:
            logger.error(f"Error parsing users file: {self.users_file}")
            self.users = {}
        except Exception as e:
            logger.error(f"Unexpected error loading users: {e}")
    # --------------------------

    # --- NUEVO MÉTODO HITO 2 ---
    @staticmethod
    def verify_password(password, salt, digest):
        """
        Verifica si la contraseña coincide con el hash almacenado.
        Lógica: MD5(password + salt) == digest
        """

        data = (password + salt).encode('utf-8')
        calc_digest = hashlib.md5(data).hexdigest()

        return secrets.compare_digest(calc_digest, digest)
    # ---------------------------

    #--- NUEVO HITO 2 ---
    def authenticate(self, media_render, username, password, current=None):
        """
        Valida las credenciales y crea una sesión segura.
        """
        logger.info(f"Authentication request for user: '{username}'")

        # --- VALIDACIÓN NUEVA (Uso de media_render) ---
        # El contrato dice que podemos lanzar BadReference
        if not media_render:
             logger.error("Authentication failed: Null MediaRender proxy")
             raise Spotifice.BadReference("MediaRender proxy cannot be null")
        
        try:
            # Comprobamos si el render está accesible
            media_render.ice_ping()
        except Exception as e:
            logger.error(f"Authentication failed: Unreachable MediaRender: {e}")
            raise Spotifice.BadReference(f"MediaRender is not reachable: {e}")
        # ---------------------------------------------

        # 1. Validar si el usuario existe
        if username not in self.users:
            logger.warning(f"User '{username}' not found.")
            raise Spotifice.AuthError(username, "Invalid credentials")

        # 2. Validar contraseña
        user_data = self.users[username]
        if not self.verify_password(password, user_data['salt'], user_data['digest']):
            logger.warning(f"Invalid password for user '{username}'.")
            raise Spotifice.AuthError(username, "Invalid credentials")

        logger.info(f"User '{username}' authenticated successfully.")

        # 3. Crear la sesión (SecureStreamManagerI)
        session_servant = SecureStreamManagerI(username, user_data, self.media_dir, self.tracks)

        # 4. Registrar el sirviente dinámicamente
        proxy = current.adapter.addWithUUID(session_servant)

        return Spotifice.SecureStreamManagerPrx.checkedCast(proxy)
    # ---------------------

    @staticmethod
    def track_info(filepath):
        return Spotifice.TrackInfo(
            id=filepath.name,
            title=filepath.stem,
            filename=filepath.name)

    # ---- MusicLibrary (sin cambios) ----
    def get_all_tracks(self, current=None):
        return list(self.tracks.values())

    def get_track_info(self, track_id, current=None):
        self.ensure_track_exists(track_id)
        return self.tracks[track_id]
    # ------------------------------------

    # ELIMINADO: open_stream, close_stream, get_audio_chunk

    # ---- PlaylistManager (NUEVO HITO 1) ----
    # Esta es la implementación de la nueva interfaz
    # que heredamos de Spotifice.MediaServer.

    def get_all_playlists(self, current=None):
        """Devuelve una lista de todas las playlists cargadas."""
        logger.info("Serving all playlists")
        return list(self.playlists.values())

    def get_playlist(self, playlist_id, current=None):
        """Devuelve una playlist específica por su ID."""
        logger.info(f"Serving playlist '{playlist_id}'")
        try:
            return self.playlists[playlist_id]
        except KeyError:
            # Si no se encuentra, lanzamos la excepción definida en el .ice
            logger.error(f"Playlist not found: {playlist_id}")
            raise Spotifice.PlaylistError(playlist_id, "Playlist not found")
    # ------------------------------------------


def main(ic):
    properties = ic.getProperties()
    media_dir = properties.getPropertyWithDefault(
        'MediaServer.Content', 'media')

    # --- MODIFICADO HITO 1 ---
    # Leemos la nueva propiedad del fichero de configuración
    playlists_dir = properties.getPropertyWithDefault(
        'MediaServer.Playlists', 'playlists')
    
    # 3. Fichero de Usuarios (NUEVO HITO 2)
    users_file = properties.getPropertyWithDefault(
        'MediaServer.UsersFile', 'users.json')
    
    # Pasamos ambos directorios al constructor
    servant = MediaServerI(Path(media_dir), Path(playlists_dir), Path(users_file))
    # -------------------------

    adapter = ic.createObjectAdapter("MediaServerAdapter")
    proxy = adapter.add(servant, ic.stringToIdentity("mediaServer1"))
    logger.info(f"MediaServer: {proxy}")

    adapter.activate()
    ic.waitForShutdown()

    logger.info("Shutdown")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: media_server.py <config-file>")

    try:
        with Ice.initialize(sys.argv[1]) as communicator:
            main(communicator)
    except KeyboardInterrupt:
        logger.info("Server interrupted by user.")
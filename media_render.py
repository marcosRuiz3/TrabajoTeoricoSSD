#!/usr/bin/env python3

import logging
import sys
from contextlib import contextmanager

import Ice
from Ice import identityToString as id2str

from gst_player import GstPlayer

# --- MODIFICADO HITO 2 ---
# Cargamos el nuevo contrato v2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MediaRender")


class MediaRenderI(Spotifice.MediaRender):
    def __init__(self, player):
        self.player = player
        self.server: Spotifice.MediaServerPrx = None
        
        # --- NUEVO HITO 2 ---
        # Variable para guardar la sesión de streaming segura
        self.stream_manager: Spotifice.SecureStreamManagerPrx = None
        # --------------------
        
        self.current_track = None

        # Identidad del render (Ya no es crítica para el streaming en v2, pero la mantenemos por si acaso)
        self.render_identity: Ice.Identity = None

        # Estado de reproducción
        self.state = Spotifice.PlaybackState.STOPPED
        self.repeat = False

        # Estado de la playlist
        self.current_playlist_ids = []
        self.current_track_index = -1

        # Historial para 'previous'
        self.history = []

    def ensure_player_stopped(self):
        if self.state == Spotifice.PlaybackState.PLAYING:
            raise Spotifice.PlayerError(reason="Already playing")

    def ensure_server_bound(self):
        if not self.server:
            raise Spotifice.BadReference(reason="No MediaServer bound")

    # --- RenderConnectivity (MODIFICADO HITO 2) ---

    def bind_media_server(self, media_server, stream_manager, current=None):
        # 1. Validar servidor principal (MusicLibrary/PlaylistManager)
        try:
            proxy = media_server.ice_timeout(500)
            proxy.ice_ping()
        except Ice.ConnectionRefusedException as e:
            raise Spotifice.BadReference(reason=f"MediaServer not reachable: {e}")

        # 2. Validar gestor de streaming (Sesión) - NUEVO HITO 2
        if not stream_manager:
             raise Spotifice.BadReference(reason="SecureStreamManager proxy cannot be null")
        try:
            sm_proxy = stream_manager.ice_timeout(500)
            sm_proxy.ice_ping()
        except Ice.ConnectionRefusedException as e:
            raise Spotifice.BadReference(reason=f"SecureStreamManager not reachable: {e}")

        # 3. Guardar ambas referencias
        self.server = media_server
        self.stream_manager = stream_manager
        
        logger.info(f"Bound to MediaServer with active session.")

    def unbind_media_server(self, current=None):
        self.stop(current)
        
        # --- NUEVO HITO 2 ---
        # Si tenemos una sesión activa, la cerramos 
        if self.stream_manager:
            try:
                logger.info("Closing session...")
                self.stream_manager.close() # Esto destruye el objeto en el servidor
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
            self.stream_manager = None
        # --------------------

        self.server = None
        self.current_playlist_ids = []
        self.current_track_index = -1
        self.history = []
        logger.info("Unbound MediaServer")

    # --- ContentManager ---

    def load_track(self, track_id, current=None):
        self.ensure_server_bound()

        try:
            with self.keep_playing_state(current):
                self.current_track = self.server.get_track_info(track_id)

                self.current_playlist_ids = []
                self.current_track_index = -1
                
                if not self.history or self.history[-1] != track_id:
                    self.history.append(track_id)

            logger.info(f"Current track set to: {self.current_track.title}")

        except Spotifice.TrackError as e:
            logger.error(f"Error setting track: {e.reason}")
            raise

    def get_current_track(self, current=None):
        return self.current_track

    def load_playlist(self, playlist_id, current=None):
        self.ensure_server_bound()
        logger.info(f"Loading playlist: {playlist_id}")

        try:
            with self.keep_playing_state(current):
                playlist = self.server.get_playlist(playlist_id)
                if not playlist.track_ids:
                    raise Spotifice.PlaylistError(playlist_id, "Playlist is empty")

                self.current_playlist_ids = playlist.track_ids
                self.current_track_index = 0
                self.history = []

                first_track_id = self.current_playlist_ids[0]
                self.current_track = self.server.get_track_info(first_track_id)
                self.history.append(first_track_id)

                logger.info(f"Playlist '{playlist.name}' loaded. Current track: {self.current_track.title}")

        except (Spotifice.PlaylistError, Spotifice.TrackError) as e:
            logger.error(f"Error loading playlist: {e.reason}")
            self.current_playlist_ids = []
            self.current_track_index = -1
            raise

    # --- PlaybackController ---

    @contextmanager
    def keep_playing_state(self, current):
        was_playing = self.state == Spotifice.PlaybackState.PLAYING
        if was_playing:
            self.stop(current)
        try:
            yield
        finally:
            if was_playing:
                self.play(current)

    def play(self, current=None):
        # Guardamos identidad por si acaso, aunque en v2 ya no es crítica
        if current:
            self.render_identity = current.id
        
        # --- MODIFICADO HITO 2 ---
        def get_chunk_hook(chunk_size):
            try:
                # Usamos stream_manager y YA NO pasamos la identidad
                return self.stream_manager.get_audio_chunk(chunk_size)
            except Spotifice.IOError as e:
                logger.error(e)
            except Ice.Exception as e:
                logger.critical(e)
        # -------------------------

        if self.state == Spotifice.PlaybackState.PAUSED:
            logger.info("Resuming playback...")
            self.player.resume()
            self.state = Spotifice.PlaybackState.PLAYING
            return

        self.ensure_player_stopped()
        self.ensure_server_bound()

        if not self.current_track:
            raise Spotifice.TrackError(reason="No track loaded")

        try:
            # --- MODIFICADO HITO 2 ---
            # Usamos stream_manager y YA NO pasamos la identidad
            self.stream_manager.open_stream(self.current_track.id)
            # -------------------------
        except Spotifice.BadIdentity as e:
            logger.error(f"Error starting stream: {e.reason}")
            raise Spotifice.StreamError(reason="Stream setup failed")

        self.player.configure(get_chunk_hook, self._on_song_finished)
        
        if not self.player.confirm_play_starts():
            raise Spotifice.PlayerError(reason="Failed to confirm playback")

        self.state = Spotifice.PlaybackState.PLAYING
        logger.info(f"Playing: {self.current_track.title}")

    def stop(self, current=None):
        # --- MODIFICADO HITO 2 ---
        # Usamos stream_manager
        if self.stream_manager:
            try:
                self.stream_manager.close_stream()
            except Exception:
                pass # Ignoramos errores al cerrar
        # -------------------------

        if not self.player.stop():
            raise Spotifice.PlayerError(reason="Failed to confirm stop")
        
        self.state = Spotifice.PlaybackState.STOPPED
        logger.info("Stopped")

    def pause(self, current=None):
        if self.state != Spotifice.PlaybackState.PLAYING:
            logger.warning("Pause called but not playing.")
            return

        self.player.pause()
        self.state = Spotifice.PlaybackState.PAUSED
        logger.info("Paused")

    def get_status(self, current=None):
        track_id = self.current_track.id if self.current_track else ""
        return Spotifice.PlaybackStatus(
            state=self.state,
            current_track_id=track_id,
            repeat=self.repeat
        )

    def set_repeat(self, value, current=None):
        self.repeat = value
        logger.info(f"Repeat set to {self.repeat}")

    def next(self, current=None):
        if self.current_track_index == -1:
            logger.warning("Next called without a playlist loaded.")
            raise Spotifice.PlaylistError("next", "No playlist loaded")

        next_index = self.current_track_index + 1

        if next_index < len(self.current_playlist_ids):
            self.current_track_index = next_index
        elif self.repeat:
            self.current_track_index = 0
        else:
            logger.info("End of playlist reached. Not advancing.")
            return False

        track_id = self.current_playlist_ids[self.current_track_index]
        logger.info(f"Advancing to next track: {track_id}")

        with self.keep_playing_state(current):
            self.ensure_server_bound()
            self.current_track = self.server.get_track_info(track_id)
            if not self.history or self.history[-1] != track_id:
                self.history.append(track_id)
        
        return True

    def previous(self, current=None):
        if len(self.history) < 2:
            logger.info("No previous track in history.")
            return

        self.history.pop()
        prev_track_id = self.history.pop()

        logger.info(f"Going to previous track: {prev_track_id}")
        
        self.current_track_index = -1 
        if prev_track_id in self.current_playlist_ids:
             self.current_track_index = self.current_playlist_ids.index(prev_track_id)

        with self.keep_playing_state(current):
            self.ensure_server_bound()
            self.current_track = self.server.get_track_info(prev_track_id)
            self.history.append(prev_track_id)

    def _on_song_finished(self):
        logger.info("Hook: Song finished.")
        
        # --- MODIFICADO HITO 2 ---
        # Usamos stream_manager para cerrar
        if self.stream_manager:
            try:
                self.stream_manager.close_stream()
            except Exception:
                pass
        # -------------------------
        
        simulated_current = Ice.Current(id=self.render_identity)

        if self.repeat and not self.current_playlist_ids:
            logger.info("Hook: Repeating single track.")
            self.state = Spotifice.PlaybackState.PLAYING 
            self.play(simulated_current) 
            return

        if self.current_track_index != -1:
            logger.info("Hook: Checking playlist for next track.")
            self.state = Spotifice.PlaybackState.PLAYING
            if self.next(simulated_current):
                return

        logger.info("Hook: Playback finished.")
        self.state = Spotifice.PlaybackState.STOPPED


def main(ic, player):
    servant = MediaRenderI(player)

    adapter = ic.createObjectAdapter("MediaRenderAdapter")
    proxy = adapter.add(servant, ic.stringToIdentity("mediaRender1"))
    logger.info(f"MediaRender: {proxy}")

    adapter.activate()
    ic.waitForShutdown()

    logger.info("Shutdown")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: media_render.py <config-file>")

    player = GstPlayer()
    player.start()
    try:
        with Ice.initialize(sys.argv[1]) as communicator:
            main(communicator, player)
    except KeyboardInterrupt:
        logger.info("Server interrupted by user.")
    finally:
        player.shutdown()
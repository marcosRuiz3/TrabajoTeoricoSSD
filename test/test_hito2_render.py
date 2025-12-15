import json
import hashlib
import secrets
import os
import Ice

# Aseguramos cargar el contrato v2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore

from gst_player import GstPlayer
from media_render import main as render_main
from media_server import main as server_main
from .icetest import IceTestCase

class TestHito2Render(IceTestCase):
    render_port = 10001
    server_port = 10000
    users_file = 'test/users_render_test.json'

    def setUp(self):
        # 1. Configuración de usuarios para el servidor
        salt = secrets.token_hex(8)
        password = "secret"
        digest = hashlib.md5((password + salt).encode('utf-8')).hexdigest()
        users_data = {"user": {"salt": salt, "digest": digest, "fullname": "U", "email": "e", "is_premium": False, "created_at": ""}}
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f)

        # 2. Arrancar Servidor
        server_props = {
            'MediaServerAdapter.Endpoints': f'tcp -p {self.server_port}',
            'MediaServer.Content': 'test/media',
            'MediaServer.Playlists': 'test/playlists',
            'MediaServer.UsersFile': self.users_file
        }
        self.create_server(server_main, server_props)
        
        # 3. Arrancar Render
        player = GstPlayer()
        player.start()
        self.addCleanup(player.shutdown)
        render_props = {'MediaRenderAdapter.Endpoints': f'tcp -p {self.render_port}'}
        self.create_server(render_main, render_props, player)

        # 4. Proxies
        self.server = self.create_proxy(f'mediaServer1:default -p {self.server_port} -t 500', Spotifice.MediaServerPrx)
        self.render = self.create_proxy(f'mediaRender1:default -p {self.render_port} -t 500', Spotifice.MediaRenderPrx)

        # 5. Obtener sesión válida (necesaria para bind)
        self.valid_session = self.server.authenticate(self.render, "user", "secret")

    def tearDown(self):
        if os.path.exists(self.users_file):
            os.remove(self.users_file)
        super().tearDown()

    def test_bind_media_server_v2(self):
        """Prueba vinculación con Servidor + Sesión."""
        # Esto debería funcionar
        self.render.bind_media_server(self.server, self.valid_session)
        
        # Limpieza
        self.render.unbind_media_server()

    def test_bind_fail_invalid_session(self):
        """Prueba que falla si pasamos una sesión nula."""
        with self.assertRaises(Spotifice.BadReference):
            # Intentamos pasar None como sesión
            self.render.bind_media_server(self.server, None)

    def test_play_authenticated(self):
        """Prueba de reproducción completa usando el canal seguro."""
        self.render.bind_media_server(self.server, self.valid_session)
        
        # Usamos una pista de test/media
        tracks = self.server.get_all_tracks()
        self.render.load_track(tracks[0].id)
        
        # Play debería usar internamente self.stream_manager.open_stream()
        self.render.play()
        
        status = self.render.get_status()
        self.assertEqual(status.state, Spotifice.PlaybackState.PLAYING)
        
        self.render.stop()

    def test_unbind_closes_session(self):
        """Prueba que al desvincular, se cierra la sesión en el servidor."""
        self.render.bind_media_server(self.server, self.valid_session)
        
        # La sesión es válida
        self.valid_session.ice_ping()
        
        # Desvinculamos (debería llamar a session.close())
        self.render.unbind_media_server()
        
        # La sesión ya no debería existir
        with self.assertRaises(Ice.ObjectNotExistException):
            self.valid_session.get_user_info()
import Ice
import json
import hashlib
import secrets
import os
import time

# Cargamos contrato v2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore

from gst_player import GstPlayer
from media_render import main as render_main
from media_server import main as server_main
from .icetest import IceTestCase

class TestRender(IceTestCase):
    render_port = 10001
    server_port = 10000
    users_file = 'test/users_render_legacy.json'

    def setUp(self):
        # 1. Crear usuarios
        self.salt = secrets.token_hex(8)
        self.password = "secret"
        self.digest = hashlib.md5((self.password + self.salt).encode('utf-8')).hexdigest()
        users_data = {"user": {"salt": self.salt, "digest": self.digest, "fullname": "U", "email": "e", "is_premium": False, "created_at": ""}}
        
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f)

        server_props = {
            'MediaServerAdapter.Endpoints': f'tcp -p {self.server_port}',
            'MediaServer.Content': 'test/media',
            'MediaServer.Playlists': 'test/playlists',
            'MediaServer.UsersFile': self.users_file
        }
        server_endpoint = f'mediaServer1:default -p {self.server_port} -t 500'
        self.create_server(server_main, server_props)

        player = GstPlayer()
        player.start()
        self.addCleanup(player.shutdown)

        render_props = {'MediaRenderAdapter.Endpoints': f'tcp -p {self.render_port}'}
        render_enpoint = f'mediaRender1:default -p {self.render_port} -t 500'
        self.create_server(render_main, render_props, player)

        self.server = self.create_proxy(server_endpoint, Spotifice.MediaServerPrx)
        self.sut = self.create_proxy(render_enpoint, Spotifice.MediaRenderPrx)
        
        # AUTENTICACIÓN PREVIA (Necesaria para Hito 2)
        self.session = self.server.authenticate(self.sut, "user", "secret")

    def tearDown(self):
        if os.path.exists(self.users_file):
            os.remove(self.users_file)
        super().tearDown()

class PlaybackTests(TestRender):
    def test_id(self):
        self.assertEqual(self.sut.ice_id(), '::Spotifice::MediaRender')

    def test_stop_is_idempotent(self):
        self.sut.stop()
        self.sut.stop()

    def test_play_unbound_server(self):
        with self.assertRaises(Spotifice.BadReference) as cm:
            self.sut.play()
        self.assertEqual(cm.exception.reason, "No MediaServer bound")

    def test_play_unloaded_track(self):
        # AHORA PASAMOS LA SESIÓN TAMBIÉN
        self.sut.bind_media_server(self.server, self.session)

        with self.assertRaises(Spotifice.TrackError) as cm:
            self.sut.play()
        self.assertEqual(cm.exception.reason, "No track loaded")

    def test_normal_play(self):
        tracks = self.server.get_all_tracks()
        self.sut.bind_media_server(self.server, self.session)
        self.sut.load_track(tracks[1].id)
        self.sut.play()

    def test_can_not_play_if_player_busy(self):
        tracks = self.server.get_all_tracks()
        self.sut.bind_media_server(self.server, self.session)
        self.sut.load_track(tracks[1].id)
        self.sut.play()

        with self.assertRaises(Spotifice.PlayerError) as cm:
            self.sut.play()
        self.assertEqual(cm.exception.reason, "Already playing")
    
    # ... (Puedes mantener aquí tus tests del Hito 1 si quieres, pero actualiza el bind) ...
import Ice
import json
import hashlib
import secrets
import os
import time

# Cargamos contrato v2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore

from media_server import main as server_main
from .icetest import IceTestCase

class TestServer(IceTestCase):
    server_port = 10000
    users_file = 'test/users_server_legacy.json'

    def setUp(self):
        # 1. Crear usuarios para que los tests puedan loguearse
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
        self.sut = self.create_proxy(server_endpoint, Spotifice.MediaServerPrx)
        # Mock render para autenticación
        self.mock_render = Spotifice.MediaRenderPrx.uncheckedCast(self.sut)

    def tearDown(self):
        if os.path.exists(self.users_file):
            os.remove(self.users_file)
        super().tearDown()

class MusicLibraryTests(TestServer):
    def test_get_all_tracks(self):
        tracks = self.sut.get_all_tracks()
        self.assertEqual(len(tracks), 4)
        self.assertEqual(tracks[0].id, '1s.mp3')

    def test_get_track_info(self):
        track = self.sut.get_track_info('1s.mp3')
        self.assertEqual(track.id, '1s.mp3')

    def test_get_track_info_wrong_track(self):
        with self.assertRaises(Spotifice.TrackError) as cm:
            self.sut.get_track_info('bad-track-id')
        self.assertEqual(cm.exception.reason, 'Track not found')

class StreamManagerTests(TestServer):
    def setUp(self):
        super().setUp()
        # Para probar streaming, ahora necesitamos una SESIÓN
        self.session = self.sut.authenticate(self.mock_render, "user", "secret")

    def test_open_stream_wrong_track(self):
        track_id = 'bad-track-id'
        # Ahora llamamos a open_stream en la SESIÓN, no en el servidor
        with self.assertRaises(Spotifice.TrackError) as cm:
            self.session.open_stream(track_id)
        self.assertEqual(cm.exception.reason, 'Track not found')

    def test_get_audio_chunk(self):
        track_id = self.sut.get_all_tracks()[0].id
        
        # Usamos la sesión
        self.session.open_stream(track_id)
        chunk = self.session.get_audio_chunk(1024)

        self.assertGreater(len(chunk), 0)
        with open('test/media/1s.mp3', 'rb') as f:
            expected = f.read(len(chunk))
            self.assertEqual(chunk, expected)

    def test_get_audio_chunk_not_open_stream(self):
        # Usamos la sesión
        with self.assertRaises(Spotifice.StreamError) as cm:
            self.session.get_audio_chunk(1024)
        self.assertEqual(cm.exception.reason, 'No stream open')
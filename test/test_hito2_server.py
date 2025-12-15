import json
import hashlib
import secrets
import os
import time
import Ice

# Aseguramos cargar el contrato v2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore

from media_server import main as server_main
from .icetest import IceTestCase

class TestAuthManager(IceTestCase):
    server_port = 10000
    users_file = 'test/users_test.json'

    def setUp(self):
        # 1. Crear un users.json temporal con credenciales conocidas
        self.salt = secrets.token_hex(8)
        self.password = "secret_password"
        # Calculamos el digest tal cual pide el enunciado
        self.digest = hashlib.md5((self.password + self.salt).encode('utf-8')).hexdigest()
        
        self.users_data = {
            "testuser": {
                "fullname": "Test User",
                "email": "test@example.com",
                "is_premium": True,
                "created_at": "2025-01-01T00:00:00Z",
                "salt": self.salt,
                "digest": self.digest
            }
        }
        
        with open(self.users_file, 'w') as f:
            json.dump(self.users_data, f)

        # 2. Configurar el servidor con el fichero de usuarios
        server_props = {
            'MediaServerAdapter.Endpoints': f'tcp -p {self.server_port}',
            'MediaServer.Content': 'test/media',
            'MediaServer.Playlists': 'test/playlists',
            'MediaServer.UsersFile': self.users_file # ¡Importante!
        }
        server_endpoint = f'mediaServer1:default -p {self.server_port} -t 500'
        
        # 3. Arrancar servidor
        self.create_server(server_main, server_props)
        self.server = self.create_proxy(server_endpoint, Spotifice.MediaServerPrx)
        
        # Truco: Usamos el propio proxy del servidor como "falso render" para el ping
        # (Solo necesitamos un objeto que responda a ice_ping)
        self.mock_render = Spotifice.MediaRenderPrx.uncheckedCast(self.server)

    def tearDown(self):
        # Borramos el fichero temporal
        if os.path.exists(self.users_file):
            os.remove(self.users_file)
        super().tearDown()

    def test_authenticate_success(self):
        """Prueba login correcto."""
        session = self.server.authenticate(self.mock_render, "testuser", "secret_password")
        self.assertIsNotNone(session)
        
        # Verificar info de sesión
        info = session.get_user_info()
        self.assertEqual(info.username, "testuser")
        self.assertEqual(info.email, "test@example.com")

    def test_authenticate_bad_password(self):
        """Prueba login con contraseña incorrecta."""
        with self.assertRaises(Spotifice.AuthError):
            self.server.authenticate(self.mock_render, "testuser", "wrong_pass")

    def test_authenticate_unknown_user(self):
        """Prueba login con usuario inexistente."""
        with self.assertRaises(Spotifice.AuthError):
            self.server.authenticate(self.mock_render, "nobody", "secret_password")

    def test_authenticate_bad_render(self):
        """Prueba que falla si el render no responde (simulado con None)."""
        # Según nuestra implementación, debe lanzar BadReference si es None o falla ping
        with self.assertRaises(Spotifice.BadReference):
            self.server.authenticate(None, "testuser", "secret_password")

    def test_session_streaming(self):
        """Prueba que el objeto de sesión permite hacer streaming."""
        session = self.server.authenticate(self.mock_render, "testuser", "secret_password")
        
        # Usamos la sesión para abrir stream (ya no pide render_id)
        session.open_stream("1s.mp3")
        
        chunk = session.get_audio_chunk(1024)
        self.assertGreater(len(chunk), 0)
        
        session.close_stream()

    def test_session_lifecycle(self):
        """Prueba que close() destruye la sesión."""
        session = self.server.authenticate(self.mock_render, "testuser", "secret_password")
        
        # La sesión existe
        session.ice_ping()
        
        # Cerramos
        session.close()
        
        # Ahora debe haber desaparecido del adaptador
        with self.assertRaises(Ice.ObjectNotExistException):
            session.get_user_info()
"""Unit tests for mcp_wa HTTP client error handling."""
import os
import unittest
from unittest.mock import MagicMock, patch

from mcp_wa.client import (
    JWT_ENV,
    SignHouseApiError,
    SignHouseClient,
    _format_error,
    _jwt_from_env,
    uploads_url,
)


class JwtFromEnvTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(JWT_ENV, None)
        os.environ.pop('Authorization', None)

    def test_missing_jwt_raises(self):
        with self.assertRaises(SignHouseApiError) as ctx:
            _jwt_from_env()
        self.assertIn(JWT_ENV, str(ctx.exception))

    def test_strips_bearer_prefix(self):
        os.environ[JWT_ENV] = 'Bearer abc.def.ghi'
        self.assertEqual(_jwt_from_env(), 'abc.def.ghi')


class FormatErrorTests(unittest.TestCase):
    def test_401_includes_refresh_hint(self):
        msg = _format_error(401, {'error': 'Unauthorized'})
        self.assertIn('Unauthorized', msg)
        self.assertIn('JWT', msg)

    def test_dict_message_field(self):
        self.assertIn('nope', _format_error(400, {'message': 'nope'}))


class SignHouseClientCallTests(unittest.TestCase):
    def setUp(self):
        os.environ[JWT_ENV] = 'test-token'
        os.environ.pop('SIGN_HOUSE_API_URL', None)

    def tearDown(self):
        os.environ.pop(JWT_ENV, None)

    @patch('mcp_wa.client.requests.request')
    def test_403_raises_with_body(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.content = b'{"error":"Forbidden"}'
        mock_resp.headers = {'content-type': 'application/json'}
        mock_resp.json.return_value = {'error': 'Forbidden'}
        mock_request.return_value = mock_resp

        client = SignHouseClient()
        with self.assertRaises(SignHouseApiError) as ctx:
            client.get('/wa/projects')
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn('Forbidden', str(ctx.exception))

    @patch('mcp_wa.client.requests.request')
    def test_success_json(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.content = b'[]'
        mock_resp.headers = {'content-type': 'application/json'}
        mock_resp.json.return_value = []
        mock_request.return_value = mock_resp

        client = SignHouseClient()
        self.assertEqual(client.get('/wa/projects'), [])


class UploadsUrlTests(unittest.TestCase):
    @patch.dict(os.environ, {'SIGN_HOUSE_API_URL': 'http://127.0.0.1:5000/api'})
    def test_uploads_path(self):
        url = uploads_url('/uploads/wa-media/foo.jpg')
        self.assertEqual(url, 'http://127.0.0.1:5000/api/wa/uploads/wa-media/foo.jpg')


if __name__ == '__main__':
    unittest.main()

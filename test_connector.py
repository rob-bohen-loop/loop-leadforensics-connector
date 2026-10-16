import asyncio
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet
from fastmcp import Client
from fastmcp.server.auth.providers.github import GitHubProvider
import httpx2

from leadforensics import LeadForensics, LeadForensicsError, window
from server import allowed_identity, build_server

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = LeadForensics('fake-key', 'fake-client')

    def test_assignee_parameter_and_pagination(self):
        with patch.object(self.client, 'read', return_value=[]) as read:
            result = self.client.fetch('assigned', client_user_id=17,
                start='2026-10-01', end='2026-10-16', page=2, page_size=10)
        endpoint, params = read.call_args.args
        self.assertEqual(endpoint, 'assigned')
        self.assertEqual(params['clientuserid'], 17)
        self.assertNotIn('assignedtoid', params)
        self.assertEqual(params['pageno'], 2)
        self.assertEqual(params['dateto'], '2026-10-16 23:59:59')
        self.assertIn('One API page', result['coverage'])

    def test_invalid_dates(self):
        for first, last in [('2026-10-16', None), ('bad', 'date'),
                            ('2026-10-16', '2026-10-01'), ('2026-01-01', '2026-10-16')]:
            with self.assertRaises(LeadForensicsError):
                window(first, last)

    def test_reject_invalid_identifiers_before_network(self):
        with patch.object(self.client, 'read') as read:
            for value in [None, 0, -1, True, 'abc']:
                with self.assertRaises(LeadForensicsError):
                    self.client.fetch('business', business_id=value)
            with self.assertRaises(LeadForensicsError):
                self.client.fetch('users', page_size=101)
            read.assert_not_called()

    def test_actual_get_headers_and_payload(self):
        response = io.BytesIO(b'{"Businesses":[{"BusinessID":4}]}')
        with patch.object(self.client.opener, 'open', return_value=response) as opened:
            data = self.client.fetch('business', business_id=4)
        request = opened.call_args.args[0]
        self.assertEqual(request.method, 'GET')
        self.assertTrue(request.full_url.endswith('Business/GetBusiness?businessid=4'))
        self.assertEqual(dict(request.header_items())['Authorization-token'], 'fake-key')
        self.assertEqual(data['data']['Businesses'][0]['BusinessID'], 4)

    def test_sanitized_errors(self):
        for error in [HTTPError('secret-url', 401, 'secret', {}, None),
                      HTTPError('secret-url', 429, 'secret', {}, None),
                      HTTPError('secret-url', 302, 'secret', {}, None),
                      URLError('secret-key'), TimeoutError('secret')]:
            with patch.object(self.client.opener, 'open', side_effect=error):
                with self.assertRaises(LeadForensicsError) as ctx:
                    self.client.fetch('users')
                self.assertNotIn('secret', str(ctx.exception).replace('hosting secrets', 'settings'))

    def test_unknown_endpoint_rejected(self):
        with patch.object(self.client.opener, 'open') as opened:
            with self.assertRaises(KeyError):
                self.client.read('https://example.com', {})
            opened.assert_not_called()

class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'PUBLIC_BASE_URL': 'https://connector.example.com',
            'ALLOWED_GITHUB_USER_ID': '123',
            'GITHUB_CLIENT_ID': 'test-client', 'GITHUB_CLIENT_SECRET': 'test-secret',
            'JWT_SIGNING_KEY': 'test-only-signing-key-with-at-least-32-characters',
            'STORAGE_ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'AUTH_STORAGE_DIR': self.tmp.name, 'LF_API_KEY': 'test-key', 'LF_CLIENT_ID': 'test-client',
        })
        self.env.start()
        self.mcp = build_server()
        self.approved = SimpleNamespace(claims={'github_user_data': {'id': 123}})
        self.other = SimpleNamespace(claims={'github_user_data': {'id': 999}})

    async def asyncTearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    async def test_identity_fails_closed(self):
        self.assertTrue(allowed_identity(self.approved, '123'))
        for token in [None, self.other, SimpleNamespace(claims={})]:
            self.assertFalse(allowed_identity(token, '123'))

    async def test_provider_rejects_other_account(self):
        with patch.object(GitHubProvider, 'verify_token', AsyncMock(return_value=self.other)):
            self.assertIsNone(await self.mcp.auth.verify_token('fake'))
        with patch.object(GitHubProvider, 'verify_token', AsyncMock(return_value=self.approved)):
            self.assertIsNotNone(await self.mcp.auth.verify_token('fake'))

    async def test_http_requires_oauth_and_exposes_metadata(self):
        transport = httpx2.ASGITransport(app=self.mcp.http_app(stateless_http=True))
        async with httpx2.AsyncClient(transport=transport, base_url='https://connector.example.com') as client:
            resp = await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            self.assertEqual(resp.status_code, 401)
            self.assertIn('resource_metadata', resp.headers.get('www-authenticate', ''))
            metadata = await client.get('/.well-known/oauth-authorization-server')
            self.assertEqual(metadata.status_code, 200)
            self.assertIn('S256', metadata.json()['code_challenge_methods_supported'])
            health = await client.get('/health')
            self.assertEqual(health.json(), {'status': 'ok'})

    async def test_mcp_tools_and_authorized_calls(self):
        calls = [
            ('list_assigned_users', {}, 'Reference/GetAssignedToList'),
            ('recent_visitors', {}, 'Business/GetAllBusinesses'),
            ('assigned_visitors', {'client_user_id': 17}, 'Business/GetBusinessesByAssignedTo'),
            ('business_details', {'business_id': 5}, 'Business/GetBusiness'),
            ('business_visits', {'business_id': 5}, 'Visit/GetVisitsByBusiness'),
            ('visit_pages', {'visit_id': 8}, 'Page/GetPagesByVisit'),
        ]
        with patch('server.get_access_token', return_value=self.approved):
            async with Client(self.mcp) as client:
                tools = await client.list_tools()
                self.assertEqual(len(tools), 6)
                self.assertTrue(all(t.annotations.read_only_hint for t in tools))
                for name, args, path in calls:
                    with patch('leadforensics.LeadForensics.read', return_value=[{'sample': True}]) as read:
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.is_error)
                        from leadforensics import ENDPOINTS
                        self.assertEqual(ENDPOINTS[read.call_args.args[0]], path)

    async def test_unauthorized_tool_never_calls_api(self):
        with patch('server.get_access_token', return_value=self.other), \
             patch('leadforensics.LeadForensics.read') as read:
            async with Client(self.mcp) as client:
                result = await client.call_tool('list_assigned_users', {}, raise_on_error=False)
                self.assertTrue(result.is_error)
            read.assert_not_called()

if __name__ == '__main__':
    unittest.main()

import os
import unittest
from unittest.mock import patch

os.environ['API_TOKEN'] = 'test-key'
from fastapi.testclient import TestClient
from app import app, connect


class Result:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return self.rows[0]


class Database:
    def __init__(self):
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, query, params=None):
        self.calls.append((query, params))
        if isinstance(query, str) and 'information_schema' in query:
            return Result([{'column_name': 'id', 'data_type': 'bigint'}])
        if isinstance(query, str):
            return Result([])
        if params is None:
            return Result([{'n': 9007199254740993}])
        return Result([{'id': 9007199254740992}, {'id': 9007199254740993}])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
    def test_authentication(self):
        self.assertEqual(self.client.get('/api/tables').status_code, 401)
        self.assertEqual(self.client.get('/api/tables?api_key=test-key').status_code, 200)
        self.assertEqual(self.client.get('/api/tables', headers={'X-API-Key': 'test-key'}).status_code, 200)
    def test_missing_key_fails_closed(self):
        with patch.dict(os.environ, {'API_TOKEN': ''}):
            self.assertEqual(self.client.get('/api/tables').status_code, 503)
    def test_invalid_table(self):
        with patch('app.connect') as db:
            self.assertEqual(self.client.get('/api/data/secret?api_key=test-key').status_code, 404)
            db.assert_not_called()
    def test_pagination_and_bigint_precision(self):
        db = Database()
        with patch('app.connect', return_value=db):
            response = self.client.get('/api/data/instagram_daily_insights?api_key=test-key&limit=1')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['data'], [{'id': '9007199254740992'}])
        self.assertEqual(payload['next_after_id'], '9007199254740992')
        self.assertEqual(payload['until_id'], '9007199254740993')
    def test_last_page_and_filters(self):
        db = Database()
        with patch('app.connect', return_value=db):
            response = self.client.get('/api/data/instagram_daily_insights?api_key=test-key&until_id=10&date_from=2026-01-01&date_to=2026-12-31')
        self.assertIsNone(response.json()['next_after_id'])
        params = db.calls[-1][1]
        self.assertEqual(params[:2], [0, 10])
        self.assertEqual(str(params[2]), '2026-01-01')
    def test_validation(self):
        for query in ('limit=0', 'limit=10001', 'after_id=-1', 'date_from=2026-12-31&date_to=2026-01-01'):
            self.assertEqual(self.client.get('/api/data/instagram_daily_insights?api_key=test-key&' + query).status_code, 422)


class ConnectionTests(unittest.TestCase):
    def test_separate_parameters_and_special_password(self):
        config = {'PGHOST': '127.0.0.1', 'PGDATABASE': 'instagram',
                  'PGUSER': 'reader', 'PGPASSWORD': "a@:# /'", 'PGPORT': '5432'}
        with patch.dict(os.environ, config, clear=True), patch('app.psycopg.connect') as driver:
            connect()
        self.assertEqual(driver.call_args.kwargs['password'], config['PGPASSWORD'])
        self.assertEqual(driver.call_args.kwargs['dbname'], 'instagram')
        self.assertEqual(driver.call_args.kwargs['port'], 5432)

    def test_missing_database_settings(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, {}, clear=True), patch('app.psycopg.connect') as driver:
            with self.assertRaises(HTTPException) as error:
                connect()
        self.assertEqual(error.exception.status_code, 503)
        driver.assert_not_called()

    def test_invalid_port(self):
        from fastapi import HTTPException
        config = {'PGHOST': 'localhost', 'PGDATABASE': 'db', 'PGUSER': 'reader', 'PGPASSWORD': 'secret'}
        for port in ('abc', '0', '65536'):
            with patch.dict(os.environ, dict(config, PGPORT=port), clear=True):
                with self.assertRaises(HTTPException):
                    connect()


class BearerOffsetTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
    def test_bearer(self):
        for value, status in [('Bearer test-key', 200), ('bearer test-key', 200), ('Bearer wrong', 401), ('Basic test-key', 401)]:
            self.assertEqual(self.client.get('/api/tables', headers={'Authorization': value}).status_code, status)
    def test_offset_is_sent_to_database(self):
        db = Database()
        with patch('app.connect', return_value=db):
            response = self.client.get('/api/data/instagram_daily_insights?offset=10000&limit=1&until_id=99999', headers={'Authorization': 'Bearer test-key'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.calls[-1][1], [0, 99999, 2, 10000])
        self.assertIn('OFFSET %s', str(db.calls[-1][0]))
        self.assertEqual(response.json()['next_offset'], 10001)
    def test_empty_page(self):
        db = Database()
        original = db.execute
        def execute(query, params=None):
            if params is not None and not isinstance(query, str):
                return Result([])
            return original(query, params)
        db.execute = execute
        with patch('app.connect', return_value=db):
            response = self.client.get('/api/data/instagram_daily_insights?api_key=test-key&offset=20000')
        self.assertEqual(response.json()['data'], [])
        self.assertIsNone(response.json()['next_offset'])
    def test_invalid_pagination(self):
        for query in ('offset=-1', 'offset=0&after_id=1'):
            self.assertEqual(self.client.get('/api/data/instagram_daily_insights?api_key=test-key&' + query).status_code, 422)

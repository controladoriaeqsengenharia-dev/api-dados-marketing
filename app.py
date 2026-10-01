"""API de leitura das seis tabelas Instagram para Power BI."""
import json
import os
import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import Response
from psycopg import sql
from psycopg.rows import dict_row

load_dotenv()
TABLES = (
    'instagram_daily_insights', 'instagram_demographic_breakdowns',
    'instagram_demographics', 'instagram_media_insight_failures',
    'instagram_media_insights', 'instagram_media_snapshots',
)
app = FastAPI(title='Instagram BI API', version='1.0.0')


def authenticate(
    x_api_key: Annotated[str | None, Header()] = None,
    api_key: Annotated[str | None, Query()] = None,
):
    expected = os.getenv('API_TOKEN', '')
    if not expected or expected.startswith('SUBSTITUA_'):
        raise HTTPException(503, 'Configure API_TOKEN no servidor.')
    supplied = x_api_key or api_key or ''
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, 'Chave de API inválida.')


def connect():
    required = ('PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')
    if any(not os.getenv(name) for name in required):
        raise HTTPException(503, 'Configure PGHOST, PGDATABASE, PGUSER e PGPASSWORD no servidor.')
    try:
        port = int(os.getenv('PGPORT') or '5432')
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise HTTPException(503, 'PGPORT deve ser uma porta válida.') from None
    return psycopg.connect(
        host=os.environ['PGHOST'], port=port, dbname=os.environ['PGDATABASE'],
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        row_factory=dict_row, connect_timeout=10,
        options='-c default_transaction_read_only=on -c statement_timeout=30000',
    )


def encode(value):
    # Strings preservam inteiros de 64 bits e numeric sem arredondamento JSON.
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


@app.get('/')
def root():
    return {'service': 'Instagram BI API', 'docs': '/docs'}


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/api/tables', dependencies=[Depends(authenticate)])
def tables():
    return {'tables': TABLES}


@app.get('/api/data/{table}', dependencies=[Depends(authenticate)])
def data(
    table: str,
    after_id: Annotated[int, Query(ge=0)] = 0,
    until_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 5000,
    date_from: date | None = None,
    date_to: date | None = None,
):
    if table not in TABLES:
        raise HTTPException(404, 'Tabela não permitida.')
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, 'date_from deve ser menor ou igual a date_to.')
    qualified = sql.Identifier('public', table)
    try:
        with connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            columns = conn.execute(
                'SELECT column_name, data_type FROM information_schema.columns '
                'WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position',
                ('public', table),
            ).fetchall()
            if not columns:
                raise HTTPException(503, 'Tabela ausente ou sem permissão de leitura.')
            if until_id is None:
                until_id = conn.execute(sql.SQL('SELECT COALESCE(MAX(id), 0) AS n FROM {}')
                                        .format(qualified)).fetchone()['n']
            clauses = [sql.SQL('id > %s'), sql.SQL('id <= %s')]
            params = [after_id, until_id]
            for op, value in [('>=', date_from), ('<=', date_to)]:
                if value is not None:
                    clauses.append(sql.SQL('data_coleta ' + op + ' %s'))
                    params.append(value)
            params.append(limit + 1)
            rows = conn.execute(sql.SQL('SELECT * FROM {} WHERE {} ORDER BY id LIMIT %s')
                                .format(qualified, sql.SQL(' AND ').join(clauses)), params).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_id = str(rows[-1]['id']) if has_more else None
        for row in rows:
            for column in columns:
                name, kind = column['column_name'], column['data_type']
                if row[name] is not None:
                    if kind in ('bigint', 'numeric', 'decimal'):
                        row[name] = str(row[name])
                    elif kind in ('json', 'jsonb'):
                        row[name] = json.dumps(row[name], default=encode, ensure_ascii=False)
        payload = {'table': table, 'columns': columns, 'data': rows,
                   'next_after_id': next_id, 'until_id': str(until_id)}
        return Response(json.dumps(payload, default=encode, ensure_ascii=False),
                        media_type='application/json', headers={'Cache-Control': 'no-store'})
    except psycopg.Error:
        raise HTTPException(503, 'Banco indisponível ou consulta não permitida.') from None

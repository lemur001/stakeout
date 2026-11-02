"""SQL repository adapter. SQLite for local/single-instance; PostgreSQL for deployment.

Writes use short transactions. No network request is made while a transaction is held.
A PostgreSQL advisory transaction lock serializes cross-table eligibility decisions.
Database uniqueness remains the final defense for duplicate sends and reservations.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from .core import iso

class Tx:
    def __init__(self, conn, postgres=False): self.conn,self.postgres=conn,postgres
    def execute(self, query: str, params: tuple | list=()):
        return self.conn.execute(query.replace('?','%s') if self.postgres else query,params)
    def one(self, query: str, params: tuple | list=()) -> dict | None:
        row=self.execute(query,params).fetchone()
        return dict(row) if row is not None else None
    def all(self, query: str, params: tuple | list=()) -> list[dict]:
        return [dict(r) for r in self.execute(query,params).fetchall()]
    def setting(self,key: str,default=None):
        row=self.one('SELECT value FROM settings WHERE key=?',(key,))
        return json.loads(row['value']) if row else default
    def set_setting(self,key: str,value):
        self.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))

class Database:
    def __init__(self,path: str,database_url: str=''):
        self.path,self.url=path,database_url
        self.postgres=bool(database_url)
        if not self.postgres:
            Path(path).parent.mkdir(parents=True,exist_ok=True)
    def _connect(self):
        if self.postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError:
                raise RuntimeError('PostgreSQL requires: pip install -r requirements-postgres.txt') from None
            conn=psycopg.connect(self.url,row_factory=dict_row,connect_timeout=10,autocommit=True)
            conn.execute('SET search_path TO civic')
            return conn
        conn=sqlite3.connect(self.path,timeout=20,isolation_level=None)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=20000')
        return conn
    @contextmanager
    def transaction(self,write: bool=True) -> Iterator[Tx]:
        conn=self._connect()
        try:
            conn.execute('BEGIN' if self.postgres or not write else 'BEGIN IMMEDIATE')
            if self.postgres and write:
                conn.execute('SELECT pg_advisory_xact_lock(724981031)')
            yield Tx(conn,self.postgres)
            conn.execute('COMMIT')
        except Exception:
            try: conn.execute('ROLLBACK')
            except Exception: pass
            raise
        finally: conn.close()
    def migrate(self):
        if self.postgres:
            import psycopg
            with psycopg.connect(self.url,autocommit=True) as c:
                c.execute('CREATE SCHEMA IF NOT EXISTS civic')
                c.execute('REVOKE ALL ON SCHEMA civic FROM PUBLIC')
        statements=(Path(__file__).parent/'schema.sql').read_text().split(';')
        with self.transaction() as tx:
            for stmt in statements:
                if stmt.strip(): tx.execute(stmt)
            tx.execute('INSERT INTO schema_versions(version,applied_at) VALUES(1,?) ON CONFLICT(version) DO NOTHING',(iso(),))
            tx.execute('INSERT INTO schema_versions(version,applied_at) VALUES(2,?) ON CONFLICT(version) DO NOTHING',(iso(),))
            columns={r['column_name'] for r in tx.all("SELECT column_name FROM information_schema.columns WHERE table_schema='civic' AND table_name='entities'")} if self.postgres else {r['name'] for r in tx.all('PRAGMA table_info(entities)')}
            if 'campaign' not in columns:tx.execute("ALTER TABLE entities ADD COLUMN campaign TEXT NOT NULL DEFAULT 'first_website'")
            tx.execute('INSERT INTO schema_versions(version,applied_at) VALUES(3,?) ON CONFLICT(version) DO NOTHING',(iso(),))
            if tx.setting('profile') is None:
                tx.set_setting('profile',{'agency_name':'Stakeout Search','sender_name':'','sender_email':'','postal_address':''})
            if tx.setting('paused') is None: tx.set_setting('paused',True)

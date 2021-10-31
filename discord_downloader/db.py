import os

from sqlalchemy.ext.asyncio import create_async_engine

from settings import STATE_DIRECTORY
import os
from os.path import dirname

import alembic.config
from alembic import command
from sqlalchemy import create_engine, Table, Column, INTEGER, VARCHAR
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class RenderedDemo(Base):
    __table__ = Table(
        'rendered_demos',
        Base.metadata,
        Column('id', INTEGER(), autoincrement=True, primary_key=True),
        Column('filename', VARCHAR(255), unique=True),
        Column('url', VARCHAR(255)),
    )


def get_async_db_connection_url():
    return f"sqlite+aiosqlite:///{STATE_DIRECTORY}/db.sqlite"


def get_blocking_db_connection_url():
    return f"sqlite+pysqlite:///{STATE_DIRECTORY}/db.sqlite"


def create_current_db_engine():
    connection = create_async_engine(get_async_db_connection_url(), echo=False)
    alembic_cfg = alembic.config.Config()
    alembic_cfg.set_main_option('script_location', os.path.join(dirname(__file__), "..", "alembic"))
    # alembic_cfg.attributes['connection'] = connection.sync_engine
    command.upgrade(alembic_cfg, 'head')
    return connection

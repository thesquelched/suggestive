from suggestive.db.session import initialize, session_scope, sqlalchemy_url
from alembic.config import Config
from alembic import command


def alembic_conf(conf):
    a_conf = Config()
    a_conf.set_main_option('script_location', 'suggestive:alembic')
    a_conf.set_main_option('url', sqlalchemy_url(conf))

    return a_conf


def initialize_database(conf):
    a_conf = alembic_conf(conf)
    initialize(conf)
    with session_scope(conf) as session:
        session.commit()

    command.stamp(a_conf, 'head')


def migrate(conf):
    a_conf = alembic_conf(conf)
    command.upgrade(a_conf, 'head')

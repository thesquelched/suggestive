from suggestive.mstat import sqlalchemy_url
from alembic.config import Config
from alembic import command


def alembic_conf(conf):
    a_conf = Config()
    a_conf.set_main_option('script_location', 'suggestive:alembic')
    a_conf.set_main_option('url', sqlalchemy_url(conf))

    return a_conf


def migrate(conf):
    a_conf = alembic_conf(conf)
    command.upgrade(a_conf, 'head')

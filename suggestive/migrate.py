import suggestive.mstat as mstat
from alembic.config import Config
from alembic import command


def alembic_conf(conf):
    a_conf = Config()
    a_conf.set_main_option('script_location', 'suggestive:alembic')
    a_conf.set_main_option('url', mstat.sqlalchemy_url(conf))

    return a_conf


def initialize_database(conf):
    a_conf = alembic_conf(conf)
    session = mstat.initialize_sqlalchemy(conf)
    session.commit()
    command.stamp(a_conf, 'head')


def migrate(conf):
    a_conf = alembic_conf(conf)
    command.upgrade(a_conf, 'head')

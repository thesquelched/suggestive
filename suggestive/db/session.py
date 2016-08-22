from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from suggestive.db.model import Base


Session = scoped_session(sessionmaker())


def sqlalchemy_url(config):
    """
    Return the SQLAlchemy query string corresponding to the suggestive database
    """
    return 'sqlite:///{}'.format(config.database())


def initialize(config, echo=False):
    """
    Return a SQLAlchemy session object. Also create database if it doesn't
    already exist
    """
    path = sqlalchemy_url(config)
    engine = create_engine(path, echo=bool(echo))
    Session.configure(bind=engine)

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(conf, commit=True):
    """
    Context manager that yields an SQLAlchemy session object that automatically
    commits/rolls back upon completion, depending on whether or not an
    exception was encountered
    """
    session = Session()
    try:
        yield session
        if commit:
            session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

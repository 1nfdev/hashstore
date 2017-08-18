from hashstore.ndb.mixins import ReprIt, NameIt, Cdt, Udt, \
    GuidPk, Singleton
from hashstore.ids import Cake, SaltedSha, InetAddress
from hashstore.ndb import StringCast

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Boolean, Column, String, Integer

Base = declarative_base()


class ServerKey(Singleton,Base):
    secret = Column(StringCast(Cake), default=Cake.new_guid())
    external_ip = Column(StringCast(InetAddress), nullable=True)
    port = Column(Integer, nullable=False)


class Session(GuidPk, NameIt, Cdt, Udt, ReprIt, Base):
    user = Column(StringCast(Cake), nullable=False)
    client = Column(StringCast(SaltedSha), nullable= True)
    host = Column(String, nullable=True)
    active = Column(Boolean, nullable=False)

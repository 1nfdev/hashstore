from hashstore.bakery.content import ContentAddress_TYPE
from hashstore.bakery.db_mixins import ReprIt, NameIt, Cdt
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Integer, Column, LargeBinary

Base = declarative_base()


class Blob(NameIt, ReprIt, Cdt, Base):
    blob_id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(ContentAddress_TYPE, nullable=False)
    content = Column(LargeBinary)

shard_meta = Base.metadata
blob = Blob.__table__
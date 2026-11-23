"""Owner-bound dictionary access. No operation accepts a caller-supplied owner."""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping

from services.hosted_identity import Principal

dictionaries = sa.table(
    "hosted_dictionaries",
    sa.column("owner_key", sa.String),
    sa.column("id", sa.String),
    sa.column("name", sa.String),
    sa.column("entries", sa.JSON),
)
c = dictionaries.c
fields = (c.id, c.name, c.entries)


class DictionaryRepository:
    def __init__(self, engine: Engine, principal: Principal):
        self.engine = engine
        self.owner_key = principal.owner_key
        self.owned = c.owner_key == self.owner_key

    def create(self, name: str, entries: dict[str, str]) -> RowMapping:
        statement = (
            dictionaries.insert()
            .values(
                owner_key=self.owner_key, id=str(uuid4()), name=name, entries=entries
            )
            .returning(*fields)
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).mappings().one()

    def list(self, limit: int, offset: int) -> list[RowMapping]:
        query = (
            sa.select(c.id, c.name)
            .where(self.owned)
            .order_by(c.id)
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as connection:
            return list(connection.execute(query).mappings())

    def get(self, resource_id: UUID) -> RowMapping | None:
        query = sa.select(*fields).where(self.owned, c.id == str(resource_id))
        with self.engine.connect() as connection:
            return connection.execute(query).mappings().one_or_none()

    def replace(
        self, resource_id: UUID, name: str, entries: dict[str, str]
    ) -> RowMapping | None:
        statement = (
            dictionaries.update()
            .where(self.owned, c.id == str(resource_id))
            .values(name=name, entries=entries)
            .returning(*fields)
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).mappings().one_or_none()

    def delete(self, resource_id: UUID) -> bool:
        statement = dictionaries.delete().where(self.owned, c.id == str(resource_id))
        with self.engine.begin() as connection:
            return connection.execute(statement).rowcount == 1

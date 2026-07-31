"""Minimal user bootstrap for control-plane entry points."""

from sqlalchemy.dialects.postgresql import insert

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import UserRow
from tandemn_system_data.models import User


class UserStore:
    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def ensure(self, user: User) -> User:
        """Create the user if absent; leave an existing user unchanged."""
        with self._client.begin() as session:
            session.execute(
                insert(UserRow)
                .values(**user.model_dump())
                .on_conflict_do_nothing(index_elements=[UserRow.user_id])
            )
        return user

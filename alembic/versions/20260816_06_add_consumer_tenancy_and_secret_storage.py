"""Add consumer tenancy, scoped credentials, and encrypted CSC storage.

Revision ID: 20260816_06
Revises: 20260426_05
Create Date: 2026-08-16 22:00:00
"""

from __future__ import annotations

import os
from uuid import uuid4

from alembic import op
from cryptography.fernet import Fernet
import sqlalchemy as sa


revision = "20260816_06"
down_revision = "20260426_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("emitters") as batch_op:
        batch_op.alter_column(
            "csc",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )
    op.create_table(
        "consumers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.UniqueConstraint("name", name="uq_consumers_name"),
    )
    op.create_table(
        "consumer_emitters",
        sa.Column("consumer_id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), primary_key=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(
            ["consumer_id"], ["consumers.id"], name="fk_consumer_emitters_consumer"
        ),
        sa.ForeignKeyConstraint(
            ["emitter_id"], ["emitters.id"], name="fk_consumer_emitters_emitter"
        ),
        sa.UniqueConstraint("emitter_id", name="uq_consumer_emitters_emitter_id"),
    )

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(sa.Column("consumer_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("scopes", sa.JSON(), nullable=True))

    connection = op.get_bind()
    consumers = sa.table(
        "consumers",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=128)),
        sa.column("status", sa.String(length=32)),
    )
    grants = sa.table(
        "consumer_emitters",
        sa.column("consumer_id", sa.String(length=36)),
        sa.column("emitter_id", sa.String(length=36)),
    )
    api_keys = sa.table(
        "api_keys",
        sa.column("id", sa.String(length=36)),
        sa.column("emitter_id", sa.String(length=36)),
        sa.column("consumer_id", sa.String(length=36)),
        sa.column("scopes", sa.JSON()),
    )
    emitters = sa.table("emitters", sa.column("id", sa.String(length=36)))

    consumer_by_emitter: dict[str, str] = {}
    for position, emitter_id in enumerate(connection.execute(sa.select(emitters.c.id)), start=1):
        consumer_id = str(uuid4())
        emitter_id = emitter_id[0]
        consumer_by_emitter[emitter_id] = consumer_id
        connection.execute(
            consumers.insert().values(
                id=consumer_id,
                name=f"Migrated consumer {position}",
                status="active",
            )
        )
        connection.execute(
            grants.insert().values(consumer_id=consumer_id, emitter_id=emitter_id)
        )

    platform_consumer_id: str | None = None
    credential_rows = connection.execute(
        sa.select(api_keys.c.id, api_keys.c.emitter_id)
    ).all()
    for credential_id, emitter_id in credential_rows:
        if emitter_id is not None:
            consumer_id = consumer_by_emitter[emitter_id]
            scopes = [
                "tenant:read",
                "tenant:write",
                "fiscal:write",
                "secrets:write",
            ]
        else:
            if platform_consumer_id is None:
                platform_consumer_id = str(uuid4())
                connection.execute(
                    consumers.insert().values(
                        id=platform_consumer_id,
                        name="Migrated platform administrator",
                        status="active",
                    )
                )
            consumer_id = platform_consumer_id
            scopes = ["platform:admin"]
        connection.execute(
            api_keys.update()
            .where(api_keys.c.id == credential_id)
            .values(consumer_id=consumer_id, scopes=scopes)
        )

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.alter_column("consumer_id", nullable=False)
        batch_op.alter_column("scopes", nullable=False)
        batch_op.create_foreign_key(
            "fk_api_keys_consumer_id_consumers", "consumers", ["consumer_id"], ["id"]
        )
        batch_op.drop_constraint("fk_api_keys_emitter_id_emitters", type_="foreignkey")
        batch_op.drop_column("emitter_id")

    _encrypt_existing_csc_values()


def downgrade() -> None:
    _decrypt_existing_csc_values()
    with op.batch_alter_table("emitters") as batch_op:
        batch_op.alter_column(
            "csc",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(sa.Column("emitter_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_api_keys_emitter_id_emitters", "emitters", ["emitter_id"], ["id"]
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE api_keys
               SET emitter_id = (
                   SELECT consumer_emitters.emitter_id
                     FROM consumer_emitters
                    WHERE consumer_emitters.consumer_id = api_keys.consumer_id
                    LIMIT 1
               )
            """
        )
    )
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_constraint("fk_api_keys_consumer_id_consumers", type_="foreignkey")
        batch_op.drop_column("scopes")
        batch_op.drop_column("consumer_id")
    op.drop_table("consumer_emitters")
    op.drop_table("consumers")


def _encrypt_existing_csc_values() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, csc FROM emitters WHERE csc IS NOT NULL")
    ).all()
    if not rows:
        return
    cipher = _migration_cipher()
    for emitter_id, plaintext in rows:
        if not plaintext.startswith("gAAAA"):
            ciphertext = cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")
            connection.execute(
                sa.text("UPDATE emitters SET csc = :csc WHERE id = :id"),
                {"csc": ciphertext, "id": emitter_id},
            )


def _decrypt_existing_csc_values() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, csc FROM emitters WHERE csc IS NOT NULL")
    ).all()
    if not rows:
        return
    cipher = _migration_cipher()
    for emitter_id, ciphertext in rows:
        plaintext = cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        connection.execute(
            sa.text("UPDATE emitters SET csc = :csc WHERE id = :id"),
            {"csc": plaintext, "id": emitter_id},
        )


def _migration_cipher() -> Fernet:
    encryption_key = os.getenv("KILA_SIFEN_ENCRYPTION_KEY")
    if not encryption_key:
        raise RuntimeError(
            "KILA_SIFEN_ENCRYPTION_KEY is required to migrate existing CSC values"
        )
    return Fernet(encryption_key.encode("ascii"))


def _timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

"""Server-side integration configuration.

A Slack incoming-webhook URL is a bearer credential: anyone holding it can post into the
customer's channel. It is therefore stored here and nowhere else — never in browser storage,
never in a response body, never in a CRM/HubSpot payload, never in a log line.

Two structural guarantees rather than conventions:

* `secret` is a **deferred** column, so loading a row does not load the credential. Code that
  needs it has to ask for it by name, which makes every read of it greppable.
* the read API (`GET /api/v1/integrations`) selects `provider` only, so on the one path a
  client can reach, the secret is never fetched from the database at all.

Unlike `share_links.token_hash`, this cannot be hashed: a webhook has to be replayed to Slack
verbatim, so a one-way digest would make it useless. Containment is the guarantee instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.models.base import Base, created_at_col, updated_at_col, uuid_pk

#: The only provider that can be configured today. Kept as a constant so the API and the
#: model agree on the row key without a magic string in two places.
SLACK = "slack"


class IntegrationSetting(Base):
    """One row per configured outbound integration. At most one row per provider."""

    __tablename__ = "integration_settings"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    # The credential. Deferred on purpose — see the module docstring.
    secret: Mapped[str] = deferred(mapped_column(Text, nullable=False))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

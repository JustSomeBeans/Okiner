from __future__ import annotations

# =============================================================================
# config.py — Global constants
# -----------------------------------------------------------------------------
# Imported by:  bot.py      → DB_PATH, SCHEMA_PATH
#               utils.py    → MAX_MESSAGE_LENGTH
#               cogs/rp_commands.py → MAX_EMBED_DESCRIPTION_LENGTH,
#                                     MAX_TEXT_LENGTH, MAX_TYPE_LENGTH,
#                                     MAX_URL_LENGTH
# Imports from: (none — this file has no internal dependencies)
# =============================================================================

from pathlib import Path

DB_PATH = "rp.db"
SCHEMA_PATH = Path(__file__).with_name("rp_schema.sql")

MAX_MESSAGE_LENGTH = 1900
MAX_TYPE_LENGTH = 64
MAX_TEXT_LENGTH = 1500
MAX_URL_LENGTH = 1000
MAX_EMBED_TITLE_LENGTH = 256
MAX_EMBED_DESCRIPTION_LENGTH = 4096
STANDARD_CASE = "standard"
SELF_CASE = "selfcase"
NULL_CASE = "nullcase"
EVERYONE_TARGET = "everyone"

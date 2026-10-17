---
name: okiner-docs
description: Comprehensive architecture, documentation, SQLite schema, command reference, and technical specifications for the Okiner Discord bot. Use when working on Okiner bot development, adding cogs, modifying database queries, configuring slash commands, or reviewing bot features.
---

# Okiner Docs

## Overview

This skill provides complete architectural guidance, database specifications, slash command reference, and technical documentation for the **Okiner** Discord bot.

When working on this repository, reference the root documentation files:
- **[OKINER_DOCUMENTATION.md](../OKINER_DOCUMENTATION.md)**: User and administrator guide covering setup, environment variables, full command table, and operational workflows.
- **[OKINER_PROJECT_DETAILS.md](../OKINER_PROJECT_DETAILS.md)**: Deep technical specification covering SQLite schema (`rp.db` / `rp_schema.sql`), database pool wiring, Discord UI view architectures, case-flow logic (`standard`, `selfcase`, `nullcase`, `standard_self_null`), and dual image input handling.

## Key Developer References

- **Bot Entry & Structure**: `main.py` -> `bot.py` (`OkinerBot`) -> `cogs/`
- **Database Access**: `database.py` with asynchronous `asqlite` pool (`PRAGMA foreign_keys = ON`).
- **Slash Commands & UI**: `cogs/rp_commands.py`, `cogs/family_commands.py`, `cogs/moderation.py`, `cogs/behavior.py`, `views.py`.

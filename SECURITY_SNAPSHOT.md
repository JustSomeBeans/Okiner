# Okiner Security Snapshot

Date: November 9, 2026
Scope: the `main after the hardening merge. This replaces earlier snapshots, which contained inaccurate claims (for example that all data is guild-partitioned and that transaction helpers alone provided atomicity).

## Data model facts

- RP data, configuration, activity counters, and emoji counts are **per server**.
- `marriages` and `children` are **global**. They have no server column by design. The family tree view therefore filters to people who are members of the current server.
- Integrity is enforced by SQLite triggers plus `BEGIN IMMEDIATE` write transactions, not by application checks alone.
- SQLite runs in WAL mode. Every pooled connection is configured by an `init` hook (`foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL`, `synchronous=NORMAL`) and startup verifies the values.

## Hardening in place

| Area | Control |
|---|---|
| Bigamy and relationship integrity | Six triggers reject self/unordered marriages, second marriages, parent-child marriages, self/reverse adoption, and spouse adoption. `add_child` rejects ancestry cycles. Writes are serialized with `BEGIN IMMEDIATE` and roll back on error. |
| Existing bad data | Never auto-deleted. Startup logs users found in several marriage rows. |
| Migrations | Versioned (`PRAGMA user_version`), each in one transaction with triggers dropped and recreated, a verified SQLite-API backup before any pending migration, and refusal to start on a database newer than the code. |
| Duplicate RP entries | Unique expression index; duplicate adds and edits return a friendly message. |
| RP creation | Type and entries written in one transaction; nothing is written before confirmation. |
| Honeypot | Member-only handling, wider staff exemption (owner, Administrator, Manage Server, Ban/Kick Members, Manage Messages, moderator role), role hierarchy and permission pre-checks, ban and delete handled separately, burst de-duplication, guarded log posting, thread coverage. It cannot target the log channel. |
| Least privilege | Requested permissions reduced to what code uses (plus Ban Members, Manage Messages, Read Message History). Presence intent removed. `manage_roles` is not requested. |
| Command errors | One central handler, guild-only check, no exception text shown to users. |
| Authorization | Management commands use channel-aware `interaction.permissions`. Management menus and forms re-check Manage Messages at click and submit time. |
| `/crouton setup` & `/crouton clear` | Partial updates (omitted options kept) via single upsert, and administrator clearing of log channel, honeypot channel, verified role, and moderator role via `database.execute_write` + `invalidate_guild_config`. Rejects @everyone, managed verified role, unusable log channel, and log channel equal to the honeypot channel. |
| Output safety | Single-pass placeholders, escaped display names, scoped mentions, action text truncated safely, backticks neutralized in the manager. |
| Abuse limits | 30 second cooldown and one pending proposal per pair for `/marry` and `/adopt`; double-click guards on proposals and RP back; `/familytree` capped at 40 nodes and rendered off the event loop. |
| Performance | Guild config cache; activity counters batched into one transaction every 15 seconds and flushed at shutdown. |
| Data retention | Member activity removed when a member leaves; all server data removed when the bot is removed from a server. |

## Known limitations and accepted risks

- **Unverification sweep is not implemented.** `/enableunverification` stores a flag and says so. If implemented later it must be log-only by default, skip bots and moderators, never touch roles above the bot, rate-limit role edits, and log every action.
- **Uploaded RP images use Discord CDN links that expire.** Durable storage is not implemented.
- **No self-service data deletion.** Deletion is by command (`/manage_rp`, `/divorce`, `/disown`) or by request to the operator. Relationship records persist across servers until removed.
- **`/crouton setup` performs partial updates (omitted options are kept)**; use `/crouton clear` to clear the log channel, honeypot channel, verified role, and moderator role.
- **In-flight flush race**: a batch being written at the moment a member or server is removed can re-insert one row.
- **The cache is per process.** Running several bot processes against one database would need a different invalidation approach.
- **Backups accumulate** (`rp.db.bak-*`) and contain user IDs. The operator must secure and prune them.
- **Honeypot is destructive by design.** Misconfiguration (a normal channel) bans real members.
- **Permission changes need manual action** on existing servers: Ban Members and Read Message History are not retroactively granted.
- **Presence data** is no longer used; the Presence Intent should stay disabled in the Developer Portal.

## Pre-deployment checklist

1. Back up the live database with SQLite's backup (not a plain copy).
2. Run the new code against a copy of the live database; confirm the startup log shows the migrations applied, `PRAGMA user_version` is 2, and six triggers exist.
3. Confirm the multi-marriage warning (if any) and resolve those rows by hand.
4. Disable the Presence Intent; grant Ban Members and Read Message History where needed.
5. Keep the pre-migration backup until the new version has run cleanly.

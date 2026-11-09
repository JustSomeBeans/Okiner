# Privacy Policy

Last updated: November 7, 2026

This policy explains what data Okiner collects, stores, and uses when it runs as a Discord bot. In short: Okiner stores only what its roleplay, family, security, and moderation features need, does not sell data, and does not share stored data with third parties for advertising, analytics, or profiling.

## Instance Operator

This policy governs the official Okiner bot instance operated by the owner listed in the Contact section.

If you self-host, fork, or modify Okiner, you are responsible for your own privacy policy, contact information, and disclosures. This policy does not cover unofficial instances.

## Who This Applies To

Users and administrators of any Discord server where Okiner is installed. Discord separately processes messages, interactions, and member information under its own terms and privacy policy. This policy covers only what Okiner itself collects, stores, and uses.

## Data Okiner Stores

Okiner stores data in a local SQLite database (`rp.db`).

**Server configuration**

- Discord server IDs for servers that use Okiner features.
- Log channel, honeypot channel, verified role, and moderator role IDs, and the inactivity setting.
- Allowlisted channel IDs for `/scan`.

**Roleplay content**

- RP type names, case labels (`standard`, `selfcase`, `nullcase`), image URLs, text templates, and action text templates added by moderators.
- The Discord user ID of the person who added each entry, and the server ID.
- Uploaded images are stored only as Discord attachment links, not as files.

**Family features** (shared across all servers, not tied to one server)

- Discord user IDs of married users and of parent and child pairs.
- Marriage and adoption timestamps.

**Activity telemetry** (per server)

- Per member: message count, join timestamp, last-active timestamp, and inactivity status and reset timestamps.
- Custom emoji use counts from messages and reactions.
- Counters are kept in memory and written to the database about every 15 seconds and at shutdown.
- The database also has columns reserved for future features that are currently unused and empty: staff-directed message count, daily message counts, daily reaction activity, voice session start, inviter, and invite code.

Okiner does not store the contents of regular chat messages. The only text stored is what is deliberately submitted through Okiner commands. Message content is read in memory to find custom emoji and the `oki!sync` prefix command, and is not saved.

## Data Okiner Uses Temporarily

Okiner reads some Discord data at runtime so commands work, and does not save it unless listed above:

- IDs, names, display names, and mentions of the person running a command and of any target.
- Server member lists for autocomplete and lookup.
- Interaction, modal, select, and button data for guided flows, and message references for temporary buttons.
- For `/scan`: the target's account creation date, avatar state, and similar public profile information used to compute a trust score. Scan results are shown in Discord and are **not** stored.

Gateway intents used: Server Members and Message Content. The Presence Intent is not used, and Okiner does not read or store online status.

## How Data Is Used

- Register, list, edit, and remove roleplay types and entries, and fill placeholders such as `{user}` and `{target}` in responses.
- Resolve target members and enforce permission checks.
- Store, check, and remove marriage and adoption records.
- Run `/scan` and the honeypot (below).
- Keep activity counts and emoji leaderboards.
- Log startup status and errors for maintenance.

## Honeypot Actions

If a server sets a honeypot channel, a non-staff member who posts there is banned and their messages from the last hour are removed. Okiner posts a notice in the server's configured log channel that includes the member's user ID and mention, and whether the ban succeeded. That notice is visible to anyone who can read that channel.

## Logs

Application logs may include the bot account name and ID at startup, an invite URL if `DISCORD_APPLICATION_ID` is configured, and error messages and tracebacks. They are not used for advertising, profiling, or sale. Depending on hosting, they may be kept in the console or hosting provider storage.

## Backups

Before database upgrades, Okiner writes a backup copy of the database (`rp.db.bak-<timestamp>`) on the same machine. Backups contain the same data as the database and are kept until the operator deletes them.

## Data Sharing and Sale

Okiner does not sell user data or share stored data with third parties for advertising, analytics, profiling, or marketing. Okiner operates through Discord, so commands, responses, embeds, and mentions pass through Discord's systems. If a saved image URL points to an external website, Discord may fetch and display that image.

## Data Retention and Deletion

Okiner keeps stored data until it is removed by command, deleted by the operator, or no longer needed.

- `/manage_rp` deletes RP types, entries, and images.
- `/divorce` removes a marriage record; `/disown` removes an adoption record.
- When a member leaves a server, that member's activity record for that server is deleted.
- When Okiner is removed from a server, that server's configuration, scan channels, activity records, emoji counts, and roleplay types and entries are deleted. If the bot was offline at the time, this runs only if it receives the removal event, so contact the operator if data remains.
- Marriage and adoption records are not tied to a server and are not deleted when a server or member leaves; they are removed by `/divorce`, `/disown`, or on request.
- RP entries record the ID of the user who added them; this is not removed when that user leaves.
- A self-service "delete my data" command is not currently available. Contact the operator to request deletion of data for a user or server.

## Access and Control

Roleplay management and moderation commands require Manage Messages or Administrator, checked when a command runs and again when its buttons or forms are used. Marriage and adoption records are created only after the target accepts a confirmation prompt. The operator has access to the database, backups, and logs as needed to run, maintain, debug, back up, or remove the bot.

## Security

Data is stored in a local SQLite database, so its security depends on the machine or hosting environment. The bot token is loaded from environment configuration and must be kept private, along with `.env`, database files, backups, and logs.

## Children's Privacy

Okiner is a general-audience bot and is not directed to children under 13. For users in the United States, Okiner does not knowingly collect personal information from children under 13; if the operator learns that it has, it will delete that information as soon as reasonably possible.

For users in the European Economic Area, the United Kingdom, or other regions with child data protection rules, Okiner is not intended for anyone who cannot lawfully consent to processing under the laws that apply to them, unless a parent or holder of parental responsibility consents where required. Under GDPR Article 8 the default age is 16, though member states may set it as low as 13. Parents or guardians may contact the operator to request review or deletion of a child's data.

## Changes to This Policy

This policy will be updated when Okiner changes in ways that affect the data it collects or stores.

## Contact

For privacy questions or deletion requests, contact the operator of the official Okiner bot instance:

- Operator: Okiner Official
- Email: OkinerOfficial@proton.me

Self-hosters must replace this section with their own contact information before making their instance available to others.

# Privacy Policy

Last updated: June 1, 2026

This privacy policy explains what data Okiner collects, stores, and uses when it runs as a Discord bot. The short version: Okiner stores only the data needed to provide its roleplay and family features, does not sell data, and does not share stored data with third parties for advertising, analytics, or profiling.

## Instance Operator

This policy governs the official Okiner bot instance operated by the bot owner listed in the Contact section below.

If you self-host, fork, modify, or run your own instance of Okiner, you are responsible for providing your own privacy policy, your own operator contact information, and any disclosures required by the way you host, configure, modify, log, or otherwise operate the bot. This policy does not automatically cover unofficial, self-hosted, forked, or modified instances.

## Who This Applies To

This policy applies to users and server administrators of any Discord server where Okiner is installed.

Okiner runs on Discord, so Discord may separately process messages, interactions, member information, and other platform data under Discord's own terms and privacy policy. This policy only covers what Okiner itself collects, stores, and uses.

## Data Okiner Stores

Okiner stores data in a local SQLite database named `rp.db`.

Okiner stores the following server configuration data:

- Discord server IDs for servers that configure roleplay features.
- Roleplay type names created for each server.

Okiner stores the following roleplay content data:

- Discord user IDs for users who add roleplay entries.
- Discord server IDs associated with those entries.
- Roleplay type names.
- Roleplay case labels, such as `standard`, `selfcase`, and `nullcase`.
- Image URLs added by moderators.
- Text templates added by moderators.
- Action text templates added by moderators.

Okiner stores the following family feature data:

- Discord user IDs for married users.
- Discord user IDs for parent and child relationships.
- Marriage timestamps.
- Adoption timestamps.

Okiner does not intentionally store message contents from regular chat messages. The only text content stored by the bot is content deliberately submitted through Okiner commands, such as roleplay text templates, action text templates, roleplay type names, and image URLs.

## Data Okiner Uses Temporarily

Okiner also receives or reads some Discord data at runtime so commands can work. This data is used temporarily and is not intentionally saved unless listed above.

Okiner may temporarily use:

- The Discord user ID of the person running a command.
- The Discord server ID where a command is used.
- The target user's Discord ID, mention, username, and display name when a command targets another member.
- Server member lists, usernames, display names, and user IDs for target autocomplete and member lookup.
- Interaction data needed to reply to slash commands and button clicks.
- Message references for temporary confirmation buttons and roleplay back buttons.

The bot currently enables these Discord gateway intents in code:

- Presence Intent.
- Server Members Intent.
- Message Content Intent.

At the time of this policy, Okiner uses member data for member lookup and autocomplete. Okiner does not intentionally store presence data or regular message content. Message Content Intent is enabled for bot operation and prefix command support, but regular chat messages are not saved by Okiner.

## How Data Is Used

Okiner uses stored and temporary data to:

- Register, list, and remove roleplay types for a server.
- Save, list, remove, and randomly select roleplay images, text templates, and action text templates.
- Replace placeholders like `{user}`, `{target}`, `{user_name}`, and `{target_name}` when generating roleplay responses.
- Resolve a typed or autocompleted target member for roleplay commands.
- Enforce command behavior, such as moderator-only roleplay management commands and owner-only sync commands.
- Store and check marriage relationships.
- Store and check parent-child adoption relationships.
- Remove relationship records when divorce or disown commands are used.
- Send command responses, confirmation prompts, and temporary buttons.
- Log startup status and unexpected errors for debugging and maintenance.

## Logs

Okiner uses application logs for operational visibility and debugging.

Logs may include:

- The bot account name and bot user ID when the bot starts.
- An invite URL if `DISCORD_APPLICATION_ID` is configured.
- Error messages and Python tracebacks when a command or database operation fails.

Logs are not used for advertising, profiling, or sale. Depending on the hosting environment, logs may be written to the console, terminal, process manager, or hosting provider log storage.

## Data Sharing and Sale

Okiner does not sell user data.

Okiner does not share stored user data with third parties for advertising, analytics, profiling, or marketing.

Okiner necessarily operates through Discord. Command inputs, command responses, embeds, buttons, mentions, and other Discord interactions pass through Discord's systems. If a saved image URL points to an external website, that URL may be displayed in a Discord embed or message as part of the roleplay feature.

## Data Retention

Okiner keeps stored data until it is removed by command, deleted from the database by the bot owner/operator, or no longer needed for the bot's operation.

Current command-based deletion includes:

- `/removetype`, which removes a roleplay type and its saved roleplay entries for that server.
- `/removeimage`, which removes a saved image URL.
- `/removetext`, `/removeselftext`, and `/removenulltext`, which remove saved text templates.
- `/removeactiontext`, `/removeselfactiontext`, and `/removenullactiontext`, which remove saved action text templates.
- `/divorce`, which removes a marriage record.
- `/disown`, which removes an adoption relationship record.

Server administrators or users may contact the bot owner/operator to request deletion of data associated with a server or user if command-based deletion is not enough.

## Access and Control

Roleplay management commands are restricted to users with the Manage Messages permission.

Family feature commands can be used by server members in servers where Okiner is installed. Marriage and adoption records are created only after the target user accepts the bot's confirmation prompt.

The bot owner/operator has access to the bot's database and logs as needed to run, maintain, debug, back up, or remove the bot.

## Security

Okiner stores data in a local SQLite database. Access to that database depends on the security of the machine or hosting environment where the bot is running.

The bot token is loaded from environment configuration and should not be shared publicly. Anyone operating this bot should keep the `.env` file, database files, and runtime logs private.

## Children's Privacy

Okiner is a general-audience Discord bot. It is not directed to children under 13, and the official Okiner instance is not intended for use by children under 13.

For users in the United States, Okiner does not knowingly collect personal information from children under 13. If the operator learns that personal information from a child under 13 has been collected without verifiable parental consent, the operator will delete that information as soon as reasonably possible.

For users in the European Economic Area, United Kingdom, or other regions with child data protection rules, Okiner is not intended for use by anyone who cannot lawfully consent to personal data processing under the laws that apply to them, unless consent is given or authorized by a parent or holder of parental responsibility where required. Under GDPR Article 8, the default age for a child to consent to information society services is 16, but EU member states may set a lower age down to 13.

Parents, guardians, or holders of parental responsibility may contact the operator using the Contact section below to request review or deletion of a child's data.

## Changes to This Policy

This policy may be updated as Okiner changes. If new features collect or store new kinds of data, this policy should be updated to disclose those changes.

## Contact

For privacy questions or deletion requests, contact the owner/operator of the official Okiner bot instance:

- Operator name or handle: `[paste operator name or handle here]`
- Contact method: `[paste email, Discord username, support server, or other contact method here]`
- Additional contact notes: `[paste optional response-time, jurisdiction, or server-specific notes here]`

Self-hosters must replace this section with their own contact information before making their instance available to others.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rp_types (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    PRIMARY KEY (guild_id, type)
);

CREATE TABLE IF NOT EXISTS roleplay_entries (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    case_type TEXT NOT NULL DEFAULT 'standard',
    url TEXT,
    texts TEXT,
    action_texts TEXT,
    PRIMARY KEY (user_id, guild_id, type, case_type, url, texts, action_texts),
    FOREIGN KEY (guild_id, type)
        REFERENCES rp_types(guild_id, type)
        ON DELETE CASCADE
);



CREATE TABLE IF NOT EXISTS children (
    offspring_id INTEGER PRIMARY KEY AUTOINCREMENT, 
    child_id INTEGER UNIQUE NOT NULL, 
    parent_id INTEGER NOT NULL,
    adoption_date TEXT
);

CREATE TABLE IF NOT EXISTS marriages (
    marriage_id INTEGER PRIMARY KEY,
    spouse1_id INTEGER UNIQUE NOT NULL,
    spouse2_id INTEGER UNIQUE NOT NULL,
    marriage_date TEXT,
    UNIQUE (spouse1_id, spouse2_id)
);

CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id INTEGER PRIMARY KEY,
    log_channel_id INTEGER NULL,
    honeypot_channel_id INTEGER NULL,
    verified_role_id INTEGER NULL,
    moderator_role_id INTEGER NULL,
    inactivity_system_enabled BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_channels (
    guild_id INTEGER,
    channel_id INTEGER,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS member_behavior (
    guild_id INTEGER,
    user_id INTEGER,
    joined_at INTEGER,
    total_messages INTEGER DEFAULT 0,
    staff_directed_messages INTEGER DEFAULT 0,
    daily_message_counts TEXT,
    daily_reaction_activity TEXT,
    voice_session_started_at INTEGER NULL,
    invited_by INTEGER NULL,
    invite_code TEXT NULL,
    last_active_at INTEGER,
    inactivity_status TEXT NULL,
    inactivity_reset_at INTEGER NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_emojis (
    guild_id INTEGER,
    emoji_id INTEGER,
    message_uses INTEGER DEFAULT 0,
    reaction_uses INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, emoji_id)
);

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
    url TEXT,
    texts TEXT,
    action_texts TEXT,
    PRIMARY KEY (user_id, guild_id, type, url, texts, action_texts),
    FOREIGN KEY (guild_id, type)
        REFERENCES rp_types(guild_id, type)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rp_self_cases (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    texts TEXT,
    action_texts TEXT,
    url TEXT,
    PRIMARY KEY (guild_id, type),
    FOREIGN KEY (guild_id, type)
        REFERENCES rp_types(guild_id, type)
        ON DELETE CASCADE
);
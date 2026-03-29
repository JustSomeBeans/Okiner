PRAGMA foreign_keys = ON;

CREATE TABLE rp_types (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    PRIMARY KEY (guild_id, type)
);

CREATE TABLE roleplay_entries (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    url TEXT,
    texts TEXT,
    PRIMARY KEY (user_id, guild_id, type, url, texts)
    FOREIGN KEY (guild_id, type)
        REFERENCES rp_types(guild_id, type)
        ON DELETE CASCADE
);
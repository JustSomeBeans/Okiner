CREATE TABLE rp_types (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    UNIQUE (guild_id, type)
);

CREATE TABLE roleplay_entries (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    url TEXT,
    texts TEXT
);
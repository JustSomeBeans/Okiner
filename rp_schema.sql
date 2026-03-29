CREATE TABLE "roleplay" (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    url TEXT,
    texts TEXT,
    type TEXT NOT NULL,
    UNIQUE (user_id, guild_id, url, texts, type)
)
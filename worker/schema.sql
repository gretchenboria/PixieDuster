-- Daily usage counters. One row per (day, account), plus a __global__ row
-- carrying the total for the whole service that day.
CREATE TABLE IF NOT EXISTS usage (
  day TEXT    NOT NULL,
  who TEXT    NOT NULL,
  n   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, who)
);

-- Old days are only kept for curiosity; safe to prune.
CREATE INDEX IF NOT EXISTS usage_by_day ON usage (day);

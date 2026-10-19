-- The seven app tables. The supplied scheduling file is never touched by this script.

CREATE TABLE conversations (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  public_id TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16)))),
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_activity_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  ended_at TEXT,
  outcome TEXT CHECK (outcome IN ('contained','handoff','safety_stop','failed')),
  outcome_reason TEXT,
  intent TEXT NOT NULL DEFAULT 'unknown',
  customer_id TEXT,
  intents_seen TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(intents_seen)),
  identify_attempts INTEGER NOT NULL DEFAULT 0,
  resolved_at TEXT,
  solved TEXT CHECK (solved IN ('yes','no')),
  solved_at TEXT,
  turn_count INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  CHECK ((outcome IS NULL) = (ended_at IS NULL))
);
CREATE INDEX idx_conversations_started_at ON conversations (started_at DESC);
CREATE INDEX idx_conversations_outcome_started ON conversations (outcome, started_at);
CREATE INDEX idx_conversations_idle ON conversations (last_activity_at) WHERE outcome IS NULL;

CREATE TABLE turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations (id),
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'message' CHECK (kind IN ('message','solved_answer')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  caller_text TEXT NOT NULL,
  reply_text TEXT NOT NULL,
  model_messages TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(model_messages)),
  safety_verdict TEXT,
  tools_called TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tools_called)),
  retrieved TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(retrieved)),
  offered TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(offered)),
  has_write INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL,
  error TEXT,
  fallback_used INTEGER NOT NULL DEFAULT 0,
  trace_id TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cost_usd REAL NOT NULL DEFAULT 0,
  cost_source TEXT NOT NULL DEFAULT 'estimated' CHECK (cost_source IN ('reported','estimated')),
  UNIQUE (conversation_id, seq)
);
CREATE INDEX idx_turns_created_at ON turns (created_at);

CREATE TABLE visit_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations (id),
  action TEXT NOT NULL CHECK (action IN ('book','move','cancel')),
  appointment_id INTEGER NOT NULL,
  slot_id INTEGER NOT NULL,
  previous_slot_id INTEGER,
  customer_id TEXT NOT NULL,
  confirmed_date TEXT,
  confirmed_window TEXT,
  confirmed_technician TEXT,
  late_fee_applied INTEGER,
  committed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  retired_at TEXT,
  CHECK (action <> 'move' OR previous_slot_id IS NOT NULL)
);
CREATE INDEX idx_visit_changes_conversation ON visit_changes (conversation_id);
CREATE INDEX idx_visit_changes_appointment ON visit_changes (appointment_id);
CREATE INDEX idx_visit_changes_committed ON visit_changes (committed_at);

CREATE TABLE handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations (id),
  kind TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(reason) > 0),
  by_error INTEGER NOT NULL DEFAULT 0,
  customer_id TEXT,
  caller_name TEXT,
  caller_phone TEXT,
  stated_by_caller INTEGER NOT NULL DEFAULT 0,
  intent TEXT NOT NULL CHECK (length(intent) > 0),
  told_caller TEXT NOT NULL CHECK (length(told_caller) > 0),
  summary_source TEXT NOT NULL DEFAULT 'agent',
  preferred_window TEXT CHECK (preferred_window IN ('morning','afternoon','evening')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','followed_up')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  followed_up_at TEXT
);
CREATE INDEX idx_handoffs_status_created ON handoffs (status, created_at);

CREATE TABLE waitlist_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations (id),
  customer_id TEXT NOT NULL,
  caller_name TEXT NOT NULL,
  caller_phone TEXT NOT NULL,
  service_type TEXT NOT NULL,
  zone TEXT NOT NULL,
  held_date TEXT NOT NULL,
  held_window TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (customer_id, service_type, held_date, held_window)
);
CREATE INDEX idx_waitlist_created ON waitlist_entries (created_at);

CREATE TABLE flags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations (id),
  note TEXT NOT NULL CHECK (length(note) > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_flags_conversation ON flags (conversation_id);

CREATE TABLE eval_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations (id),
  scenario_id TEXT NOT NULL UNIQUE,
  scenario TEXT NOT NULL CHECK (json_valid(scenario)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

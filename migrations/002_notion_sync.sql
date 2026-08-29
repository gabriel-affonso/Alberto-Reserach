ALTER TABLE digest_items ADD COLUMN reading_id INTEGER REFERENCES readings(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS notion_article_syncs (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  notion_page_id TEXT NOT NULL,
  last_digest_item_id TEXT REFERENCES digest_items(id) ON DELETE SET NULL,
  last_synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (project_id, paper_id)
);

CREATE INDEX IF NOT EXISTS idx_notion_article_syncs_page
  ON notion_article_syncs(notion_page_id);

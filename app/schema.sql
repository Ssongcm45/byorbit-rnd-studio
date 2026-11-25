-- ByOrbit R&D Studio 개인용 — SQLite 스키마 (30 테이블 + 전문검색)
-- 테이블·컬럼 이름은 팀판과 같게 둔다. ID는 모두 UUID(32자리 hex) 문자열.
PRAGMA foreign_keys = ON;

-- A. 온톨로지·시소러스 ------------------------------------------------------
CREATE TABLE IF NOT EXISTS concept_scheme (
  scheme_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, version TEXT, released_at TEXT
);
CREATE TABLE IF NOT EXISTS onto_class (
  class_id TEXT PRIMARY KEY, iri TEXT UNIQUE, label_ko TEXT, label_en TEXT,
  parent_class_id TEXT REFERENCES onto_class(class_id)
);
CREATE TABLE IF NOT EXISTS concept (
  concept_id TEXT PRIMARY KEY,
  scheme_id TEXT REFERENCES concept_scheme(scheme_id),
  class_id TEXT REFERENCES onto_class(class_id),
  iri TEXT UNIQUE, pref_label_ko TEXT NOT NULL, pref_label_en TEXT, definition TEXT,
  origin TEXT NOT NULL DEFAULT 'seed' CHECK (origin IN ('seed','mine')),
  status TEXT NOT NULL DEFAULT 'active', created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS concept_label (
  label_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL REFERENCES concept(concept_id) ON DELETE CASCADE,
  label TEXT NOT NULL, lang TEXT, label_type TEXT NOT NULL CHECK (label_type IN ('pref','alt','hidden'))
);
CREATE INDEX IF NOT EXISTS ix_concept_label_label ON concept_label(label);
CREATE TABLE IF NOT EXISTS concept_relation (
  concept_id TEXT NOT NULL REFERENCES concept(concept_id) ON DELETE CASCADE,
  target_concept_id TEXT NOT NULL REFERENCES concept(concept_id) ON DELETE CASCADE,
  rel_type TEXT NOT NULL,
  PRIMARY KEY (concept_id, target_concept_id, rel_type)
);

-- B. 프로젝트·자료 ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS project (
  project_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS project_item (
  project_id TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, added_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (project_id, entity_type, entity_id)
);
CREATE TABLE IF NOT EXISTS source (
  source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, title TEXT, authors TEXT, year INTEGER,
  doi TEXT, license TEXT,
  confidentiality TEXT NOT NULL DEFAULT '일반' CHECK (confidentiality IN ('일반','내부','기밀')),
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS document (
  doc_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source(source_id) ON DELETE CASCADE,
  file_uri TEXT NOT NULL, file_name TEXT NOT NULL, mime TEXT, sha256 TEXT UNIQUE,
  parse_status TEXT NOT NULL DEFAULT '{}', parser_ver TEXT, note TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS doc_section (
  section_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  parent_section_id TEXT REFERENCES doc_section(section_id), heading TEXT, ord INTEGER,
  page_from INTEGER, page_to INTEGER
);
CREATE TABLE IF NOT EXISTS doc_table (
  table_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  section_id TEXT REFERENCES doc_section(section_id), caption TEXT, page INTEGER, cells_json TEXT
);
CREATE TABLE IF NOT EXISTS chunk (
  chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  section_id TEXT REFERENCES doc_section(section_id), table_id TEXT REFERENCES doc_table(table_id),
  parent_chunk_id TEXT REFERENCES chunk(chunk_id),
  chunk_type TEXT NOT NULL CHECK (chunk_type IN ('text','table','summary')),
  ord INTEGER, text TEXT NOT NULL, page INTEGER, bbox TEXT
);
CREATE INDEX IF NOT EXISTS ix_chunk_doc ON chunk(doc_id);

-- 전문검색: 3글자 이상은 trigram 색인, 짧은 말은 LIKE로 보완한다
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
  text, content='chunk', content_rowid='rowid', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
  INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
  INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
  INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
  INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text);
END;

-- C. 라벨링 -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS annotation (
  ann_id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
  span_start INTEGER, span_end INTEGER, surface_text TEXT NOT NULL,
  label_type TEXT NOT NULL, concept_id TEXT REFERENCES concept(concept_id),
  normalized_value TEXT, unit_concept_id TEXT REFERENCES concept(concept_id),
  confidence REAL, method TEXT NOT NULL CHECK (method IN ('dict','regex','llm','human')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('auto','pending','accepted','rejected')),
  engine TEXT, reviewed_at TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_ann_chunk ON annotation(chunk_id);
CREATE INDEX IF NOT EXISTS ix_ann_status ON annotation(status);
CREATE TABLE IF NOT EXISTS relation_annotation (
  rel_id TEXT PRIMARY KEY, head_ann_id TEXT NOT NULL REFERENCES annotation(ann_id) ON DELETE CASCADE,
  tail_ann_id TEXT NOT NULL REFERENCES annotation(ann_id) ON DELETE CASCADE,
  rel_type TEXT NOT NULL, confidence REAL, status TEXT NOT NULL DEFAULT 'pending'
);

-- D. 도메인 사실 ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS byproduct (
  byproduct_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL UNIQUE REFERENCES concept(concept_id),
  sector TEXT, commodity_concept_id TEXT REFERENCES concept(concept_id),
  generating_process_concept_id TEXT REFERENCES concept(concept_id)
);
CREATE TABLE IF NOT EXISTS sample (
  sample_id TEXT PRIMARY KEY, byproduct_id TEXT REFERENCES byproduct(byproduct_id),
  supplier TEXT, collected_at TEXT, pretreatment_concept_id TEXT REFERENCES concept(concept_id),
  pretreatment_text TEXT, lot_no TEXT, sample_code TEXT,
  confidentiality TEXT NOT NULL DEFAULT '기밀' CHECK (confidentiality IN ('일반','내부','기밀')),
  coa_doc_id TEXT REFERENCES document(doc_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS measurement (
  meas_id TEXT PRIMARY KEY, byproduct_id TEXT REFERENCES byproduct(byproduct_id),
  sample_id TEXT REFERENCES sample(sample_id) ON DELETE CASCADE,
  target_concept_id TEXT REFERENCES concept(concept_id), target_text TEXT NOT NULL,
  value REAL, value_text TEXT, unit_concept_id TEXT REFERENCES concept(concept_id), unit_text TEXT,
  basis TEXT, method_concept_id TEXT REFERENCES concept(concept_id), method_text TEXT,
  ann_id TEXT REFERENCES annotation(ann_id) ON DELETE SET NULL,
  doc_id TEXT REFERENCES document(doc_id) ON DELETE CASCADE,
  entry TEXT NOT NULL CHECK (entry IN ('coa','extracted','manual')),
  verified_at TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS conversion_run (
  conv_id TEXT PRIMARY KEY, byproduct_id TEXT REFERENCES byproduct(byproduct_id),
  process_concept_id TEXT REFERENCES concept(concept_id), params_json TEXT,
  output_concept_id TEXT REFERENCES concept(concept_id), yield_pct REAL,
  ann_id TEXT REFERENCES annotation(ann_id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS application_fit (
  fit_id TEXT PRIMARY KEY, byproduct_id TEXT REFERENCES byproduct(byproduct_id),
  application_concept_id TEXT REFERENCES concept(concept_id), trl INTEGER,
  evidence_count INTEGER, regulatory_status TEXT
);
CREATE TABLE IF NOT EXISTS regulation (
  reg_id TEXT PRIMARY KEY, title TEXT, jurisdiction TEXT, article TEXT,
  applies_to_concept_id TEXT REFERENCES concept(concept_id), effective_date TEXT,
  source_id TEXT REFERENCES source(source_id)
);
CREATE TABLE IF NOT EXISTS lca_result (
  lca_id TEXT PRIMARY KEY, byproduct_id TEXT REFERENCES byproduct(byproduct_id),
  conv_id TEXT REFERENCES conversion_run(conv_id), functional_unit TEXT,
  gwp_kgco2e REAL, water_m3 REAL, method TEXT
);

-- E. 실행·리포트 ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workflow (
  wf_id TEXT PRIMARY KEY, name TEXT NOT NULL, graph_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1, is_template INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY, wf_id TEXT REFERENCES workflow(wf_id), wf_version INTEGER,
  status TEXT NOT NULL DEFAULT 'running', started_at TEXT DEFAULT (datetime('now')), finished_at TEXT
);
CREATE TABLE IF NOT EXISTS run_step (
  step_id TEXT PRIMARY KEY, run_id TEXT REFERENCES run(run_id) ON DELETE CASCADE,
  node_key TEXT, agent_key TEXT, engine TEXT, session_id TEXT,
  input_json TEXT, output_json TEXT, duration_ms INTEGER, status TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS hypothesis (
  hyp_id TEXT PRIMARY KEY, run_id TEXT REFERENCES run(run_id), statement TEXT NOT NULL,
  byproduct_id TEXT REFERENCES byproduct(byproduct_id),
  application_concept_id TEXT REFERENCES concept(concept_id), novelty REAL, feasibility REAL
);
CREATE TABLE IF NOT EXISTS experiment_plan (
  exp_id TEXT PRIMARY KEY, hyp_id TEXT REFERENCES hypothesis(hyp_id), design_type TEXT,
  factors_json TEXT, responses_json TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS report (
  report_id TEXT PRIMARY KEY, run_id TEXT REFERENCES run(run_id), title TEXT NOT NULL,
  body_md TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', confirmed_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS report_citation (
  cit_id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES report(report_id) ON DELETE CASCADE,
  claim_text TEXT NOT NULL, chunk_id TEXT REFERENCES chunk(chunk_id),
  measurement_id TEXT REFERENCES measurement(meas_id)
);

-- F. 기록 -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS change_log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT, row_id TEXT,
  before_json TEXT, after_json TEXT, at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage_log (
  usage_id TEXT PRIMARY KEY, run_id TEXT REFERENCES run(run_id), engine TEXT, session_id TEXT,
  task TEXT, duration_ms INTEGER, chunks INTEGER, ok INTEGER, at TEXT DEFAULT (datetime('now'))
);

-- G. 자료 수집 (공식 API·크롤러) — M3 ---------------------------------------
CREATE TABLE IF NOT EXISTS collect_query (
  query_id TEXT PRIMARY KEY, name TEXT NOT NULL, query TEXT NOT NULL,
  sources_json TEXT NOT NULL DEFAULT '[]', project TEXT,
  auto INTEGER NOT NULL DEFAULT 0, interval_h INTEGER NOT NULL DEFAULT 24,
  last_run_at TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS collect_item (
  item_id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
  doi TEXT, title TEXT NOT NULL, title_key TEXT, year INTEGER, doc_type TEXT,
  item_json TEXT NOT NULL, oa INTEGER,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','accepted','rejected','ingested')),
  doc_id TEXT REFERENCES document(doc_id) ON DELETE SET NULL,
  query_id TEXT REFERENCES collect_query(query_id) ON DELETE SET NULL,
  first_seen_at TEXT DEFAULT (datetime('now')), UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_collect_item_doi ON collect_item(doi);
CREATE INDEX IF NOT EXISTS idx_collect_item_title ON collect_item(title_key);
CREATE TABLE IF NOT EXISTS collect_job (
  job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, query_id TEXT, query TEXT, sources_json TEXT,
  status TEXT NOT NULL DEFAULT 'running', stats_json TEXT, error TEXT,
  started_at TEXT DEFAULT (datetime('now')), finished_at TEXT
);

-- H. 내 실험 (공정 흐름 workflow 위에서 조건·결과 기록, 예측과 비교) — M3 ----
CREATE TABLE IF NOT EXISTS experiment (
  exp_id TEXT PRIMARY KEY, name TEXT NOT NULL, wf_id TEXT REFERENCES workflow(wf_id),
  byproduct_id TEXT REFERENCES byproduct(byproduct_id), plan_id TEXT REFERENCES experiment_plan(exp_id),
  confidentiality TEXT NOT NULL DEFAULT '내부' CHECK (confidentiality IN ('일반','내부','기밀')),
  note TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS experiment_run (
  xrun_id TEXT PRIMARY KEY, exp_id TEXT NOT NULL REFERENCES experiment(exp_id) ON DELETE CASCADE,
  label TEXT, conditions_json TEXT NOT NULL DEFAULT '{}', run_date TEXT, note TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS experiment_value (
  xval_id TEXT PRIMARY KEY, xrun_id TEXT NOT NULL REFERENCES experiment_run(xrun_id) ON DELETE CASCADE,
  step_key TEXT, target_text TEXT NOT NULL, target_concept_id TEXT REFERENCES concept(concept_id),
  value REAL, value_text TEXT, unit_text TEXT, basis TEXT,
  kind TEXT NOT NULL DEFAULT 'measured' CHECK (kind IN ('measured','predicted')),
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE SCHEMA IF NOT EXISTS stackplan;
SET LOCAL search_path TO stackplan;

CREATE TABLE projects (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 150),
    week_count integer NOT NULL CHECK (week_count BETWEEN 1 AND 52),
    status text NOT NULL DEFAULT 'Created' CHECK (status IN ('Created','Processing','Ready','Failed','Interrupted')),
    job_id uuid UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'Created') = (job_id IS NULL))
);
CREATE TABLE processing_jobs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL UNIQUE REFERENCES projects(id),
    submission_key text NOT NULL CHECK (length(submission_key) BETWEEN 8 AND 128),
    status text NOT NULL CHECK (status IN ('queued','running','Ready','Failed','Interrupted')),
    stage text NOT NULL CHECK (stage IN ('queued','parsing','extracting','validating','complete','failed','interrupted')),
    lease_token uuid,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE (project_id, submission_key),
    UNIQUE (id, project_id),
    CHECK ((status = 'running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL))
);
ALTER TABLE projects ADD CONSTRAINT project_accepted_job_fk FOREIGN KEY(job_id,id) REFERENCES processing_jobs(id,project_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE modules (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    job_id uuid NOT NULL,
    module_title text NOT NULL CHECK (length(module_title) BETWEEN 1 AND 200),
    normalized_title text NOT NULL CHECK (length(normalized_title) BETWEEN 1 AND 200),
    credit integer NOT NULL CHECK (credit BETWEEN 1 AND 100),
    position integer NOT NULL CHECK (position BETWEEN 0 AND 19),
    FOREIGN KEY(job_id,project_id) REFERENCES processing_jobs(id,project_id),
    UNIQUE(project_id,normalized_title), UNIQUE(job_id,position), UNIQUE(id,job_id)
);
CREATE TABLE documents (
    id uuid PRIMARY KEY,
    module_id uuid NOT NULL REFERENCES modules(id),
    filename text NOT NULL CHECK(length(filename) BETWEEN 1 AND 200),
    media_type text NOT NULL CHECK(media_type IN ('application/pdf','image/png','image/jpeg')),
    size bigint NOT NULL CHECK(size BETWEEN 1 AND 10485760),
    checksum text NOT NULL CHECK(checksum ~ '^[0-9a-f]{64}$'),
    storage_key text NOT NULL UNIQUE CHECK(storage_key ~ '^originals/[0-9a-f-]{36}\.(pdf|png|jpg)$'),
    UNIQUE(module_id,checksum), UNIQUE(id,module_id)
);
CREATE TABLE parse_snapshots (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL UNIQUE REFERENCES documents(id),
    parser_version text NOT NULL CHECK(length(parser_version) BETWEEN 1 AND 100),
    chunk_count integer NOT NULL CHECK(chunk_count BETWEEN 1 AND 128),
    UNIQUE(id,document_id)
);
CREATE TABLE source_elements (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id),
    parse_id uuid NOT NULL,
    text text NOT NULL CHECK(octet_length(text) BETWEEN 1 AND 64000),
    regions jsonb NOT NULL CHECK(jsonb_typeof(regions) = 'array'),
    context text NOT NULL CHECK(length(context) <= 2000),
    position integer NOT NULL CHECK(position >= 0),
    FOREIGN KEY(parse_id,document_id) REFERENCES parse_snapshots(id,document_id),
    UNIQUE(parse_id,position)
);
CREATE TABLE extraction_results (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES processing_jobs(id),
    module_id uuid NOT NULL,
    published boolean NOT NULL DEFAULT false,
    uncertainties jsonb NOT NULL CHECK(jsonb_typeof(uncertainties)='array'),
    metrics jsonb NOT NULL CHECK(jsonb_typeof(metrics)='object'),
    FOREIGN KEY(module_id,job_id) REFERENCES modules(id,job_id),
    UNIQUE(job_id,module_id), UNIQUE(id,module_id)
);
CREATE TABLE assessments (
    id uuid PRIMARY KEY,
    result_id uuid NOT NULL,
    module_id uuid NOT NULL REFERENCES modules(id),
    parent_assessment_id uuid,
    facts jsonb NOT NULL CHECK(jsonb_typeof(facts)='object'),
    FOREIGN KEY(result_id,module_id) REFERENCES extraction_results(id,module_id),
    UNIQUE(id,result_id,module_id),
    FOREIGN KEY(parent_assessment_id,result_id,module_id) REFERENCES assessments(id,result_id,module_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE assessment_evidence (
    assessment_id uuid NOT NULL REFERENCES assessments(id),
    field text NOT NULL CHECK(field IN ('name','kind','weight_percent','weight_scope','week','end_week','parent_key')),
    source_element_id uuid NOT NULL REFERENCES source_elements(id),
    PRIMARY KEY(assessment_id,field,source_element_id)
);
CREATE TABLE processing_issues (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES processing_jobs(id),
    module_id uuid,
    document_id uuid REFERENCES documents(id),
    code text NOT NULL CHECK(length(code) BETWEEN 1 AND 64),
    severity text NOT NULL CHECK(severity IN ('error','warning')),
    message text NOT NULL CHECK(length(message) BETWEEN 1 AND 500),
    scope text NOT NULL CHECK(scope IN ('request','system','module','document','assessment')),
    FOREIGN KEY(module_id,job_id) REFERENCES modules(id,job_id)
);
CREATE UNIQUE INDEX source_warning_once ON processing_issues(job_id,document_id,code) WHERE severity='warning';
CREATE TABLE review_revisions (
    id uuid PRIMARY KEY,
    result_id uuid NOT NULL,
    assessment_id uuid NOT NULL,
    module_id uuid NOT NULL,
    revision integer NOT NULL CHECK(revision > 0),
    facts jsonb NOT NULL CHECK(jsonb_typeof(facts)='object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(assessment_id,result_id,module_id) REFERENCES assessments(id,result_id,module_id),
    UNIQUE(assessment_id,revision)
);
CREATE INDEX queued_jobs ON processing_jobs(created_at) WHERE status='queued';
CREATE INDEX running_leases ON processing_jobs(lease_expires_at) WHERE status='running';
CREATE INDEX document_module ON documents(module_id);
CREATE INDEX source_document ON source_elements(document_id);
CREATE INDEX results_project_lookup ON extraction_results(job_id) WHERE published;

-- Published facts, original metadata, evidence and reviews are append-only.
CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable_record'; END; $$;
CREATE TRIGGER immutable_documents BEFORE UPDATE OR DELETE ON documents FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_assessments BEFORE UPDATE OR DELETE ON assessments FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON assessment_evidence FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_parses BEFORE UPDATE OR DELETE ON parse_snapshots FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_sources BEFORE UPDATE OR DELETE ON source_elements FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER immutable_reviews BEFORE UPDATE OR DELETE ON review_revisions FOR EACH ROW EXECUTE FUNCTION reject_mutation();

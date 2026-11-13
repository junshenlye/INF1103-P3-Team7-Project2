SET LOCAL search_path TO stackplan;

ALTER TABLE projects DROP CONSTRAINT projects_status_check;
ALTER TABLE projects ADD CHECK(status IN ('Created','Processing','Ready','Partial','Failed','Interrupted'));
ALTER TABLE processing_jobs DROP CONSTRAINT processing_jobs_status_check;
ALTER TABLE processing_jobs ADD CHECK(status IN ('queued','running','Ready','Partial','Failed','Interrupted'));
ALTER TABLE processing_jobs ADD COLUMN recoveries integer NOT NULL DEFAULT 0;
ALTER TABLE processing_issues ADD COLUMN resolved boolean NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN event_sequence bigint NOT NULL DEFAULT 0;
ALTER TABLE extraction_results DROP CONSTRAINT extraction_results_job_id_module_id_key;

CREATE OR REPLACE FUNCTION enforce_project_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id<>OLD.id OR NEW.name<>OLD.name OR NEW.week_count<>OLD.week_count OR
       (OLD.job_id IS NOT NULL AND NEW.job_id IS DISTINCT FROM OLD.job_id) OR
       NOT (NEW.status=OLD.status OR
         (OLD.status='Created' AND NEW.status='Processing') OR
         (OLD.status='Processing' AND NEW.status IN ('Ready','Partial','Failed','Interrupted')) OR
         (OLD.status IN ('Ready','Partial','Failed','Interrupted') AND NEW.status='Processing')) THEN
        RAISE EXCEPTION 'invalid_project_transition' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE OR REPLACE FUNCTION enforce_job_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id<>OLD.id OR NEW.project_id<>OLD.project_id OR NEW.submission_key<>OLD.submission_key OR
       NOT ((OLD.status='queued' AND NEW.status='running') OR
         (OLD.status='running' AND NEW.status IN ('running','queued','Ready','Partial','Failed','Interrupted')) OR
         (OLD.status IN ('Ready','Partial','Failed','Interrupted') AND NEW.status='queued')) THEN
        RAISE EXCEPTION 'invalid_job_transition' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;

CREATE TABLE document_tasks (
    document_id uuid PRIMARY KEY REFERENCES documents(id),
    job_id uuid NOT NULL REFERENCES processing_jobs(id),
    generation integer NOT NULL DEFAULT 1 CHECK(generation>0),
    state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed')),
    inference text NOT NULL DEFAULT 'unknown' CHECK(inference IN ('unknown','understood','partially_understood','cannot_infer','no_assessment_content')),
    owner_token uuid,
    issues jsonb NOT NULL DEFAULT '[]',
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK((state='running')=(owner_token IS NOT NULL))
);
CREATE INDEX document_queue ON document_tasks(job_id,state);
INSERT INTO document_tasks(document_id,job_id,state,inference)
SELECT d.id,m.job_id,
 CASE WHEN r.id IS NOT NULL THEN 'succeeded' WHEN j.status IN ('queued','running') THEN 'queued' ELSE 'failed' END,
 CASE WHEN r.id IS NOT NULL THEN 'understood' ELSE 'unknown' END
FROM documents d JOIN modules m ON m.id=d.module_id JOIN processing_jobs j ON j.id=m.job_id
LEFT JOIN extraction_results r ON r.module_id=m.id;
CREATE FUNCTION enqueue_document() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO document_tasks(document_id,job_id) SELECT NEW.id,job_id FROM modules WHERE id=NEW.module_id;
 RETURN NEW;
END; $$;
CREATE TRIGGER document_enqueue AFTER INSERT ON documents FOR EACH ROW EXECUTE FUNCTION enqueue_document();

CREATE TABLE document_chunks (
 document_id uuid NOT NULL REFERENCES documents(id),
 chunk_index integer NOT NULL CHECK(chunk_index>=0),
 parse_id uuid NOT NULL REFERENCES parse_snapshots(id),
 records jsonb NOT NULL,
 uncertainties jsonb NOT NULL,
 PRIMARY KEY(document_id,chunk_index),
 FOREIGN KEY(parse_id,document_id) REFERENCES parse_snapshots(id,document_id)
);
CREATE TRIGGER immutable_chunks BEFORE UPDATE OR DELETE ON document_chunks FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TABLE extraction_attempts (
 id bigserial PRIMARY KEY, document_id uuid NOT NULL REFERENCES documents(id), generation integer NOT NULL,
 stage text NOT NULL, chunk_index integer, attempt integer NOT NULL, code text NOT NULL,
 message text NOT NULL, provider_status integer, rejected jsonb, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE module_result_heads (
 module_id uuid PRIMARY KEY REFERENCES modules(id), result_id uuid NOT NULL UNIQUE REFERENCES extraction_results(id),
 manifest text NOT NULL
);
-- Older failed jobs can contain validated module results that were never published.
-- Preserve and expose these as partial results under the new recovery contract.
UPDATE extraction_results SET published=true WHERE NOT published;
INSERT INTO module_result_heads SELECT module_id,id,'legacy' FROM extraction_results WHERE published;
CREATE TABLE schedule_revisions (
 id bigserial PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects(id),
 results jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_schedule_revisions BEFORE UPDATE OR DELETE ON schedule_revisions FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TABLE processing_events (
 project_id uuid NOT NULL REFERENCES projects(id), sequence bigint NOT NULL, kind text NOT NULL,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(project_id,sequence)
);
CREATE TABLE retry_requests (
 document_id uuid NOT NULL REFERENCES documents(id), request_key text NOT NULL,
 generation integer NOT NULL, PRIMARY KEY(document_id,request_key)
);
CREATE TABLE provider_permits (
 provider text NOT NULL, slot integer NOT NULL, job_id uuid REFERENCES processing_jobs(id), owner_token uuid,
 PRIMARY KEY(provider,slot)
);
INSERT INTO provider_permits(provider,slot) SELECT p,n FROM unnest(ARRAY['docling','gpt']) p CROSS JOIN generate_series(1,8) n;
ALTER TABLE document_progress DROP CONSTRAINT document_progress_state_check;
ALTER TABLE document_progress ADD CHECK(state IN ('waiting','parsing','extracting','extracted','unknown','failed'));
ALTER TABLE document_chunks ADD COLUMN generation integer NOT NULL DEFAULT 1;
ALTER TABLE document_chunks DROP CONSTRAINT document_chunks_pkey;
ALTER TABLE document_chunks ADD PRIMARY KEY(document_id,chunk_index,generation);
CREATE TABLE document_replacements (
 old_document_id uuid PRIMARY KEY REFERENCES documents(id),
 new_document_id uuid NOT NULL UNIQUE REFERENCES documents(id),
 request_key text NOT NULL, CHECK(old_document_id<>new_document_id)
);
ALTER TABLE module_result_heads ADD COLUMN stale boolean NOT NULL DEFAULT false;
ALTER TABLE document_tasks ADD COLUMN uncertainties jsonb NOT NULL DEFAULT '[]';
ALTER TABLE parse_snapshots ADD COLUMN chunk_bytes integer NOT NULL DEFAULT 16000 CHECK(chunk_bytes BETWEEN 1024 AND 64000);
-- Retrying a module conflict can supersede suspect candidates without deleting them.
ALTER TABLE document_tasks ADD COLUMN minimum_generation integer NOT NULL DEFAULT 1;

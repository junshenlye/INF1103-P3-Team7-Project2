SET LOCAL search_path TO stackplan;

CREATE TABLE assessment_review_lineage (
    assessment_id uuid PRIMARY KEY REFERENCES assessments(id),
    previous_assessment_id uuid NOT NULL REFERENCES assessments(id),
    CHECK (assessment_id <> previous_assessment_id)
);
CREATE TRIGGER immutable_review_lineage
BEFORE UPDATE OR DELETE ON assessment_review_lineage
FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE OR REPLACE FUNCTION enforce_project_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.name <> OLD.name OR NEW.week_count <> OLD.week_count
       OR (OLD.job_id IS NOT NULL AND NEW.job_id IS DISTINCT FROM OLD.job_id)
       OR NOT (
           NEW.status = OLD.status
           OR (OLD.status = 'Created' AND NEW.status = 'Processing')
           OR (OLD.status = 'Processing' AND NEW.status IN ('Ready', 'Partial', 'Failed', 'Interrupted'))
           OR (OLD.status IN ('Ready', 'Partial', 'Failed', 'Interrupted') AND NEW.status = 'Processing')
           OR (OLD.status IN ('Ready', 'Partial', 'Failed') AND NEW.status IN ('Ready', 'Partial', 'Failed'))
       ) THEN
        RAISE EXCEPTION 'invalid_project_transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_job_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id OR NEW.submission_key <> OLD.submission_key
       OR NOT (
           (OLD.status = 'queued' AND NEW.status = 'running')
           OR (OLD.status = 'running' AND NEW.status IN ('running', 'queued', 'Ready', 'Partial', 'Failed', 'Interrupted'))
           OR (OLD.status IN ('Ready', 'Partial', 'Failed', 'Interrupted') AND NEW.status = 'queued')
           OR (OLD.status IN ('Ready', 'Partial', 'Failed') AND NEW.status IN ('Ready', 'Partial', 'Failed'))
       ) THEN
        RAISE EXCEPTION 'invalid_job_transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

-- Unfinished documents on terminal interrupted/failed jobs must be resumable.
UPDATE document_tasks AS task
SET state = 'failed', owner_token = NULL
FROM processing_jobs AS job
WHERE job.id = task.job_id
  AND job.status IN ('Failed', 'Interrupted')
  AND task.state IN ('queued', 'running');

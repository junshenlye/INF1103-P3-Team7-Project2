SET LOCAL search_path TO stackplan;
ALTER TABLE processing_issues ADD FOREIGN KEY(document_id,module_id) REFERENCES documents(id,module_id);
ALTER TABLE processing_issues ADD CHECK(document_id IS NULL OR module_id IS NOT NULL);
ALTER TABLE assessments ADD CHECK(length(facts->>'name') BETWEEN 1 AND 200 AND facts->>'kind' IN ('assessment','group') AND facts->>'weight_scope' IN ('module','group','unknown'));
ALTER TABLE assessments ADD CHECK(facts->>'key' IS NOT NULL);
CREATE TRIGGER immutable_modules BEFORE UPDATE OR DELETE ON modules FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE FUNCTION enforce_evidence_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM assessments a JOIN source_elements s ON s.id=NEW.source_element_id JOIN documents d ON d.id=s.document_id WHERE a.id=NEW.assessment_id AND a.module_id=d.module_id) THEN
        RAISE EXCEPTION 'evidence_owner_mismatch' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER evidence_owner BEFORE INSERT ON assessment_evidence FOR EACH ROW EXECUTE FUNCTION enforce_evidence_owner();

CREATE FUNCTION enforce_project_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id<>OLD.id OR NEW.name<>OLD.name OR NEW.week_count<>OLD.week_count OR
       NOT ((OLD.status='Created' AND NEW.status='Processing') OR (OLD.status='Processing' AND NEW.status IN ('Ready','Failed','Interrupted'))) OR
       (OLD.job_id IS NOT NULL AND NEW.job_id IS DISTINCT FROM OLD.job_id) THEN
        RAISE EXCEPTION 'invalid_project_transition' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER project_transition BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION enforce_project_transition();
CREATE FUNCTION enforce_job_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id<>OLD.id OR NEW.project_id<>OLD.project_id OR NEW.submission_key<>OLD.submission_key OR
       NOT ((OLD.status='queued' AND NEW.status='running') OR (OLD.status='running' AND NEW.status IN ('running','Ready','Failed','Interrupted'))) THEN
        RAISE EXCEPTION 'invalid_job_transition' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER job_transition BEFORE UPDATE ON processing_jobs FOR EACH ROW EXECUTE FUNCTION enforce_job_transition();
CREATE FUNCTION enforce_result_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.published OR NOT NEW.published OR NEW.id<>OLD.id OR NEW.job_id<>OLD.job_id OR NEW.module_id<>OLD.module_id OR NEW.uncertainties<>OLD.uncertainties OR NEW.metrics<>OLD.metrics THEN
        RAISE EXCEPTION 'immutable_result' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER result_publication BEFORE UPDATE ON extraction_results FOR EACH ROW EXECUTE FUNCTION enforce_result_publication();
CREATE TRIGGER immutable_result_delete BEFORE DELETE ON extraction_results FOR EACH ROW EXECUTE FUNCTION reject_mutation();

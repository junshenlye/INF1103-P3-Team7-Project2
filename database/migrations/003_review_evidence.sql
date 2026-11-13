SET LOCAL search_path TO stackplan;
CREATE TABLE review_evidence (
    review_id uuid NOT NULL REFERENCES review_revisions(id),
    field text NOT NULL CHECK(field IN ('name','kind','weight_percent','weight_scope','week','end_week','parent_key')),
    source_element_id uuid NOT NULL REFERENCES source_elements(id),
    PRIMARY KEY(review_id,field,source_element_id)
);
CREATE TRIGGER immutable_review_evidence BEFORE UPDATE OR DELETE ON review_evidence FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE FUNCTION enforce_review_evidence_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM review_revisions r JOIN source_elements s ON s.id=NEW.source_element_id JOIN documents d ON d.id=s.document_id WHERE r.id=NEW.review_id AND r.module_id=d.module_id) THEN
        RAISE EXCEPTION 'review_evidence_owner_mismatch' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER review_evidence_owner BEFORE INSERT ON review_evidence FOR EACH ROW EXECUTE FUNCTION enforce_review_evidence_owner();

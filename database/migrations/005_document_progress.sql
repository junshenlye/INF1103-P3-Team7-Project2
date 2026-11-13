-- Checkpoints are operational metadata, separate from immutable source evidence.
CREATE TABLE document_progress (
    document_id uuid PRIMARY KEY REFERENCES documents(id),
    state text NOT NULL CHECK (state IN ('waiting','parsing','extracting','extracted','unknown'))
);

-- Do not invent detailed progress for jobs processed before this feature.
INSERT INTO document_progress(document_id, state)
SELECT d.id, CASE
    WHEN j.status = 'Ready' OR r.id IS NOT NULL THEN 'extracted'
    WHEN j.status = 'queued' THEN 'waiting'
    ELSE 'unknown'
END
FROM documents d
JOIN modules m ON m.id = d.module_id
JOIN processing_jobs j ON j.id = m.job_id
LEFT JOIN extraction_results r ON r.module_id = m.id AND r.job_id = m.job_id;

SET LOCAL search_path TO stackplan;
CREATE FUNCTION valid_assessment_facts(f jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
SELECT COALESCE(
    jsonb_typeof(f)='object'
    AND f ?& ARRAY['key','name','kind','weight_percent','weight_scope','week','end_week','parent_key']
    AND jsonb_typeof(f->'key')='string' AND length(f->>'key') BETWEEN 1 AND 120
    AND jsonb_typeof(f->'name')='string' AND length(btrim(f->>'name')) BETWEEN 1 AND 200
    AND f->>'kind' IN ('assessment','group')
    AND f->>'weight_scope' IN ('module','group','unknown')
    AND (f->'weight_percent'='null'::jsonb OR (jsonb_typeof(f->'weight_percent')='number' AND (f->>'weight_percent')::numeric BETWEEN 0 AND 100))
    AND (f->'week'='null'::jsonb OR (jsonb_typeof(f->'week')='number' AND f->>'week' ~ '^[0-9]+$' AND (f->>'week')::numeric BETWEEN 1 AND 52))
    AND (f->'end_week'='null'::jsonb OR (jsonb_typeof(f->'end_week')='number' AND f->>'end_week' ~ '^[0-9]+$' AND (f->>'end_week')::numeric BETWEEN 1 AND 52 AND f->'week'<>'null'::jsonb AND (f->>'end_week')::numeric >= (f->>'week')::numeric))
    AND (f->>'kind'<>'group' OR (f->'week'='null'::jsonb AND f->'end_week'='null'::jsonb))
    AND (f->'parent_key'='null'::jsonb OR (jsonb_typeof(f->'parent_key')='string' AND length(f->>'parent_key') BETWEEN 1 AND 120 AND f->>'parent_key'<>f->>'key'))
    AND (f->>'weight_scope'<>'group' OR f->'parent_key'<>'null'::jsonb),false);
$$;
ALTER TABLE assessments ADD CHECK(valid_assessment_facts(facts));
ALTER TABLE assessments ADD CHECK((parent_assessment_id IS NULL) = (facts->'parent_key'='null'::jsonb));
ALTER TABLE review_revisions ADD CHECK(valid_assessment_facts(facts));

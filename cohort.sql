WITH qualifying AS (
    SELECT
        c.person_id,
        MIN(c.recorded_date) AS index_date
    FROM condition_occurrence c
    JOIN condition_detail d USING (condition_id)
    JOIN person p USING (person_id)
    WHERE c.local_concept = 'LOCAL_DIABETES'
      AND d.verification_status = 'confirmed'
      AND d.clinical_status = 'active'
      AND c.recorded_date >= DATE(p.birth_date, '+18 years')
    GROUP BY c.person_id
), eligible AS (
    SELECT
        m.*,
        q.index_date,
        ROW_NUMBER() OVER (
            PARTITION BY m.person_id
            ORDER BY m.effective_date DESC, m.measurement_id ASC
        ) AS rn
    FROM measurement m
    JOIN measurement_detail d USING (measurement_id)
    JOIN qualifying q USING (person_id)
    WHERE m.local_concept = 'LOCAL_HBA1C'
      AND d.status IN ('final', 'corrected')
      AND d.supported_unit = 1
      AND m.value IS NOT NULL
      AND m.effective_date BETWEEN q.index_date
          AND DATE(q.index_date, '+' || :window_days || ' days')
), result AS (
    SELECT
        p.person_id,
        q.index_date,
        e.measurement_id,
        e.effective_date,
        e.value,
        CASE
            WHEN q.person_id IS NULL THEN 'outside_cohort'
            WHEN e.measurement_id IS NULL THEN 'no_eligible_result'
            WHEN e.value >= :threshold THEN 'meets_threshold'
            ELSE 'below_threshold'
        END AS outcome
    FROM person p
    LEFT JOIN qualifying q USING (person_id)
    LEFT JOIN eligible e ON e.person_id = p.person_id AND e.rn = 1
)
SELECT *
FROM result
ORDER BY person_id;

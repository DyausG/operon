ALTER TABLE execution_claim
    ADD COLUMN adapter TEXT NOT NULL DEFAULT 'legacy-unresolved';

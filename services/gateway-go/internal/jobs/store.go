package jobs

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Store wraps the Postgres pool for run persistence. Phase 1 only needs
// insert-and-poll; lineage-specific writes (pipeline_steps, transformations)
// are Phase 2 work and deliberately not touched here.
type Store struct {
	pool *pgxpool.Pool
}

func NewStore(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// CreateRun inserts a new run row with status=queued and returns the
// generated run_id. dataset_id must already exist in `datasets` — the
// foreign key constraint enforces that; a violation surfaces as an error
// here, which the handler should translate to a 400.
func (s *Store) CreateRun(ctx context.Context, sub JobSubmission) (*Run, error) {
	var run Run
	query := `
		INSERT INTO runs (dataset_id, status)
		VALUES ($1, $2)
		RETURNING id, dataset_id, status, created_at
	`
	err := s.pool.QueryRow(ctx, query, sub.DatasetID, string(StatusQueued)).
		Scan(&run.ID, &run.DatasetID, &run.Status, &run.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("insert run: %w", err)
	}
	run.JobType = sub.JobType
	return &run, nil
}

// GetRun fetches a run by ID for GET /v1/jobs/:id.
func (s *Store) GetRun(ctx context.Context, runID string) (*Run, error) {
	var run Run
	query := `
		SELECT id, dataset_id, status, created_at, started_at, finished_at
		FROM runs WHERE id = $1
	`
	err := s.pool.QueryRow(ctx, query, runID).
		Scan(&run.ID, &run.DatasetID, &run.Status, &run.CreatedAt, &run.StartedAt, &run.FinishedAt)
	if err != nil {
		return nil, fmt.Errorf("get run: %w", err)
	}
	return &run, nil
}

// UpdateStatus transitions a run's status and stamps started_at/finished_at
// as appropriate. Used by the noop job executor to drive queued -> running
// -> done without any real Celery task existing yet (that's Phase 8).
func (s *Store) UpdateStatus(ctx context.Context, runID string, status RunStatus) error {
	now := time.Now().UTC()
	var query string
	var err error
	switch status {
	case StatusRunning:
		query = `UPDATE runs SET status = $1, started_at = $2 WHERE id = $3`
		_, err = s.pool.Exec(ctx, query, string(status), now, runID)
	case StatusDone, StatusFailed:
		query = `UPDATE runs SET status = $1, finished_at = $2 WHERE id = $3`
		_, err = s.pool.Exec(ctx, query, string(status), now, runID)
	default:
		query = `UPDATE runs SET status = $1 WHERE id = $2`
		_, err = s.pool.Exec(ctx, query, string(status), runID)
	}
	if err != nil {
		return fmt.Errorf("update run status: %w", err)
	}
	return nil
}

// InsertAuditLog records a submit/status-change event per CLAUDE.md §6
// audit_log table. Minimal use in Phase 1 — full audit coverage is not a
// Phase 1 acceptance criterion, but every state-changing operation should
// leave a trace from the start.
func (s *Store) InsertAuditLog(ctx context.Context, runID, actor, action string) error {
	query := `INSERT INTO audit_log (run_id, actor, action) VALUES ($1, $2, $3)`
	_, err := s.pool.Exec(ctx, query, runID, actor, action)
	if err != nil {
		return fmt.Errorf("insert audit log: %w", err)
	}
	return nil
}
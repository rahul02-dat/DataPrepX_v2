package jobs

import "time"

// JobType mirrors the enum in shared/schemas/job.schema.json.
// Only "noop" is implemented in Phase 1. "full_pipeline" is reserved for later
// phases and must be rejected until the corresponding phase lands.
type JobType string

const (
	JobTypeNoop         JobType = "noop"
	JobTypeFullPipeline JobType = "full_pipeline"
)

// RunStatus mirrors shared/schemas/job_status.schema.json, matching the
// state transitions documented in CLAUDE.md §5.7.
type RunStatus string

const (
	StatusQueued    RunStatus = "queued"
	StatusRunning   RunStatus = "running"
	StatusGateCheck RunStatus = "gate-check"
	StatusOptimize  RunStatus = "optimizing"
	StatusDone      RunStatus = "done"
	StatusFailed    RunStatus = "failed"
)

// JobSubmission is the inbound request body for POST /v1/jobs.
// Field names and constraints must stay in lockstep with
// shared/schemas/job.schema.json — that file is the source of truth.
type JobSubmission struct {
	JobType   JobType                `json:"job_type"`
	DatasetID string                 `json:"dataset_id"`
	Config    map[string]interface{} `json:"config,omitempty"`
}

// Run represents a row in the `runs` table (CLAUDE.md §6), trimmed to the
// fields gateway-go needs to expose over the API.
type Run struct {
	ID         string     `json:"run_id"`
	DatasetID  string     `json:"dataset_id"`
	JobType    JobType    `json:"job_type"`
	Status     RunStatus  `json:"status"`
	GitSHA     string     `json:"git_sha,omitempty"`
	ConfigHash string     `json:"config_hash,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
	StartedAt  *time.Time `json:"started_at,omitempty"`
	FinishedAt *time.Time `json:"finished_at,omitempty"`
}

// StatusMessage is what gets pushed over the WebSocket hub, matching
// shared/schemas/job_status.schema.json exactly.
type StatusMessage struct {
	RunID     string    `json:"run_id"`
	Status    RunStatus `json:"status"`
	Message   string    `json:"message,omitempty"`
	Timestamp time.Time `json:"timestamp"`
}
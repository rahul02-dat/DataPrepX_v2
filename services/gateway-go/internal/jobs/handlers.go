package jobs

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

type Handler struct {
	store    *Store
	datasets *DatasetStore
	hub      *Hub
	upgrader websocket.Upgrader
}

func NewHandler(store *Store, datasets *DatasetStore, hub *Hub) *Handler {
	return &Handler{
		store:    store,
		datasets: datasets,
		hub:      hub,
		upgrader: websocket.Upgrader{
			// Dev-only: allow any origin. Tighten before Phase 11 hardening.
			CheckOrigin: func(r *http.Request) bool { return true },
		},
	}
}

func (h *Handler) RegisterRoutes(r *gin.Engine) {
	r.POST("/v1/datasets", h.UploadDataset)
	r.POST("/v1/jobs", h.SubmitJob)
	r.GET("/v1/jobs/:id", h.GetJob)
	r.GET("/v1/jobs/:id/stream", h.StreamJob)
}

// UploadDataset accepts a multipart file, hashes and stores it, and
// returns dataset_id + content_hash for use in a subsequent job submission.
func (h *Handler) UploadDataset(c *gin.Context) {
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing 'file' form field: " + err.Error()})
		return
	}
	defer file.Close()

	datasetID, contentHash, err := h.datasets.Ingest(c.Request.Context(), file, header.Filename)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"dataset_id":   datasetID,
		"content_hash": contentHash,
		"filename":     header.Filename,
	})
}

// SubmitJob validates the request against job.schema.json, then inserts a
// run row and drives the noop execution path synchronously (queued ->
// running -> done). Real async execution via Celery is Phase 8 — this is
// intentionally a stub executor, not the real thing.
func (h *Handler) SubmitJob(c *gin.Context) {
	rawBody, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "failed to read body"})
		return
	}

	validationErrs, err := ValidateSubmission(rawBody)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if len(validationErrs) > 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "schema validation failed", "details": validationErrs})
		return
	}

	var sub JobSubmission
	if err := json.Unmarshal(rawBody, &sub); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	if sub.JobType == JobTypeFullPipeline {
		c.JSON(http.StatusNotImplemented, gin.H{
			"error": "job_type 'full_pipeline' is not implemented until Phase 5-8 land; Phase 1 only supports 'noop'",
		})
		return
	}

	run, err := h.store.CreateRun(c.Request.Context(), sub)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "failed to create run (check dataset_id exists): " + err.Error()})
		return
	}
	_ = h.store.InsertAuditLog(c.Request.Context(), run.ID, "system", "job_submitted")

	c.JSON(http.StatusAccepted, gin.H{"run_id": run.ID, "status": run.Status})

	// Drive the noop lifecycle in the background so the HTTP response
	// returns immediately, per planner Phase 8's "gateway never blocks"
	// principle even though Phase 8 itself isn't built yet.
	go h.runNoop(run.ID)
}

func (h *Handler) runNoop(runID string) {
	ctx := context.Background()
	h.transition(ctx, runID, StatusRunning, "noop job running")
	time.Sleep(200 * time.Millisecond) // simulate minimal work
	h.transition(ctx, runID, StatusDone, "noop job completed, no pipeline logic executed")
}

func (h *Handler) transition(ctx context.Context, runID string, status RunStatus, message string) {
	if err := h.store.UpdateStatus(ctx, runID, status); err != nil {
		// Best-effort: log and still publish so WS subscribers aren't stuck.
		// Proper error surfacing to the run record is Phase 2/8 territory.
		println("jobs: failed to update run status:", err.Error())
	}
	h.hub.Publish(runID, status, message)
}

// GetJob returns the current run row for polling.
func (h *Handler) GetJob(c *gin.Context) {
	runID := c.Param("id")
	run, err := h.store.GetRun(c.Request.Context(), runID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "run not found: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, run)
}

// StreamJob upgrades to a WebSocket and subscribes the connection to
// status updates for the given run_id, satisfying the Phase 1 acceptance
// criterion: "status streamed to a WebSocket client end-to-end."
func (h *Handler) StreamJob(c *gin.Context) {
	runID := c.Param("id")
	conn, err := h.upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	h.hub.Subscribe(runID, conn)
	defer func() {
		h.hub.Unsubscribe(runID, conn)
		conn.Close()
	}()

	// Send current state immediately on connect so a client that subscribes
	// after the job already progressed isn't left waiting indefinitely.
	if run, err := h.store.GetRun(c.Request.Context(), runID); err == nil {
		h.hub.Publish(runID, run.Status, "current state on subscribe")
	}

	// Block reading (discarding) so the handler stays alive until the
	// client disconnects; Gin needs the goroutine to persist for writes.
	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			return
		}
	}
}
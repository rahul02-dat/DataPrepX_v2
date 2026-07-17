// Package jobs will hold job submission, polling, and WebSocket status streaming.
// Phase 0 only provides stub handlers to prove the route exists and responds; the real
// job/run data model lands in Phase 1 (see docs/01_IMPLEMENTATION_PLANNER.md §Phase 1).
package jobs

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// SubmitStub is a placeholder for job submission. It does not persist anything and does not
// touch Postgres or Redis yet — that is explicitly out of scope for Phase 0.
func SubmitStub(c *gin.Context) {
	c.JSON(http.StatusAccepted, gin.H{
		"status":  "stub",
		"message": "job submission not implemented until Phase 1",
	})
}

// GetStatusStub is a placeholder for job status polling.
func GetStatusStub(c *gin.Context) {
	id := c.Param("id")
	c.JSON(http.StatusOK, gin.H{
		"status":  "stub",
		"job_id":  id,
		"message": "job status polling not implemented until Phase 1",
	})
}

package jobs

import (
	"encoding/json"
	"log"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// Hub fans out StatusMessage updates to WebSocket clients subscribed to a
// given run_id. One hub instance is shared across the gateway process.
type Hub struct {
	mu   sync.RWMutex
	subs map[string]map[*websocket.Conn]bool // run_id -> set of connections
}

func NewHub() *Hub {
	return &Hub{subs: make(map[string]map[*websocket.Conn]bool)}
}

func (h *Hub) Subscribe(runID string, conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.subs[runID] == nil {
		h.subs[runID] = make(map[*websocket.Conn]bool)
	}
	h.subs[runID][conn] = true
}

func (h *Hub) Unsubscribe(runID string, conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if conns, ok := h.subs[runID]; ok {
		delete(conns, conn)
		if len(conns) == 0 {
			delete(h.subs, runID)
		}
	}
}

// Publish pushes a status transition to every client subscribed to runID.
// A dead connection is dropped silently rather than blocking the whole
// broadcast — Phase 1's noop job has at most one subscriber, but this
// should not become a bottleneck once Phase 8 wires real Celery tasks in.
func (h *Hub) Publish(runID string, status RunStatus, message string) {
	h.mu.RLock()
	conns := h.subs[runID]
	h.mu.RUnlock()

	msg := StatusMessage{
		RunID:     runID,
		Status:    status,
		Message:   message,
		Timestamp: time.Now().UTC(),
	}
	payload, err := json.Marshal(msg)
	if err != nil {
		log.Printf("hub: failed to marshal status message: %v", err)
		return
	}
	for conn := range conns {
		if err := conn.WriteMessage(websocket.TextMessage, payload); err != nil {
			log.Printf("hub: write failed for run %s, dropping subscriber: %v", runID, err)
			h.Unsubscribe(runID, conn)
			conn.Close()
		}
	}
}
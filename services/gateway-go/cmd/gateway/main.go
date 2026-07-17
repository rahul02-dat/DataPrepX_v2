package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/gin-gonic/gin"

	"github.com/dataprepx/gateway-go/internal/jobs"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	router := gin.Default()

	router.GET("/healthz", healthzHandler)

	v1 := router.Group("/v1")
	{
		v1.POST("/jobs", jobs.SubmitStub)
		v1.GET("/jobs/:id", jobs.GetStatusStub)
	}

	addr := fmt.Sprintf(":%s", port)
	log.Printf("gateway-go listening on %s", addr)
	if err := router.Run(addr); err != nil {
		log.Fatalf("server failed: %v", err)
	}
}

func healthzHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "gateway-go"})
}
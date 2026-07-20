package main

import (
	"fmt"
	"log"
	"net/http"
	"context"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	

	"github.com/dataprepx/gateway-go/internal/jobs"
)

func main() {
	ctx := context.Background()
	dbURL := os.Getenv("DATABASE_URL")
	pool, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		log.Fatalf("Failed to connect to postgres: %v", err)
	}
	defer pool.Close()

	store := jobs.NewStore(pool)
	datasetStore := jobs.NewDatasetStore(store, "/data/uploads")
	hub := jobs.NewHub()
	handler:= jobs.NewHandler(store, datasetStore, hub)


	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	router := gin.Default()

	router.GET("/healthz", healthzHandler)

	handler.RegisterRoutes(router)

	addr := fmt.Sprintf(":%s", port)
	log.Printf("gateway-go listening on %s", addr)
	if err := router.Run(addr); err != nil {
		log.Fatalf("server failed: %v", err)
	}
}

func healthzHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "gateway-go"})
}
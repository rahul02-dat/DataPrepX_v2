package jobs

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// DatasetStore handles the narrow slice of dataset ingestion Phase 1 needs:
// accept a file, hash it, store it, record it. No parsing, no schema
// inference, no validation gates — that is Phase 2/3 work and must not be
// pulled forward here.
type DatasetStore struct {
	store   *Store
	baseDir string // local filesystem storage root for Phase 1; object storage is a later concern
}

func NewDatasetStore(store *Store, baseDir string) *DatasetStore {
	return &DatasetStore{store: store, baseDir: baseDir}
}

// Ingest reads r fully, computes its content hash, writes it to baseDir
// under that hash (content-addressed, consistent with the lineage
// philosophy in CLAUDE.md §5.3 even though Phase 2 lineage itself isn't
// built yet), and inserts a `datasets` row.
func (d *DatasetStore) Ingest(ctx context.Context, r io.Reader, originalFilename string) (datasetID, contentHash string, err error) {
	if err := os.MkdirAll(d.baseDir, 0o755); err != nil {
		return "", "", fmt.Errorf("create storage dir: %w", err)
	}

	tmpPath := filepath.Join(d.baseDir, "tmp-upload")
	tmpFile, err := os.Create(tmpPath)
	if err != nil {
		return "", "", fmt.Errorf("create temp file: %w", err)
	}
	defer os.Remove(tmpPath)

	hasher := sha256.New()
	size, err := io.Copy(io.MultiWriter(tmpFile, hasher), r)
	tmpFile.Close()
	if err != nil {
		return "", "", fmt.Errorf("write upload: %w", err)
	}

	hash := hex.EncodeToString(hasher.Sum(nil))
	finalPath := filepath.Join(d.baseDir, hash)
	if err := os.Rename(tmpPath, finalPath); err != nil {
		return "", "", fmt.Errorf("finalize stored file: %w", err)
	}

	var id string
	query := `
		INSERT INTO datasets (content_hash, storage_uri, size_bytes, original_filename)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (content_hash) DO UPDATE SET original_filename = EXCLUDED.original_filename
		RETURNING id
	`
	err = d.store.pool.QueryRow(ctx, query, hash, finalPath, size, originalFilename).Scan(&id)
	if err != nil {
		return "", "", fmt.Errorf("insert dataset row: %w", err)
	}

	return id, hash, nil
}
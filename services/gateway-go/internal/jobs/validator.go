package jobs

import (
	"embed"
	"encoding/json"
	"fmt"

	"github.com/xeipuuv/gojsonschema"
)

// The canonical schema lives at shared/schemas/job.schema.json in the repo
// root. go:embed cannot reach outside the module, so this is a synced copy —
// run `make sync-schemas` after editing the canonical file. A CI step
// (added to Makefile as `check-schema-sync`) diffs this copy against the
// canonical file and fails the build on drift.
//
//go:embed schemas/job.schema.json
var jobSchemaFS embed.FS

var jobSchema *gojsonschema.Schema

func init() {
	data, err := jobSchemaFS.ReadFile("schemas/job.schema.json")
	if err != nil {
		panic(fmt.Sprintf("jobs: failed to load embedded job schema: %v", err))
	}
	loader := gojsonschema.NewBytesLoader(data)
	s, err := gojsonschema.NewSchema(loader)
	if err != nil {
		panic(fmt.Sprintf("jobs: invalid embedded job schema: %v", err))
	}
	jobSchema = s
}

// ValidateSubmission checks a raw JSON body against job.schema.json before
// it is ever unmarshalled into a JobSubmission struct. Returns a slice of
// human-readable validation errors, empty if valid.
func ValidateSubmission(rawBody []byte) ([]string, error) {
	var parsed interface{}
	if err := json.Unmarshal(rawBody, &parsed); err != nil {
		return nil, fmt.Errorf("invalid JSON body: %w", err)
	}
	result, err := jobSchema.Validate(gojsonschema.NewGoLoader(parsed))
	if err != nil {
		return nil, fmt.Errorf("schema validation error: %w", err)
	}
	if result.Valid() {
		return nil, nil
	}
	errs := make([]string, 0, len(result.Errors()))
	for _, e := range result.Errors() {
		errs = append(errs, e.String())
	}
	return errs, nil
}
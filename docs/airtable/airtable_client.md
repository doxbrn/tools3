# Airtable Client

The `AirtableClient` is a Python class that provides a complete interface for interacting with the Content Flow Airtable base. It handles all operations related to tables, records, and includes specialized methods for managing job logs.

## Installation

No additional installation is required beyond the standard project setup. The client is part of the services module.

## Configuration

The client requires an Airtable API key to function. You can provide this in one of two ways:

1. Set the `AIRTABLE_API_KEY` environment variable
2. Pass the API key directly to the client constructor

```python
# Using environment variable
import os
os.environ["AIRTABLE_API_KEY"] = "your_api_key_here"
from services.airtable_client import AirtableClient
client = AirtableClient()

# OR passing directly
from services.airtable_client import AirtableClient
client = AirtableClient(api_key="your_api_key_here")
```

By default, the client connects to the Content Flow base. If you need to connect to a different base, you can specify the base ID:

```python
client = AirtableClient(base_id="appXXXXXXXXXXXXXX")
```

## General Usage

### Table Operations

```python
# List all tables in the base
tables = client.list_tables()

# Create a new table
new_table = client.create_table(
    table_name="My_Table",
    description="My table description",
    fields=[
        {
            "name": "Name",
            "type": "singleLineText",
            "description": "The name field"
        }
        # Add more fields as needed
    ]
)
```

### Record Operations

```python
# List records from a table
records = client.list_records("channels", max_records=10)

# Get a specific record
record = client.get_record("channels", "recXXXXXXXXXXXXXX")

# Create a new record
new_record = client.create_record("channels", {
    "Nome_Canal": "My New Channel",
    "Status": "Ativo"
})

# Update a record
updated_record = client.update_record("channels", "recXXXXXXXXXXXXXX", {
    "Status": "Arquivado"
})

# Delete a record
client.delete_record("channels", "recXXXXXXXXXXXXXX")

# Search records
search_results = client.search_records("channels", "Nome_Canal", "My Channel")
```

## Jobs Logs Management

The client provides specialized methods for working with the Jobs_Logs table, which tracks processing jobs throughout the system.

### Creating a Job Log

```python
import uuid

# Generate a unique job ID
job_id = f"job-{uuid.uuid4()}"

# Create a job log
job_log = client.create_job_log(
    job_id=job_id,
    job_type="Image_Generation",
    service_name="image_generation_service",
    related_content_id="C-123",  # Optional
    related_scene_id="C-123-S1",  # Optional
    metadata={  # Optional
        "parameters": {
            "model": "stable-diffusion",
            "prompt": "a landscape with mountains",
            "steps": 30
        }
    }
)

# The job log ID will be needed for updates
log_id = job_log["id"]
```

### Updating Job Status

```python
# Update job to running status
client.update_job_status(
    log_record_id=log_id,
    status="Running",
    log_message="Job started processing"
)

# Add log messages
client.add_log_message(
    log_record_id=log_id,
    message="Processing step 1/3 - 33% complete"
)

# Mark as completed with results
client.update_job_status(
    log_record_id=log_id,
    status="Completed",
    log_message="Job completed successfully",
    metadata_updates={
        "results": {
            "image_url": "https://example.com/images/generated.png",
            "processing_time": 3.5
        }
    }
)

# Handle failure
client.update_job_status(
    log_record_id=log_id,
    status="Failed",
    log_message="Job failed due to API error",
    error_details="API returned status code 500: Server Error"
)
```

### Retrieving Job Logs

```python
# Get logs for a specific job
job_logs = client.get_job_logs(job_id="job-12345")

# Filter by status
running_jobs = client.get_job_logs(status="Running")

# Filter by job type
image_jobs = client.get_job_logs(job_type="Image_Generation")

# Filter by service
service_jobs = client.get_job_logs(service_name="image_generation_service")

# Filter by related content
content_jobs = client.get_job_logs(related_content_id="C-123")
```

## Table Reference

The client provides access to the following tables in the Content Flow base:

| Table Name | Code Key | Description |
|------------|----------|-------------|
| Canais | "channels" | Channels configuration |
| Conteudos | "contents" | Content items |
| Cenas | "scenes" | Individual scenes |
| 🪄 AI Actions | "actions" | AI action definitions |
| Banco_imagens | "image_bank" | Image bank |
| Assets | "assets" | Media assets |
| Models | "models" | AI model definitions |
| ⚙️ Configuracoes | "config" | System configuration |
| Contas Canais | "channels_accounts" | Channel accounts |
| Templates Video | "video_templates" | Video templates |
| ℹ️ Cost | "costs" | Cost tracking |
| Jobs_Logs | "logs" | Job logging |

## Error Handling

The client handles API errors and returns error information in the response. Always check for an "error" key in the response before proceeding:

```python
response = client.create_record("channels", {"Nome_Canal": "Test"})
if "error" in response:
    print(f"Error occurred: {response['error']}")
else:
    print("Record created successfully!")
``` 
# Content Flow Airtable Base

The Content Flow Airtable Base is the central database that powers the content generation and management workflow. This document provides an overview of the base structure and how to interact with it.

## Content Flow Process

1. **Content Generation:** The AI generates content based on channel specifications (prompts, themes) stored in the `Canais` table. The generated content is stored in the `Conteudos` table.

2. **Scene Division:** Content is divided into scenes with the results stored in the `Cenas` table. Each scene maintains a reference to its parent content item and has an order field for sequence.

3. **Asset Generation:** Automated processes generate image and audio assets for each scene, storing their S3 URLs (e.g., `url_s3_image`, `url_s3_audio`) back into the corresponding `Cenas` records.

4. **Video Creation:** Workflows read data from `Conteudos` and `Cenas` (specifically the asset URLs and order) to trigger the video creation API endpoint.

5. **Webhook Notification:** The video creation service uses the `webhook_url` from the `Conteudos` record (or a default) to send a notification upon completion of the video rendering and S3 upload.

## Base Structure

The Content Flow base consists of several interconnected tables that manage different aspects of the content workflow:

| Table Name | Description |
|------------|-------------|
| Canais | Channels configuration, themes, and settings |
| Conteudos | Content items, including themes and generated scripts |
| Cenas | Individual scenes that make up content items |
| 🪄 AI Actions | AI action definitions and webhooks |
| Banco_imagens | Image bank for storing and retrieving images |
| Assets | Media assets including audio, video, and images |
| Models | AI model definitions and configurations |
| ⚙️ Configuracoes | System configuration settings |
| Contas Canais | Channel accounts for publishing |
| Templates Video | Video templates for automated video generation |
| ℹ️ Cost | Cost tracking for generation processes |
| Jobs_Logs | Logging and tracking of all processing jobs |

## Key Relationships

- Canais → Conteudos: One-to-many relationship, each channel can have multiple content items
- Conteudos → Cenas: One-to-many relationship, each content item is divided into scenes
- Canais → AI Actions: Many-to-many relationship for image, audio, and video generation
- Conteudos → Assets: Many-to-many relationship linking content to generated assets

## Available Documentation

Detailed documentation is available for specific aspects of the Content Flow base:

- [Airtable Client](./airtable_client.md) - How to interact with the base programmatically
- [Jobs_Logs Table](./jobs_logs_table.md) - How to track and monitor processing jobs

## Accessing the Base

The Content Flow base can be accessed in several ways:

1. **Airtable Web Interface**: Direct access through the Airtable UI
2. **Airtable API**: Direct API access using the Airtable API and base ID
3. **AirtableClient**: Recommended approach using our custom client library

### Using the AirtableClient

The `AirtableClient` is the recommended way to interact with the Content Flow base. See the [Airtable Client documentation](./airtable_client.md) for detailed usage instructions.

```python
from services.airtable_client import AirtableClient

# Initialize the client
client = AirtableClient()

# Example: List all channels
channels = client.list_records("channels")
for channel in channels:
    print(channel.get("fields", {}).get("Nome_Canal"))
```

## Job Logging and Monitoring

All processing jobs within the system should be logged to the Jobs_Logs table for tracking and monitoring. See the [Jobs_Logs Table documentation](./jobs_logs_table.md) for details on how to implement proper job logging.

```python
# Example: Creating a job log entry
job_log = client.create_job_log(
    job_id="job-12345",
    job_type="Content_Generation",
    service_name="content_generator"
)
```

## Base ID and API Access

The Content Flow base ID is `appVgvW0XEsJLXZ0P`. This ID is used when connecting to the base through the API or the AirtableClient.

For API access, you'll need:
- Base ID: `appVgvW0XEsJLXZ0P`
- API Key: Obtain from your system administrator or environment configuration

## Recommended Workflows

1. **Content Creation**:
   - Create/select a Channel
   - Generate content themes
   - Select and approve themes
   - Generate full content
   - Split content into scenes
   - Generate assets for each scene
   - Compose final media

2. **Job Monitoring**:
   - Create job log entries for each processing step
   - Update status as jobs progress
   - Track errors and retry failed jobs
   - Analyze performance metrics

## Best Practices

1. Always use the AirtableClient for consistent interactions
2. Log all processing jobs to the Jobs_Logs table
3. Include proper error handling and retries for failed operations
4. Use the provided relationship fields to maintain data integrity
5. Follow the established naming conventions for new records 
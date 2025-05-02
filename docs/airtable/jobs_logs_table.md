# Jobs_Logs Table

The `Jobs_Logs` table in the Content Flow Airtable base is designed to track and monitor all processing jobs throughout the system. This centralized logging helps with debugging, performance monitoring, and maintaining an audit trail of operations.

## Table Structure

The table contains the following fields:

| Field Name | Type | Description |
|------------|------|-------------|
| Job_ID | Single line text | Unique identifier for the job |
| Status | Single select | Current job status (Pending, Running, Completed, Failed, Canceled) |
| Job_Type | Single select | Type of job (Content_Generation, Image_Generation, Audio_Generation, etc.) |
| Related_Content_ID | Single line text | ID of related content in the Conteudos table |
| Related_Scene_ID | Single line text | ID of related scene in the Cenas table |
| Started_At | Date | When the job was started |
| Completed_At | Date | When the job was completed |
| Duration_Seconds | Number | Total processing time in seconds |
| Log_Messages | Long text | Accumulated log messages with timestamps |
| Service_Name | Single line text | Name of the service that processed the job |
| Error_Details | Long text | Detailed error information if job failed |
| Metadata | Long text | Additional job metadata in JSON format |

## Status Values

The `Status` field can have the following values:

- **Pending**: Job has been created but processing hasn't started
- **Running**: Job is currently being processed
- **Completed**: Job finished successfully
- **Failed**: Job encountered an error and couldn't complete
- **Canceled**: Job was manually canceled or timed out

## Job Types

The `Job_Type` field can have these values:

- **Content_Generation**: Generation of content/scripts
- **Image_Generation**: AI image generation
- **Audio_Generation**: Text-to-speech or audio processing
- **Video_Generation**: Creating videos from assets
- **Video_Processing**: Processing existing videos
- **Content_Translation**: Translating content to different languages
- **File_Upload**: Uploading files to storage
- **File_Download**: Downloading files from external sources

## Purpose and Usage

The Jobs_Logs table serves several important purposes:

1. **Tracking job progress**: Monitor jobs as they move through different processing stages
2. **Performance monitoring**: Track how long jobs take to complete
3. **Error analysis**: Capture detailed error information for troubleshooting
4. **Audit trails**: Maintain a record of all system operations
5. **Service health monitoring**: Identify patterns of failures or slowdowns

## Using the Jobs_Logs Table

### Through the AirtableClient

The recommended way to interact with the Jobs_Logs table is through the `AirtableClient` class, which provides specialized methods for job log management. See the [Airtable Client documentation](./airtable_client.md) for details.

### Example Usage Flow

A typical usage flow looks like:

1. **Job creation**: When a job is initiated, create a new log entry with status "Pending"
2. **Processing start**: Update the job status to "Running" when processing begins
3. **Progress updates**: Add log messages during processing to track progress
4. **Completion**: Update status to "Completed" or "Failed" with appropriate metadata
5. **Analysis**: Query job logs to analyze performance, find errors, etc.

### Direct API Access

While using the AirtableClient is recommended, you can also access the Jobs_Logs table directly through the Airtable API if needed.

## Implementation Recommendations

When implementing job logging:

1. **Use unique job IDs**: Generate UUID-based job IDs to ensure uniqueness
2. **Include timestamps**: Log messages should include timestamps for proper sequencing
3. **Structured metadata**: Store structured data in the Metadata field as formatted JSON
4. **Relate to content**: Link jobs to their associated content and scene records when possible
5. **Handle errors**: Capture detailed error information to aid troubleshooting

## Example Log Message Format

The Log_Messages field typically follows this format:

```
[2023-08-15T10:00:00] Job created and pending execution
[2023-08-15T10:01:15] Processing started - Loading input data
[2023-08-15T10:02:30] Processing step 1/3 complete
[2023-08-15T10:03:45] Processing step 2/3 complete
[2023-08-15T10:05:00] Processing step 3/3 complete
[2023-08-15T10:05:15] Job completed successfully
```

## Example Metadata Format

The Metadata field typically contains JSON data like:

```json
{
  "parameters": {
    "model": "stable-diffusion",
    "prompt": "a landscape with mountains",
    "negative_prompt": "ugly, blurry",
    "steps": 30,
    "width": 1024,
    "height": 1024
  },
  "results": {
    "image_url": "https://example.com/images/generated_12345.png",
    "generation_seed": 1234567890,
    "processing_time": 3.5
  },
  "system_info": {
    "worker_id": "worker-03",
    "cpu_usage": 85,
    "memory_usage": 4.2
  }
}
``` 
# Add Overlay & Background Music

Applies a static overlay image and mixes background music into an existing video file asynchronously.

## Endpoint

`POST /v1/video/add-overlay-music`

## Authentication

Requires a valid API key passed in the `x-api-key` header.

## Request Body

The request body must be a JSON object with the following properties:

*   `input_video_url` (string, required): URL of the source video file (must be publicly accessible).
*   `overlay_image_url` (string, required): URL of the overlay image file (e.g., PNG with transparency, must be publicly accessible).
*   `background_music_url` (string, required): URL of the background music audio file (must be publicly accessible).
*   `webhook_url` (string, required): The URL where the final result (success or failure) will be POSTed.
*   `content_id` (string, required): A unique identifier for this job, used for tracking and temporary file naming.
*   `overlay_position` (string, optional, default: `"bottom-right"`): Specifies where to place the overlay image. Valid values:
    *   `"top-left"`
    *   `"top-right"`
    *   `"bottom-left"`
    *   `"bottom-right"`
    *   `"center"`
*   `music_volume` (number, optional, default: `0.5`): Adjusts the volume of the background music relative to its original volume. `1.0` is original volume, `0.5` is half volume, `0.0` is silent. Values between 0.0 and 2.0 are accepted.
*   `output_filename` (string, optional): If provided, this filename (without extension, `.mp4` will be added) will be used for the final output video uploaded to S3. If omitted, a default name based on the input video and operation will be generated (e.g., `input_overlay_music.mp4`).

### Example Request Payload

```json
{
  "input_video_url": "https://example.com/path/to/my_video.mp4",
  "overlay_image_url": "https://example.com/path/to/logo.png",
  "background_music_url": "https://example.com/path/to/track.mp3",
  "webhook_url": "https://myapp.com/webhook/video-processed",
  "content_id": "job-123-abc",
  "overlay_position": "bottom-right",
  "music_volume": 0.3,
  "output_filename": "final_branded_video_v1" 
}
```

## Response

### Immediate Response (Synchronous)

If the request payload is valid and authenticated, the API immediately responds with `202 Accepted`:

```json
{
  "status": "processing",
  "message": "Overlay/music addition process started for job-123-abc. Result will be sent to https://myapp.com/webhook/video-processed"
}
```

### Final Response (Asynchronous Webhook)

Once processing is complete (either success or failure), the service sends a POST request to the `webhook_url` provided in the initial request.

#### Success Payload

```json
{
  "content_id": "job-123-abc",
  "status": "completed",
  "s3_url": "https://your-s3-endpoint.com/your-bucket/final_branded_video_v1.mp4" 
}

```

#### Failure Payload

```json
{
  "content_id": "job-123-abc",
  "status": "failed",
  "error": "Error processing overlay/music: Failed to download overlay image: 404 Client Error: Not Found for url: https://example.com/path/to/bad_logo.png" 
}

``` 
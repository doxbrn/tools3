# Add Overlay & Background Music

Applies a static or looping video/image overlay and mixes looping background music into an existing video file asynchronously.

## Endpoint

`POST /v1/video/add-overlay-music`

## Authentication

Requires a valid API key passed in the `x-api-key` header.

## Request Body

The request body must be a JSON object with the following properties:

*   `input_video_url` (string, required): URL of the source video file.
*   `overlay_image_url` (string, required): URL of the overlay image OR video file.
*   `background_music_url` (string, required): URL of the background music audio file.
*   `webhook_url` (string, required): The URL where the final result will be POSTed.
*   `content_id` (string, required): A unique identifier for this job.
*   `overlay_position` (string, optional, default: `"bottom-right"`): Specifies overlay placement. Valid values:
    *   `"full"`: Scales the overlay to match the input video dimensions.
    *   `"top-left"`
    *   `"top-right"`
    *   `"bottom-left"`
    *   `"bottom-right"`
    *   `"center"`
*   `music_volume` (number, optional, default: `0.5`): Adjusts background music volume (0.0-2.0).
*   `output_filename` (string, optional): Desired output filename (without extension).
*   `overlay_opacity` (number, optional, default: `1.0`): Opacity of the overlay (0.0 = fully transparent, 1.0 = fully opaque).
*   `overlay_blend_mode` (string, optional): Blending mode for the overlay. Supported modes include:
    *   `"normal"` (default if omitted)
    *   `"screen"`
    *   `"multiply"`
    *   `"overlay"`
    *   `"difference"`
    *   *(Add more if implemented in the service)*

### Example Request Payload

```json
{
  "input_video_url": "https://example.com/path/to/my_video.mp4",
  "overlay_image_url": "https://example.com/path/to/animated_logo.mov", // Can be video!
  "background_music_url": "https://example.com/path/to/track.mp3",
  "webhook_url": "https://myapp.com/webhook/video-processed",
  "content_id": "job-456-xyz",
  "overlay_position": "full", // Scale to full size
  "music_volume": 0.3,
  "output_filename": "final_branded_video_v2",
  "overlay_opacity": 0.8, // Slightly transparent
  "overlay_blend_mode": "screen" // Use screen blend mode
}
```

## Response

### Immediate Response (Synchronous)

If the request payload is valid and authenticated, the API immediately responds with `202 Accepted`:

```json
{
  "status": "processing",
  "message": "Overlay/music addition process started for job-456-xyz. Result will be sent to https://myapp.com/webhook/video-processed"
}
```

### Final Response (Asynchronous Webhook)

Once processing is complete (either success or failure), the service sends a POST request to the `webhook_url` provided in the initial request.

#### Success Payload

```json
{
  "content_id": "job-456-xyz",
  "status": "completed",
  "s3_url": "https://your-s3-endpoint.com/your-bucket/final_branded_video_v2.mp4" 
}

```

#### Failure Payload

```json
{
  "content_id": "job-456-xyz",
  "status": "failed",
  "error": "Error processing overlay/music: Could not get dimensions/duration of input video ... "
}

``` 
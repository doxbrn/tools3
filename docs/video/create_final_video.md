# Create Final Video Endpoint

## 1. Overview

The `/v1/video/create-final-video` endpoint is a part of the Video API and is responsible for creating a final video by combining multiple scenes, each consisting of an image and audio. This endpoint is particularly useful for content creators who need to assemble a complete video from individual scene components. It fits into the overall API structure as a part of the version 1 (v1) routes, specifically under the `/v1/video` namespace.

## 2. Endpoint

**URL Path:** `/v1/video/create-final-video`
**HTTP Method:** `POST`

## 3. Request

### Headers

- `x-api-key` (required): The API key for authentication.

### Body Parameters

The request body must be a JSON object with the following properties:

- `scenes` (required, array of objects): An array of scene objects, each containing:
  - `image_url` (required, string, URI format): The URL of the image for the scene.
  - `audio_url` (required, string, URI format): The URL of the audio for the scene.
- `title` (optional, string): A title for the final video.
- `webhook_url` (optional, string, URI format): The URL to which the response should be sent as a webhook.
- `id` (optional, string): An identifier for the request.

The `validate_payload` decorator in the routes file enforces the following JSON schema for the request body:

```json
{
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image_url": {"type": "string", "format": "uri"},
                    "audio_url": {"type": "string", "format": "uri"}
                },
                "required": ["image_url", "audio_url"]
            },
            "minItems": 1
        },
        "title": {"type": "string"},
        "webhook_url": {"type": "string", "format": "uri"},
        "id": {"type": "string"}
    },
    "required": ["scenes"],
    "additionalProperties": false
}
```

### Example Request

```json
{
    "scenes": [
        {
            "image_url": "https://example.com/scene1_image.jpg",
            "audio_url": "https://example.com/scene1_audio.wav"
        },
        {
            "image_url": "https://example.com/scene2_image.jpg",
            "audio_url": "https://example.com/scene2_audio.wav"
        },
        {
            "image_url": "https://example.com/scene3_image.jpg",
            "audio_url": "https://example.com/scene3_audio.wav"
        }
    ],
    "title": "My Final Video",
    "webhook_url": "https://example.com/webhook",
    "id": "request-123"
}
```

```bash
curl -X POST \
     -H "x-api-key: YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
        "scenes": [
            {
                "image_url": "https://example.com/scene1_image.jpg",
                "audio_url": "https://example.com/scene1_audio.wav"
            },
            {
                "image_url": "https://example.com/scene2_image.jpg",
                "audio_url": "https://example.com/scene2_audio.wav"
            },
            {
                "image_url": "https://example.com/scene3_image.jpg",
                "audio_url": "https://example.com/scene3_audio.wav"
            }
        ],
        "title": "My Final Video",
        "webhook_url": "https://example.com/webhook",
        "id": "request-123"
     }' \
     https://your-api-endpoint.com/v1/video/create-final-video
```

## 4. Response

### Success Response

The success response follows the general response format defined in the `app.py` file. Here's an example:

```json
{
    "endpoint": "/v1/video/create-final-video",
    "code": 200,
    "id": "request-123",
    "job_id": "a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6",
    "response": "https://cloud-storage.example.com/final-video.mp4",
    "message": "success",
    "pid": 12345,
    "queue_id": 6789,
    "run_time": 15.678,
    "queue_time": 3.456,
    "total_time": 19.134,
    "queue_length": 0,
    "build_number": "1.0.0"
}
```

The `response` field contains the URL of the final video file uploaded to cloud storage.

### Error Responses

- **400 Bad Request**: Returned when the request body is missing or invalid.

  ```json
  {
    "code": 400,
    "message": "Invalid request payload"
  }
  ```

- **401 Unauthorized**: Returned when the `x-api-key` header is missing or invalid.

  ```json
  {
    "code": 401,
    "message": "Unauthorized"
  }
  ```

- **429 Too Many Requests**: Returned when the maximum queue length is reached.

  ```json
  {
    "code": 429,
    "id": "request-123",
    "job_id": "a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6",
    "message": "MAX_QUEUE_LENGTH (100) reached",
    "pid": 12345,
    "queue_id": 6789,
    "queue_length": 100,
    "build_number": "1.0.0"
  }
  ```

- **500 Internal Server Error**: Returned when an unexpected error occurs during the final video creation process.

  ```json
  {
    "code": 500,
    "message": "An error occurred during final video creation"
  }
  ```

## 5. Error Handling

The endpoint handles the following common errors:

- **Missing or invalid request body**: If the request body is missing or does not conform to the expected JSON schema, a 400 Bad Request error is returned.
- **Missing or invalid API key**: If the `x-api-key` header is missing or invalid, a 401 Unauthorized error is returned.
- **Queue length exceeded**: If the maximum queue length is reached (determined by the `MAX_QUEUE_LENGTH` environment variable), a 429 Too Many Requests error is returned.
- **Unexpected errors during final video creation**: If an unexpected error occurs during the final video creation process, a 500 Internal Server Error is returned with the error message.

## 6. Usage Notes

- The scenes will be processed in the order they appear in the `scenes` array.
- Each scene consists of a static image combined with an audio track.
- The duration of each segment in the final video is determined by the duration of the corresponding audio file.
- If the `webhook_url` parameter is provided, the response will be sent as a webhook to the specified URL.
- The `id` parameter can be used to identify the request in the response.
- The `title` parameter is optional and can be used to provide a title for the final video.

## 7. Common Issues

- **Invalid URLs**: Ensure that the image and audio URLs are valid and publicly accessible.
- **Unsupported media formats**: The service expects images in common formats (jpg, png) and audio in formats like wav or mp3.
- **Audio duration**: Very short audio files may result in segments that are too brief to be properly processed.
- **Number of scenes**: Processing a large number of scenes may take a significant amount of time.

## 8. Best Practices

- **Pre-process media files**: Ensure that your image and audio files are properly formatted and optimized before using this endpoint.
- **Staggered requests**: If you have many videos to create, consider staggering your requests to avoid hitting queue limits.
- **Error handling**: Implement proper error handling in your client application to deal with potential errors returned by the endpoint.
- **Webhooks**: For long-running processes, use the webhook functionality to receive notifications when the process is complete rather than polling the API.
- **Cleanup**: Once you've downloaded and processed the final video, consider implementing cleanup procedures to free up storage space. 
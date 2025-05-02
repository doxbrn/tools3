# services/s3_toolkit.py

import os
import boto3
from urllib.parse import quote
import logging

logger = logging.getLogger(__name__)

def upload_to_s3(local_path: str, s3_key: str) -> str:
    """
    Uploads a local file to S3 using the env-vars definidas em config.py.
    Retorna a URL pública do objeto.
    """
    from config import S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET_NAME, S3_REGION

    session = boto3.Session(
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION
    )
    client = session.client("s3", endpoint_url=S3_ENDPOINT_URL)

    filename = os.path.basename(local_path)
    try:
        with open(local_path, "rb") as f:
            client.upload_fileobj(
                f,
                S3_BUCKET_NAME,
                s3_key,
                ExtraArgs={"ACL": "public-read"}
            )
        url = f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/{quote(s3_key)}"
        return url
    except Exception as e:
        logger.error(f"Error uploading {local_path} to S3: {e}")
        raise
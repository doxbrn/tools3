#!/usr/bin/env python3
"""
Example usage of the AirtableClient class to interact with Content Flow base
and manage job logs.
"""

import os
import sys
import json
import uuid
import time
from datetime import datetime

# Add the parent directory to the path to import from services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.airtable_client import AirtableClient


def setup_client():
    """Set up and return an AirtableClient instance."""
    # Use API key from environment variable or directly provide it here
    api_key = os.environ.get("AIRTABLE_API_KEY")
    
    if not api_key:
        # For demonstration, use the API key from the command line argument
        if len(sys.argv) > 1:
            api_key = sys.argv[1]
        else:
            print("Please provide an Airtable API key as an environment variable "
                  "AIRTABLE_API_KEY or as a command line argument")
            sys.exit(1)
    
    return AirtableClient(api_key=api_key)


def list_tables_example(client):
    """Example: List all tables in the Content Flow base."""
    print("\n=== Listing Tables ===")
    tables = client.list_tables()
    if isinstance(tables, list):
        for idx, table in enumerate(tables, 1):
            print(f"{idx}. {table.get('name', 'Unknown')} (ID: {table.get('id', 'Unknown')})")
    else:
        print("Failed to list tables:", tables)


def list_channels_example(client):
    """Example: List channels from the Canais table."""
    print("\n=== Listing Channels ===")
    channels = client.list_records("channels", max_records=5)
    
    for channel in channels:
        channel_name = channel.get("fields", {}).get("Nome_Canal", "Unknown")
        channel_id = channel.get("fields", {}).get("ID_Canal", "Unknown")
        status = channel.get("fields", {}).get("Status", "Unknown")
        print(f"Channel: {channel_name} (ID: {channel_id}, Status: {status})")


def logs_example(client):
    """Example: Create and manage job logs."""
    print("\n=== Job Logs Management Example ===")
    
    # Generate a unique job ID
    job_id = f"job-{uuid.uuid4()}"
    print(f"Creating example job with ID: {job_id}")
    
    # Create a new job log
    job_log = client.create_job_log(
        job_id=job_id,
        job_type="Image_Generation",
        service_name="example_service",
        metadata={
            "parameters": {
                "model": "stable-diffusion",
                "prompt": "beautiful landscape with mountains",
                "negative_prompt": "ugly, blurry",
                "steps": 30,
                "width": 1024,
                "height": 1024
            }
        }
    )
    
    if "id" not in job_log:
        print("Failed to create job log:", job_log)
        return
    
    log_id = job_log["id"]
    print(f"Created job log with record ID: {log_id}")
    
    # Update job status to running
    print("Updating job status to Running...")
    client.update_job_status(
        log_record_id=log_id,
        status="Running",
        log_message="Job started processing"
    )
    
    # Add progress messages
    print("Adding progress messages...")
    for i in range(1, 4):
        time.sleep(1)  # Simulate processing time
        client.add_log_message(
            log_record_id=log_id,
            message=f"Processing step {i}/3 - {i*33}% complete"
        )
    
    # Update metadata with results
    print("Adding metadata with results...")
    client.update_job_status(
        log_record_id=log_id,
        status="Completed",
        log_message="Job completed successfully",
        metadata_updates={
            "results": {
                "image_url": "https://example.com/images/generated_1234.png",
                "generation_seed": 12345,
                "processing_time": 3.5
            }
        }
    )
    
    # Retrieve and display the complete job log
    print("\nRetrieving complete job log:")
    job_logs = client.get_job_logs(job_id=job_id)
    
    if job_logs:
        log_record = job_logs[0]
        fields = log_record.get("fields", {})
        
        print(f"Job ID: {fields.get('Job_ID')}")
        print(f"Status: {fields.get('Status')}")
        print(f"Job Type: {fields.get('Job_Type')}")
        print(f"Started At: {fields.get('Started_At')}")
        print(f"Completed At: {fields.get('Completed_At')}")
        print(f"Duration: {fields.get('Duration_Seconds')} seconds")
        print("\nLog Messages:")
        print(fields.get("Log_Messages"))
        
        if "Metadata" in fields:
            try:
                metadata = json.loads(fields["Metadata"])
                print("\nMetadata:")
                print(json.dumps(metadata, indent=2))
            except json.JSONDecodeError:
                print("Failed to parse metadata")
    else:
        print("Failed to retrieve job logs")


def main():
    """Run the examples."""
    client = setup_client()
    
    # Run examples
    list_tables_example(client)
    list_channels_example(client)
    logs_example(client)
    
    print("\nExamples completed successfully!")


if __name__ == "__main__":
    main() 
import os
import json
import requests
from typing import Dict, List
from datetime import datetime


class AirtableClient:
    """
    A complete Airtable client for interacting with the Content Flow base.
    Provides functionality to work with all tables and includes specialized methods
    for logs management.
    """
    
    BASE_URL = "https://api.airtable.com/v0"
    
    def __init__(self, api_key: str = None, base_id: str = None):
        """
        Initialize the Airtable client.
        
        Args:
            api_key: Airtable API key. If not provided, will look for AIRTABLE_API_KEY env var.
            base_id: Airtable base ID. If not provided, will use Content Flow base ID.
        """
        self.api_key = api_key or os.environ.get("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("Airtable API key is required")
        
        # Default to Content Flow base ID if not specified
        self.base_id = base_id or "appVgvW0XEsJLXZ0P"  # Content Flow base ID
        
        # Table IDs from Content Flow base
        self.tables = {
            "channels": "tbl81UhgC1U9wJe8Q",        # Canais
            "contents": "tblG4KH7skP2FYfm3",        # Conteudos
            "scenes": "tbl8VAVMlPkxFxYNb",          # Cenas
            "actions": "tblLJzUfEA2AA8IjN",         # AI Actions
            "image_bank": "tblQw34bi1fzIFKWK",      # Banco_imagens
            "assets": "tbl1a8nCgMSURg7Kz",          # Assets
            "models": "tbl8n9mlmSmEly1x3",          # Models
            "config": "tbl6IaMIcpPunrPm6",          # Configuracoes
            "channels_accounts": "tbljjtNyXnwcaYKIi",  # Contas Canais
            "video_templates": "tblMF4Gxk83gvmmSK",  # Templates Video
            "costs": "tblhNcsXcFjDVveRS",           # Cost
        }
        
        # Default headers for all requests
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Create logs table if it doesn't exist
        self._ensure_logs_table_exists()
    
    def _ensure_logs_table_exists(self):
        """Ensure that the logs table exists in the base, creating it if needed."""
        try:
            # Check if logs table exists by listing all tables
            # If it doesn't exist in our table mapping, we'll create it
            if "logs" not in self.tables:
                print("Creating logs table...")
                response = self.create_table(
                    table_name="Jobs_Logs",
                    description="Track processing jobs and their logs",
                    fields=[
                        {
                            "name": "Job_ID",
                            "type": "singleLineText",
                            "description": "Unique identifier for the job"
                        },
                        {
                            "name": "Status",
                            "type": "singleSelect",
                            "description": "Current status of the job",
                            "options": {
                                "choices": [
                                    {"name": "Pending", "color": "yellowBright"},
                                    {"name": "Running", "color": "blueBright"},
                                    {"name": "Completed", "color": "greenBright"},
                                    {"name": "Failed", "color": "redBright"},
                                    {"name": "Canceled", "color": "grayLight1"}
                                ]
                            }
                        },
                        {
                            "name": "Job_Type",
                            "type": "singleSelect",
                            "description": "Type of job being processed",
                            "options": {
                                "choices": [
                                    {"name": "Content_Generation", "color": "purpleLight2"},
                                    {"name": "Image_Generation", "color": "orangeLight2"},
                                    {"name": "Audio_Generation", "color": "tealBright"},
                                    {"name": "Video_Generation", "color": "blueLight2"},
                                    {"name": "Video_Processing", "color": "cyanLight2"},
                                    {"name": "Content_Translation", "color": "pinkLight2"},
                                    {"name": "File_Upload", "color": "greenLight2"},
                                    {"name": "File_Download", "color": "yellowLight2"}
                                ]
                            }
                        },
                        {
                            "name": "Related_Content_ID",
                            "type": "singleLineText",
                            "description": "ID of related content in the Conteudos table"
                        },
                        {
                            "name": "Related_Scene_ID",
                            "type": "singleLineText",
                            "description": "ID of related scene in the Cenas table"
                        },
                        {
                            "name": "Started_At",
                            "type": "dateTime",
                            "description": "When the job was started"
                        },
                        {
                            "name": "Completed_At",
                            "type": "dateTime",
                            "description": "When the job was completed"
                        },
                        {
                            "name": "Duration_Seconds",
                            "type": "number",
                            "description": "Total processing time in seconds"
                        },
                        {
                            "name": "Log_Messages",
                            "type": "multilineText",
                            "description": "Accumulated log messages"
                        },
                        {
                            "name": "Service_Name",
                            "type": "singleLineText",
                            "description": "Name of the service that processed the job"
                        },
                        {
                            "name": "Error_Details",
                            "type": "multilineText",
                            "description": "Detailed error information if job failed"
                        },
                        {
                            "name": "Metadata",
                            "type": "multilineText",
                            "description": "Additional job metadata in JSON format"
                        }
                    ]
                )
                
                if response and "id" in response:
                    self.tables["logs"] = response["id"]
                    print(f"Logs table created with ID: {response['id']}")
                else:
                    print("Failed to create logs table")
            
        except Exception as e:
            print(f"Error ensuring logs table exists: {str(e)}")
    
    def _make_request(self, method: str, endpoint: str, data: dict = None, params: dict = None) -> dict:
        """
        Make a request to the Airtable API.
        
        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint
            data: Request body data
            params: URL parameters
            
        Returns:
            API response as dictionary
        """
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params
            )
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response:
                try:
                    error_data = e.response.json()
                    error_msg += f" - {json.dumps(error_data)}"
                except:
                    error_msg += f" - Status code: {e.response.status_code}"
            print(error_msg)
            return {"error": error_msg}

    # Base methods for table management
    def list_bases(self) -> List[Dict]:
        """List all accessible bases"""
        return self._make_request("GET", "meta/bases")
    
    def list_tables(self) -> List[Dict]:
        """List all tables in the base"""
        return self._make_request("GET", f"meta/bases/{self.base_id}/tables")
    
    def create_table(self, table_name: str, description: str = "", fields: List[Dict] = None) -> Dict:
        """
        Create a new table in the base.
        
        Args:
            table_name: Name of the new table
            description: Optional description of the table
            fields: List of field configurations for the table
            
        Returns:
            New table information
        """
        data = {
            "name": table_name,
            "description": description,
            "fields": fields or []
        }
        return self._make_request("POST", f"meta/bases/{self.base_id}/tables", data=data)
    
    # Record methods
    def list_records(self, table_name: str, max_records: int = 100, view: str = None) -> List[Dict]:
        """
        List records from a table.
        
        Args:
            table_name: Table name or ID
            max_records: Maximum number of records to return
            view: Optional view ID to filter records
            
        Returns:
            List of records
        """
        table_id = self._get_table_id(table_name)
        params = {"maxRecords": max_records}
        if view:
            params["view"] = view
            
        response = self._make_request("GET", f"{self.base_id}/{table_id}", params=params)
        return response.get("records", [])
    
    def get_record(self, table_name: str, record_id: str) -> Dict:
        """
        Get a single record by ID.
        
        Args:
            table_name: Table name or ID
            record_id: Record ID
            
        Returns:
            Record data
        """
        table_id = self._get_table_id(table_name)
        return self._make_request("GET", f"{self.base_id}/{table_id}/{record_id}")
    
    def create_record(self, table_name: str, fields: Dict) -> Dict:
        """
        Create a new record in a table.
        
        Args:
            table_name: Table name or ID
            fields: Record fields as key-value pairs
            
        Returns:
            Created record data
        """
        table_id = self._get_table_id(table_name)
        data = {"fields": fields}
        return self._make_request("POST", f"{self.base_id}/{table_id}", data=data)
    
    def update_record(self, table_name: str, record_id: str, fields: Dict) -> Dict:
        """
        Update an existing record.
        
        Args:
            table_name: Table name or ID
            record_id: Record ID to update
            fields: Fields to update
            
        Returns:
            Updated record data
        """
        table_id = self._get_table_id(table_name)
        data = {"fields": fields}
        return self._make_request("PATCH", f"{self.base_id}/{table_id}/{record_id}", data=data)
    
    def delete_record(self, table_name: str, record_id: str) -> Dict:
        """
        Delete a record.
        
        Args:
            table_name: Table name or ID
            record_id: Record ID to delete
            
        Returns:
            Deletion confirmation
        """
        table_id = self._get_table_id(table_name)
        return self._make_request("DELETE", f"{self.base_id}/{table_id}/{record_id}")
    
    def search_records(self, table_name: str, field_name: str, value: str) -> List[Dict]:
        """
        Search for records with a specific field value.
        
        Args:
            table_name: Table name or ID
            field_name: Field to search in
            value: Value to search for
            
        Returns:
            List of matching records
        """
        table_id = self._get_table_id(table_name)
        filter_by_formula = f"{{{field_name}}}='{value}'"
        params = {"filterByFormula": filter_by_formula}
        
        response = self._make_request("GET", f"{self.base_id}/{table_id}", params=params)
        return response.get("records", [])
    
    def _get_table_id(self, table_name: str) -> str:
        """
        Get the table ID from a table name or return the ID if it's already an ID.
        
        Args:
            table_name: Table name or ID
            
        Returns:
            Table ID
        """
        if table_name in self.tables:
            return self.tables[table_name]
        return table_name
    
    # Specialized methods for logs
    def create_job_log(self, job_id: str, job_type: str, service_name: str, 
                       related_content_id: str = None, related_scene_id: str = None,
                       metadata: Dict = None) -> Dict:
        """
        Create a new job log entry.
        
        Args:
            job_id: Unique identifier for the job
            job_type: Type of job (from predefined options)
            service_name: Name of the service processing the job
            related_content_id: Optional ID of related content
            related_scene_id: Optional ID of related scene
            metadata: Optional additional metadata
            
        Returns:
            Created log record
        """
        now = datetime.now().isoformat()
        
        fields = {
            "Job_ID": job_id,
            "Status": "Pending",
            "Job_Type": job_type,
            "Service_Name": service_name,
            "Started_At": now,
            "Log_Messages": f"[{now}] Job created and pending execution\n"
        }
        
        if related_content_id:
            fields["Related_Content_ID"] = related_content_id
            
        if related_scene_id:
            fields["Related_Scene_ID"] = related_scene_id
            
        if metadata:
            fields["Metadata"] = json.dumps(metadata, indent=2)
            
        return self.create_record("logs", fields)
    
    def update_job_status(self, log_record_id: str, status: str, 
                          log_message: str = None, error_details: str = None,
                          metadata_updates: Dict = None) -> Dict:
        """
        Update a job's status and add log messages.
        
        Args:
            log_record_id: Log record ID to update
            status: New status (Pending, Running, Completed, Failed)
            log_message: Optional message to append to logs
            error_details: Optional error details if status is Failed
            metadata_updates: Optional metadata to update or add
            
        Returns:
            Updated log record
        """
        now = datetime.now().isoformat()
        fields = {"Status": status}
        
        # Get current record to update the log messages
        current_record = self.get_record("logs", log_record_id)
        current_logs = current_record.get("fields", {}).get("Log_Messages", "")
        
        # Add new log message
        if log_message:
            fields["Log_Messages"] = f"{current_logs}[{now}] {log_message}\n"
        
        # Set completed time and duration if job is finished
        if status in ["Completed", "Failed", "Canceled"]:
            fields["Completed_At"] = now
            
            # Calculate duration if we have a start time
            if "Started_At" in current_record.get("fields", {}):
                start_time = datetime.fromisoformat(current_record["fields"]["Started_At"])
                end_time = datetime.fromisoformat(now)
                duration_seconds = (end_time - start_time).total_seconds()
                fields["Duration_Seconds"] = duration_seconds
        
        # Add error details if provided
        if error_details:
            fields["Error_Details"] = error_details
            
        # Update metadata if provided
        if metadata_updates:
            current_metadata = {}
            try:
                if "Metadata" in current_record.get("fields", {}):
                    current_metadata = json.loads(current_record["fields"]["Metadata"])
            except json.JSONDecodeError:
                current_metadata = {}
                
            # Update with new metadata
            current_metadata.update(metadata_updates)
            fields["Metadata"] = json.dumps(current_metadata, indent=2)
            
        return self.update_record("logs", log_record_id, fields)
    
    def add_log_message(self, log_record_id: str, message: str) -> Dict:
        """
        Add a log message to an existing job log.
        
        Args:
            log_record_id: Log record ID
            message: Message to add to the log
            
        Returns:
            Updated log record
        """
        now = datetime.now().isoformat()
        
        # Get current record to update the log messages
        current_record = self.get_record("logs", log_record_id)
        current_logs = current_record.get("fields", {}).get("Log_Messages", "")
        
        fields = {
            "Log_Messages": f"{current_logs}[{now}] {message}\n"
        }
        
        return self.update_record("logs", log_record_id, fields)
    
    def get_job_logs(self, job_id: str = None, job_type: str = None, 
                    status: str = None, service_name: str = None,
                    related_content_id: str = None, related_scene_id: str = None) -> List[Dict]:
        """
        Search for job logs with various filters.
        
        Args:
            job_id: Filter by job ID
            job_type: Filter by job type
            status: Filter by status
            service_name: Filter by service name
            related_content_id: Filter by related content ID
            related_scene_id: Filter by related scene ID
            
        Returns:
            List of matching log records
        """
        filters = []
        
        if job_id:
            filters.append(f"{{Job_ID}}='{job_id}'")
            
        if job_type:
            filters.append(f"{{Job_Type}}='{job_type}'")
            
        if status:
            filters.append(f"{{Status}}='{status}'")
            
        if service_name:
            filters.append(f"{{Service_Name}}='{service_name}'")
            
        if related_content_id:
            filters.append(f"{{Related_Content_ID}}='{related_content_id}'")
            
        if related_scene_id:
            filters.append(f"{{Related_Scene_ID}}='{related_scene_id}'")
            
        # If we have filters, build the formula
        if filters:
            filter_formula = "AND(" + ",".join(filters) + ")"
            params = {"filterByFormula": filter_formula}
            response = self._make_request("GET", f"{self.base_id}/{self.tables['logs']}", params=params)
            return response.get("records", [])
        else:
            # No filters, return all logs
            return self.list_records("logs") 
# Airtable Base: Content Flow

**Base ID:** `appVgvW0XEsJLXZ0P`

## Overview

This Airtable base is designed to manage the workflow for creating video content, from defining channel personalities and themes to generating individual scenes and assembling the final video. It serves as the central hub for coordinating automated and manual steps in the content creation pipeline.

## Tables

### 1. Canais

- **Table ID:** `tbl81UhgC1U9wJe8Q`
- **Purpose:** Defines the different channels or content series. Each record represents a unique channel with its specific identity, tone, style, and content generation guidelines.
- **Key Fields (Inferred from sample record):**
    - `ID_Canal`: Unique identifier for the channel (e.g., `CH-rec0SBDz3rsZbCt9Z`).
    - `Nome_Canal`: Name of the channel (e.g., "A Tribo da Chama Sagrada").
    - `Status`: Current status of the channel (e.g., "Em Desenvolvimento").
    - `Personalidade`: Description of the channel's persona and archetype.
    - `Tom_Voz`: Guidelines for the narrative tone and voice.
    - `Estilo_Escrita`: Rules for writing style, vocabulary, and structure.
    - `Tema_Central`: Core themes the channel explores.
    - `Instrucoes_Geracao_Tema`: Prompts/guidelines for generating specific content themes.
    - `Instrucoes_Geracao_Conteudo`: Detailed instructions for structuring and generating the full content script, including frameworks and triggers.
    - `Restricoes_Conteudo`: Content restrictions and things to avoid.
    - `Diretrizes_Estrutura_Texto`: Specific rules for text structure.
    - `Conteudos`: Linked records from the `Conteudos` table.
    - `Image Action`, `Audio Action`, `Video Action`: Likely linked records defining automated actions/workflows (e.g., for generating images, audio, video).
    - `TTS_Guidelines`: Specific instructions for formatting text for Text-to-Speech generation.
    - `Channel Profile Summary`: A consolidated summary of the channel's profile fields.
    - `Min Words Scene`: Minimum word count per scene.
    - `Tamanho Texto`: Target word count range for the full script.

### 2. Conteudos

- **Table ID:** `tblG4KH7skP2FYfm3`
- **Purpose:** Represents individual pieces of content (e.g., a specific video script) generated for a channel.
- **Key Fields (Inferred from sample record):**
    - `ID`: Unique identifier for the content piece (e.g., `C-142`).
    - `Canal`: Linked record from the `Canais` table, indicating the channel this content belongs to.
    - `Tema Name`: The specific title or theme of this content piece (e.g., "A Bússola da Alma...").
    - `Roteiro_Completo`: The full script generated for the content.
    - `Texto English`: English translation of the script.
    - `Status_Geral`: Overall status of the content piece (e.g., "Assets_Pendente").
    - `Cenas`: Linked records from the `Cenas` table, representing the individual scenes comprising this content.
    - `Words`: Total word count of the `Roteiro_Completo`.
    - `Text Length`: Character count of the `Roteiro_Completo`.
    - `Tema Completo`: JSON object containing detailed theme information (description, justification, hooks, structure, etc.).
    - `webhook_url` (Optional): A specific webhook URL to notify upon completion of processes related to this content (e.g., video rendering). If not provided, a default webhook might be used by the system.

### 3. Cenas

- **Table ID:** `tbl8b8YqU2T0v7k2T`
- **Purpose:** Represents individual scenes within a piece of content. Each scene typically has associated text, and eventually, corresponding image and audio assets.
- **Key Fields (Inferred from sample record):**
    - `ID_Cena`: Unique identifier for the scene (e.g., `CENA-rec08XolW5uVAfVzO`).
    - `Conteudo`: Linked record from the `Conteudos` table (inferred, based on workflow).
    - `Ordem`: Numerical order of the scene within the content.
    - `Texto_Cena`: The script portion for this specific scene.
    - `Status_Cena`: Status of the scene generation (e.g., "Pendente").
    - `words`: Word count of the `Texto_Cena`.
    - `duracao`: Duration of the scene (likely calculated after audio generation).
    - `url_s3_image`: (Expected Field) URL of the generated image asset for the scene stored in S3.
    - `url_s3_audio`: (Expected Field) URL of the generated audio asset for the scene stored in S3.

## Workflow Integration

This base integrates with external services and workflows (like n8n and the custom API endpoints):

1.  **Content Generation:** Scripts (`Roteiro_Completo`) are generated based on channel definitions (`Canais`) and themes, then stored in `Conteudos`.
2.  **Scene Breakdown:** Scripts are broken down into individual scenes (`Cenas`), linked back to the main content.
3.  **Asset Generation:** Automated processes (potentially triggered by Airtable Automations or external workflows like n8n) generate image and audio assets for each scene, storing their S3 URLs (e.g., `url_s3_image`, `url_s3_audio`) back into the corresponding `Cenas` records.
4.  **Video Creation:** Workflows (like the `create_final_video.json` n8n workflow) read data from `Conteudos` and `Cenas` (specifically the asset URLs and order) to trigger the `/v1/video/create-final-video` API endpoint.
5.  **Webhook Notification:** The video creation service (`services/v1/video/create_final_video.py`) uses the `webhook_url` from the `Conteudos` record (or a default) to send a notification upon completion (success or failure) of the video rendering and S3 upload. 
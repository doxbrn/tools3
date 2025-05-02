# Video Processing - Create Final Video

## Descrição

Este endpoint cria um vídeo final combinando múltiplas cenas (imagem + áudio). Cada cena pode ter efeitos visuais aplicados, e o vídeo final pode incluir música de fundo, overlay e legendas.

## Endpoint API

```
POST /v1/video/create-final-video
```

## Parâmetros da Requisição

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|------------|------------|
| scenes | array | Sim | Array de cenas para incluir no vídeo |
| title | string | Não | Título do vídeo (usado em notificações) |
| webhook_url | string | Não | URL para notificar quando o processamento for concluído |
| id | string | Não | Identificador personalizado para o vídeo |
| advanced_options | object | Não | Opções avançadas de processamento de vídeo |

### Estrutura de Cena

Cada cena no array `scenes` deve ter a seguinte estrutura:

```json
{
  "image_url": "https://exemplo.com/imagem.jpg",
  "audio_url": "https://exemplo.com/audio.mp3",
  "text": "Texto opcional para legendas",
  "options": {
    "overlay": {
      "url": "https://exemplo.com/overlay.png",
      "position": "Topo",
      "opacity": 80
    },
    "zoom": {
      "type": "Zoom In",
      "speed": 5
    }
  }
}
```

### Opções Avançadas Globais

O objeto `advanced_options` permite definir configurações globais para todo o vídeo:

```json
{
  "overlay": {
    "url": "https://exemplo.com/overlay-global.png",
    "position": "Topo",
    "opacity": 80
  },
  "zoom": {
    "type": "Zoom In",
    "speed": 5
  },
  "background_music": {
    "url": "https://exemplo.com/musica-fundo.mp3",
    "volume": 20
  },
  "captions": {
    "enabled": true,
    "style": "Padrão"
  },
  "transitions": {
    "type": "Fade",
    "duration": 1.0
  }
}
```

## Opções Detalhadas

### Overlay

| Opção | Tipo | Valores Possíveis | Descrição |
|-------|------|-------------------|-----------|
| url | string | URL válida | URL do arquivo de overlay (geralmente PNG com transparência) |
| position | string | "Topo", "Centro", "Base", "Personalizado" | Posição do overlay no vídeo |
| opacity | number | 0-100 | Opacidade do overlay em porcentagem |

### Zoom

| Opção | Tipo | Valores Possíveis | Descrição |
|-------|------|-------------------|-----------|
| type | string | "Zoom In", "Zoom Out", "Pan Horizontal", "Pan Vertical", "Ken Burns", "Nenhum" | Tipo de efeito de zoom |
| speed | number | 1-20 | Velocidade do efeito em porcentagem |

#### Tipos de Zoom
- **Zoom In**: Aproxima gradualmente a imagem
- **Zoom Out**: Afasta gradualmente a imagem
- **Pan Horizontal**: Move horizontalmente pela imagem
- **Pan Vertical**: Move verticalmente pela imagem
- **Ken Burns**: Combinação de movimento e zoom aleatórios
- **Nenhum**: Imagem estática sem efeitos

### Música de Fundo

| Opção | Tipo | Valores Possíveis | Descrição |
|-------|------|-------------------|-----------|
| url | string | URL válida | URL do arquivo de áudio para música de fundo |
| volume | number | 0-100 | Volume da música de fundo em porcentagem |

### Legendas

| Opção | Tipo | Valores Possíveis | Descrição |
|-------|------|-------------------|-----------|
| enabled | boolean | true/false | Ativa ou desativa as legendas |
| style | string | "Padrão", "Contrastado", "Minimalista", "Grande" | Estilo visual das legendas |

### Transições

| Opção | Tipo | Valores Possíveis | Descrição |
|-------|------|-------------------|-----------|
| type | string | "Corte Seco", "Fade", "Dissolver", "Deslizar", "Zoom" | Tipo de transição entre cenas |
| duration | number | 0.1-3.0 | Duração da transição em segundos |

## Configuração via Airtable

As opções avançadas também podem ser configuradas no Airtable por canal ou por cena:

### Configuração por Canal (tabela "Canais")

| Campo | Descrição |
|-------|-----------|
| Resolucao_Padrao | Resolução do vídeo (1920x1080, 1080x1920, etc.) |
| Frame_Rate_Padrao | Taxa de quadros do vídeo |
| Zoom_Tipo | Tipo de zoom padrão para todas as cenas |
| Zoom_Speed_Imagem (%) | Velocidade do zoom em porcentagem |
| Overlay_Default_URL | URL do overlay padrão |
| Overlay_Posicao | Posição padrão do overlay |
| Overlay_Opacidade | Opacidade do overlay em porcentagem |
| Musica_Fundo_Default_URL | URL da música de fundo padrão |
| Volume_Musica_Fundo (%) | Volume da música de fundo em porcentagem |
| Legendas_Ativar | Ativa ou desativa legendas |
| Legendas_Estilo | Estilo visual das legendas |
| Efeitos_Transicao | Tipo de transição entre cenas |
| Duracao_Transicao_Seg | Duração da transição em segundos |

### Configuração por Cena (tabela "Cenas")

| Campo | Descrição |
|-------|-----------|
| Zoom_Tipo_Custom | Sobrescreve o tipo de zoom do canal para esta cena |
| Zoom_Speed_Custom | Sobrescreve a velocidade do zoom para esta cena |
| Overlay_Custom_URL | Sobrescreve o overlay do canal para esta cena |
| Musica_Fundo_Custom_URL | Sobrescreve a música de fundo para esta cena |
| Volume_Musica_Custom | Sobrescreve o volume da música para esta cena |

## Prioridade das Configurações

O sistema usa a seguinte ordem de prioridade para determinar as configurações a serem aplicadas:

1. Opções específicas da cena no payload (mais alta prioridade)
2. Configurações da cena no Airtable
3. Opções avançadas globais no payload
4. Configurações do canal no Airtable (mais baixa prioridade)

## Exemplo de Requisição

```json
{
  "scenes": [
    {
      "image_url": "https://exemplo.com/imagem1.jpg",
      "audio_url": "https://exemplo.com/audio1.mp3",
      "text": "Esta é a primeira cena com zoom in",
      "options": {
        "zoom": {
          "type": "Zoom In",
          "speed": 8
        }
      }
    },
    {
      "image_url": "https://exemplo.com/imagem2.jpg",
      "audio_url": "https://exemplo.com/audio2.mp3",
      "text": "Esta é a segunda cena com pan horizontal",
      "options": {
        "zoom": {
          "type": "Pan Horizontal",
          "speed": 5
        },
        "overlay": {
          "url": "https://exemplo.com/overlay-cena2.png",
          "position": "Base",
          "opacity": 70
        }
      }
    }
  ],
  "title": "Meu Vídeo com Efeitos",
  "webhook_url": "https://meuservidor.com/webhook",
  "id": "video-123",
  "advanced_options": {
    "overlay": {
      "url": "https://exemplo.com/overlay-padrao.png",
      "position": "Topo",
      "opacity": 80
    },
    "background_music": {
      "url": "https://exemplo.com/musica-fundo.mp3",
      "volume": 15
    },
    "captions": {
      "enabled": true,
      "style": "Contrastado"
    },
    "transitions": {
      "type": "Fade",
      "duration": 1.2
    }
  }
}
```

## Resposta

```json
{
  "job_id": "e5684e3f-b184-4c2e-81e3-3a61673766b8",
  "status": "processing",
  "message": "Video creation started. You will be notified via webhook when complete."
}
```

## Notificação de Webhook

Quando o processamento for concluído, uma notificação será enviada para o `webhook_url` (se fornecido) com o seguinte formato:

```json
{
  "job_id": "e5684e3f-b184-4c2e-81e3-3a61673766b8",
  "status": "completed",
  "data": {
    "video_url": "https://bucket-name.s3.region.amazonaws.com/final_videos/e5684e3f-b184-4c2e-81e3-3a61673766b8_final.mp4",
    "title": "Meu Vídeo com Efeitos",
    "id": "video-123"
  }
}
```

Em caso de erro:

```json
{
  "job_id": "e5684e3f-b184-4c2e-81e3-3a61673766b8",
  "status": "failed",
  "error": "Mensagem de erro detalhada"
}
``` 
# Configuração do Google Cloud Storage (GCS) para NCA Toolkit

Este documento orienta como configurar corretamente o NCA Toolkit para usar o Google Cloud Storage.

## Erro Atual

Atualmente, você está encontrando o seguinte erro:
```
Invalid endpoint: https://s3..amazonaws.com
```

Este erro indica que há uma configuração incorreta no S3. Como você está tentando usar o Google Cloud Storage, precisamos ajustar as configurações.

## Opções de Configuração do GCS

### Opção 1: Usando arquivo de credenciais de conta de serviço

1. Você já possui o arquivo `Santograal Tools.json` com as credenciais da conta de serviço.
2. Configure as seguintes variáveis de ambiente no dokploy.com:

```
# Variáveis principais
API_KEY=123456

# Configurações GCP
GCP_SA_CREDENTIALS=<conteúdo do arquivo Santograal Tools.json como string JSON>
GCP_BUCKET_NAME=storage-paradox

# Desabilite as configurações S3 (remova ou deixe vazio)
S3_ENDPOINT_URL=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET_NAME=
S3_REGION=
```

### Opção 2: Usando HMAC Keys (mais simples)

Como você já possui as HMAC keys para o Google Cloud Storage, configure:

```
# Variáveis principais
API_KEY=123456

# Configurações GCP com HMAC
GCP_ACCESS_KEY=<YOUR_GCP_ACCESS_KEY>
GCP_SECRET_KEY=<YOUR_GCP_SECRET_KEY>
GCP_BUCKET_NAME=storage-paradox
GCP_REGION=us-central1

# Desabilite as configurações S3 (remova ou deixe vazio)
S3_ENDPOINT_URL=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET_NAME=
S3_REGION=
```

## Passos para Aplicar as Alterações

1. Acesse as configurações do aplicativo no dokploy.com
2. Atualize as variáveis de ambiente conforme uma das opções acima
3. Reinicie o aplicativo para que as novas configurações sejam aplicadas

## Verificação

Após atualizar as configurações, você poderá testar novamente o upload e verificar nos logs se o erro foi resolvido. 
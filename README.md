# Finanças Casa MG - Bot do Telegram

Assistente financeiro para gestão de gastos compartilhados em casa.

## 🚀 Deploy no Railway

### Pré-requisitos

1. **Criar um Bot no Telegram:**
   - Abra o Telegram e procure por `@BotFather`
   - Envie `/newbot`
   - Escolha um nome e username para o bot
   - **Salve o TOKEN** que o BotFather te enviar

2. **Configurar Google Sheets API:**
   - Acesse [Google Cloud Console](https://console.cloud.google.com/)
   - Crie um novo projeto
   - Ative a **Google Sheets API**
   - Vá em "Credenciais" → "Criar credenciais" → "Conta de serviço"
   - Crie uma conta de serviço
   - Clique na conta criada → "Chaves" → "Adicionar chave" → "JSON"
   - **Baixe o arquivo JSON**
   - Copie o email da service account (exemplo: `bot@projeto.iam.gserviceaccount.com`)
   - Compartilhe sua planilha Google Sheets com este email (permissão de edição)

### Deploy no Railway

#### Opção 1: Via GitHub (Recomendado)

1. **Criar repositório no GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/financas-casa-mg.git
   git push -u origin main
   ```

2. **Deploy no Railway:**
   - Acesse [railway.app](https://railway.app/)
   - Faça login com GitHub
   - Clique em "New Project" → "Deploy from GitHub repo"
   - Selecione seu repositório
   - Railway detectará automaticamente o `Procfile`

3. **Configurar variáveis de ambiente:**
   - No painel do Railway, vá em "Variables"
   - Adicione:
     ```
     TELEGRAM_BOT_TOKEN=seu_token_do_botfather
     GOOGLE_CREDENTIALS_JSON=conteúdo_completo_do_json
     ```
   
   **IMPORTANTE:** Para `GOOGLE_CREDENTIALS_JSON`:
   - Abra o arquivo JSON baixado no Google Cloud
   - Copie **TODO O CONTEÚDO** (minificado, sem quebras de linha)
   - Cole como valor da variável

4. **Deploy automático:**
   - Railway fará o deploy automaticamente
   - Acompanhe os logs para verificar se iniciou corretamente

#### Opção 2: Via Railway CLI

1. **Instalar Railway CLI:**
   ```bash
   npm i -g @railway/cli
   ```

2. **Login e deploy:**
   ```bash
   railway login
   railway init
   railway up
   ```

3. **Adicionar variáveis:**
   ```bash
   railway variables set TELEGRAM_BOT_TOKEN="seu_token"
   railway variables set GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}'
   ```

### Verificar se está funcionando

1. Abra o Telegram e procure seu bot
2. Envie `/start`
3. Se responder, está funcionando! ✅

### Comandos do Bot

- **Registrar gasto:** "Gastei R$150 com mercado"
- **/resumo** - Ver resumo do mês
- **/acerto** - Calcular quem deve pra quem
- **/historico** - Ver todos os gastos
- **/ajuda** - Instruções completas

### Estrutura do Projeto

```
telegram_bot/
├── bot.py              # Código principal do bot
├── requirements.txt    # Dependências Python
├── Procfile           # Comando para Railway executar
├── runtime.txt        # Versão do Python
└── README.md          # Esta documentação
```

### Troubleshooting

**Bot não responde:**
- Verifique se as variáveis de ambiente estão corretas
- Verifique os logs no Railway: `railway logs`
- Confirme que o bot foi adicionado ao grupo

**Erro ao acessar planilha:**
- Verifique se a service account tem acesso à planilha
- Confirme que `GOOGLE_CREDENTIALS_JSON` está correta (JSON válido)
- Teste o acesso manualmente com as credenciais

**Erro no deploy:**
- Verifique se `requirements.txt` está correto
- Confirme que `Procfile` existe
- Veja os logs de build no Railway

### Manutenção

- **Logs:** `railway logs` (via CLI) ou painel web
- **Reiniciar:** O Railway reinicia automaticamente se houver crash
- **Atualizar:** Push no GitHub dispara deploy automático

### Suporte

Para problemas:
1. Verifique os logs no Railway
2. Teste localmente: `python bot.py`
3. Verifique as variáveis de ambiente

---

**Desenvolvido para Casa MG** 🏠💰

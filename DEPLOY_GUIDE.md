# 🚀 GUIA RÁPIDO DE DEPLOY - Railway

## ⚡ Passo a Passo Simplificado

### 1️⃣ Criar Bot no Telegram (2 minutos)

1. Abra o Telegram
2. Procure: `@BotFather`
3. Envie: `/newbot`
4. Escolha nome: `Finanças Casa MG`
5. Escolha username: `financas_casa_mg_bot` (ou outro disponível)
6. **COPIE O TOKEN** (exemplo: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2️⃣ Configurar Google Sheets API (5 minutos)

1. Acesse: https://console.cloud.google.com/
2. Crie novo projeto: "Financas Casa MG"
3. Ative a API:
   - Menu → "APIs e Serviços" → "Biblioteca"
   - Procure "Google Sheets API"
   - Clique "Ativar"

4. Criar credenciais:
   - "Credenciais" → "Criar credenciais" → "Conta de serviço"
   - Nome: `bot-telegram`
   - Clique "Criar e continuar"
   - Role: "Editor"
   - Clique "Concluir"

5. Baixar JSON:
   - Clique na conta criada
   - Aba "Chaves" → "Adicionar chave" → "Criar nova chave" → "JSON"
   - **BAIXE O ARQUIVO**

6. Compartilhar planilha:
   - Copie o email da service account (está no JSON: `client_email`)
   - Abra sua planilha Google Sheets
   - Clique "Compartilhar"
   - Cole o email
   - Permissão: "Editor"
   - Clique "Enviar"

### 3️⃣ Deploy no Railway (3 minutos)

#### Opção A: Com GitHub (Recomendado)

1. **Criar repositório:**
   - Vá em https://github.com/new
   - Nome: `financas-casa-mg-bot`
   - Clique "Create repository"

2. **Fazer upload dos arquivos:**
   - Baixe todos os arquivos deste bot
   - Na página do repositório, clique "uploading an existing file"
   - Arraste todos os arquivos (bot.py, requirements.txt, etc.)
   - Clique "Commit changes"

3. **Deploy no Railway:**
   - Acesse: https://railway.app/
   - Login com GitHub
   - "New Project" → "Deploy from GitHub repo"
   - Selecione `financas-casa-mg-bot`
   - Aguarde o build

4. **Configurar variáveis:**
   - Clique no projeto
   - Aba "Variables"
   - Clique "New Variable"
   
   **Variável 1:**
   ```
   Nome: TELEGRAM_BOT_TOKEN
   Valor: [cole o token do BotFather]
   ```
   
   **Variável 2:**
   ```
   Nome: GOOGLE_CREDENTIALS_JSON
   Valor: [cole TODO O CONTEÚDO do arquivo JSON em UMA LINHA]
   ```
   
   💡 **Dica:** Abra o JSON no bloco de notas, copie tudo e cole

5. **Aguarde reiniciar:**
   - Railway reiniciará automaticamente
   - Veja os logs para confirmar: "🚀 Bot iniciado!"

#### Opção B: Sem GitHub (Direto)

1. **Preparar arquivos:**
   - Baixe todos os arquivos do bot
   - Crie uma pasta `financas-casa-mg-bot`
   - Coloque todos os arquivos dentro

2. **Instalar Railway CLI:**
   ```bash
   npm i -g @railway/cli
   ```

3. **Deploy:**
   ```bash
   cd financas-casa-mg-bot
   railway login
   railway init
   railway up
   ```

4. **Adicionar variáveis:**
   ```bash
   railway variables set TELEGRAM_BOT_TOKEN="seu_token_aqui"
   railway variables set GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}'
   ```

### 4️⃣ Testar (1 minuto)

1. Abra o Telegram
2. Procure seu bot (username que você escolheu)
3. Envie: `/start`
4. Se responder → **FUNCIONANDO!** ✅

### 5️⃣ Adicionar ao Grupo

1. No Telegram, abra seu grupo
2. Clique no nome do grupo → "Adicionar membros"
3. Procure o bot e adicione
4. Teste: "Gastei R$10 com teste"
5. Deve responder com confirmação! ✅

---

## 🆘 Problemas Comuns

**❌ Bot não responde:**
- Verifique o token no Railway (Variables)
- Veja os logs: railway.app → seu projeto → "Logs"

**❌ Erro ao acessar planilha:**
- Confirme que compartilhou a planilha com o email da service account
- Verifique se o JSON está correto (sem quebras de linha extras)

**❌ Erro no deploy:**
- Confirme que todos os arquivos foram enviados
- Verifique se `requirements.txt` e `Procfile` existem

---

## 📞 Precisa de Ajuda?

1. Verifique os logs no Railway
2. Teste o bot localmente: `python bot.py`
3. Confirme as variáveis de ambiente

**Pronto! Seu bot está funcionando 24/7 no Railway! 🎉**

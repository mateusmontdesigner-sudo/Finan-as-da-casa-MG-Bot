#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Finanças Casa MG - Bot do Telegram
Assistente financeiro para gestão de gastos compartilhados
"""

import os
import re
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configurações
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SPREADSHEET_ID = '1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE'

# Mapeamento de usuários (Telegram username/first_name -> Nome na planilha)
USER_MAPPING = {
    'mateus': 'Mateus',
    'cristhian': 'Cristhian',
    'marcelo': 'Marcelo',
    'eli': 'Eli'
}

# Categorias que são divididas por 4 pessoas (incluindo Eli)
CATEGORIAS_COM_ELI = ['água', 'agua', 'luz']


class SheetsManager:
    """Gerenciador de interações com Google Sheets"""
    
    def __init__(self):
        self.client = None
        self.sheet = None
        self.setup_sheets()
    
    def setup_sheets(self):
        """Configura conexão com Google Sheets"""
        try:
            # Usa credenciais de variável de ambiente
            creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
            if creds_json:
                import json
                creds_dict = json.loads(creds_json)
                scope = ['https://www.googleapis.com/auth/spreadsheets']
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
                self.client = gspread.authorize(creds)
                self.sheet = self.client.open_by_key(SPREADSHEET_ID).sheet1
                logger.info("✅ Conectado ao Google Sheets")
            else:
                logger.warning("⚠️ GOOGLE_CREDENTIALS_JSON não configurado")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar Google Sheets: {e}")
    
    def add_expense(self, data, quem_pagou, descricao, categoria, valor, divisao, quem_repassa, valor_pessoa):
        """Adiciona um novo gasto na planilha"""
        try:
            if not self.sheet:
                return False
            
            # Encontra a primeira linha vazia
            values = self.sheet.get_all_values()
            next_row = len(values) + 1
            
            # Formata a data
            data_formatada = data.strftime('%d/%m/%Y')
            
            # Adiciona a linha
            row_data = [
                data_formatada,
                quem_pagou,
                descricao,
                categoria,
                valor,
                divisao,
                quem_repassa,
                f'=E{next_row}/F{next_row}',  # Fórmula para valor por pessoa
                '',  # Quitações (vazio)
                ''   # Total do mês (vazio)
            ]
            
            self.sheet.append_row(row_data, value_input_option='USER_ENTERED')
            logger.info(f"✅ Gasto adicionado: {quem_pagou} - {descricao} - R$ {valor}")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao adicionar gasto: {e}")
            return False
    
    def get_summary(self):
        """Retorna resumo dos gastos do mês"""
        try:
            if not self.sheet:
                return None
            
            values = self.sheet.get_all_values()
            if len(values) <= 1:
                return {'total': 0, 'por_pessoa': {}}
            
            # Pula cabeçalho
            data_rows = values[1:]
            
            totais = {
                'Mateus': 0,
                'Cristhian': 0,
                'Marcelo': 0,
                'Eli': 0
            }
            
            total_geral = 0
            
            for row in data_rows:
                if len(row) < 5:
                    continue
                
                quem_pagou = row[1]
                valor_str = row[4]
                
                # Remove formatação e converte
                if valor_str:
                    valor = float(valor_str.replace('R$', '').replace('.', '').replace(',', '.').strip())
                    
                    # Adiciona ao total da pessoa
                    if quem_pagou in totais:
                        totais[quem_pagou] += valor
                    elif ', ' in quem_pagou:  # Pagamento compartilhado
                        pagadores = quem_pagou.split(', ')
                        valor_cada = valor / len(pagadores)
                        for pagador in pagadores:
                            if pagador in totais:
                                totais[pagador] += valor_cada
                    
                    total_geral += valor
            
            return {
                'total': total_geral,
                'por_pessoa': totais
            }
        except Exception as e:
            logger.error(f"❌ Erro ao gerar resumo: {e}")
            return None


# Instância do gerenciador de planilhas
sheets = SheetsManager()


def identify_user(update: Update) -> str:
    """Identifica o usuário a partir da mensagem do Telegram"""
    user = update.effective_user
    
    # Tenta pelo username
    if user.username:
        username_lower = user.username.lower()
        for key, name in USER_MAPPING.items():
            if key in username_lower:
                return name
    
    # Tenta pelo first_name
    if user.first_name:
        first_name_lower = user.first_name.lower()
        for key, name in USER_MAPPING.items():
            if key in first_name_lower:
                return name
    
    # Se não encontrar, retorna o first_name
    return user.first_name or "Usuário"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Boas-vindas"""
    message = """👋 Olá! Sou o **Finanças Casa MG**!

🏠💰 Estou aqui para gerenciar os gastos da casa.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 **COMANDOS DISPONÍVEIS:**

💰 **Registrar gasto:**
   "Gastei R$150 com mercado"
   "Paguei R$80 de luz"

📊 **Ver resumo:**
   /resumo

💸 **Calcular acerto:**
   /acerto

📜 **Ver histórico:**
   /historico

❓ **Ajuda:**
   /ajuda

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 **Planilha:**
https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit

Pronto para começar! 🚀"""
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajuda - Instruções"""
    message = """📋 **COMO USAR O BOT:**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 **REGISTRAR GASTOS:**

Exemplos:
• "Gastei R$150 com mercado"
• "Paguei R$80 de luz"
• "R$45 de limpeza"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 **COMANDOS:**

/resumo - Ver quanto cada um pagou
/acerto - Calcular quem deve pra quem
/historico - Listar todos os gastos
/ajuda - Ver esta mensagem

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ **REGRAS DE DIVISÃO:**

🏠 **Gastos gerais** (mercado, limpeza, gás):
   → Divididos entre Mateus, Cristhian e Marcelo

💡 **Água e Luz:**
   → Divididos entre 4 pessoas (vocês 3 + Eli)
   → Eli paga antecipado, vocês repassam

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /resumo - Mostra resumo do mês"""
    summary = sheets.get_summary()
    
    if not summary:
        await update.message.reply_text("❌ Erro ao acessar a planilha.")
        return
    
    message = f"""📊 **RESUMO DO MÊS**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 **TOTAL GERAL:** R$ {summary['total']:.2f}

👥 **TOTAL PAGO POR CADA UM:**
"""
    
    for pessoa, valor in summary['por_pessoa'].items():
        if valor > 0:
            message += f"   • {pessoa}: R$ {valor:.2f}\n"
    
    message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Ver detalhes na planilha:
https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit"""
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def acerto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /acerto - Calcula quem deve pra quem"""
    await update.message.reply_text(
        "💸 **CÁLCULO DE ACERTO**\n\n"
        "Esta funcionalidade calcula automaticamente quem deve pagar quanto para quem.\n\n"
        "🔧 Em desenvolvimento... Por enquanto, consulte a aba de resumo na planilha:\n"
        "https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit",
        parse_mode='Markdown'
    )


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /historico - Lista todos os gastos"""
    await update.message.reply_text(
        "📜 **HISTÓRICO DE GASTOS**\n\n"
        "Veja todos os gastos registrados na planilha:\n"
        "https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit",
        parse_mode='Markdown'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto (registro de gastos)"""
    text = update.message.text
    user_name = identify_user(update)
    
    # Pattern para detectar gastos: "Gastei R$100 com mercado"
    patterns = [
        r'gastei\s+r\$?\s*(\d+(?:,\d{2})?)\s+(?:com|de|em)\s+(.+)',
        r'paguei\s+r\$?\s*(\d+(?:,\d{2})?)\s+(?:de|da|do)\s+(.+)',
        r'r\$?\s*(\d+(?:,\d{2})?)\s+(?:de|da|do|com|em)\s+(.+)',
        r'registrar:?\s*(.+?)\s*-?\s*r\$?\s*(\d+(?:,\d{2})?)',
    ]
    
    matched = False
    for i, pattern in enumerate(patterns):
        match = re.search(pattern, text.lower())
        if match:
            matched = True
            
            # Extrai valor e descrição
            if i == 3:  # Último pattern tem ordem invertida
                descricao = match.group(1).strip().title()
                valor_str = match.group(2)
            else:
                valor_str = match.group(1)
                descricao = match.group(2).strip().title()
            
            # Converte valor
            valor = float(valor_str.replace(',', '.'))
            
            # Identifica categoria
            descricao_lower = descricao.lower()
            if 'mercado' in descricao_lower or 'supermercado' in descricao_lower:
                categoria = 'Supermercado'
            elif 'aluguel' in descricao_lower:
                categoria = 'Aluguel'
            elif 'água' in descricao_lower or 'agua' in descricao_lower:
                categoria = 'Água'
            elif 'luz' in descricao_lower or 'energia' in descricao_lower:
                categoria = 'Luz'
            elif 'internet' in descricao_lower or 'wifi' in descricao_lower:
                categoria = 'Internet'
            elif 'gás' in descricao_lower or 'gas' in descricao_lower:
                categoria = 'Gás'
            elif 'limpeza' in descricao_lower:
                categoria = 'Limpeza'
            else:
                categoria = 'Outros'
            
            # Determina divisão
            if categoria.lower() in CATEGORIAS_COM_ELI:
                divisao = 4
                quem_repassa = 'Mateus, Marcelo, Cristhian'
            else:
                divisao = 3
                # Remove o pagador da lista de quem repassa
                todos = ['Mateus', 'Cristhian', 'Marcelo']
                quem_repassa = ', '.join([p for p in todos if p != user_name])
            
            valor_pessoa = valor / divisao
            
            # Mensagem de confirmação
            confirm_msg = f"""✅ **GASTO REGISTRADO!**

👤 **Quem pagou:** {user_name}
📝 **Descrição:** {descricao}
🏷️ **Categoria:** {categoria}
💰 **Valor Total:** R$ {valor:.2f}
👥 **Divisão:** {divisao} pessoas
💵 **Valor por pessoa:** R$ {valor_pessoa:.2f}
🔄 **Quem irá repassar:** {quem_repassa}
📅 **Data:** {datetime.now().strftime('%d/%m/%Y')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Planilha atualizada!"""
            
            # Adiciona na planilha
            success = sheets.add_expense(
                datetime.now(),
                user_name,
                descricao,
                categoria,
                valor,
                divisao,
                quem_repassa,
                valor_pessoa
            )
            
            if success:
                await update.message.reply_text(confirm_msg, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    "❌ Erro ao registrar na planilha. Tente novamente ou registre manualmente."
                )
            
            break
    
    if not matched:
        # Mensagem não reconhecida - não responde para não poluir o grupo
        pass


def main():
    """Função principal - inicia o bot"""
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN não configurado!")
        return
    
    # Cria a aplicação
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Registra handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ajuda", ajuda))
    application.add_handler(CommandHandler("help", ajuda))
    application.add_handler(CommandHandler("resumo", resumo))
    application.add_handler(CommandHandler("acerto", acerto))
    application.add_handler(CommandHandler("historico", historico))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Inicia o bot
    logger.info("🚀 Bot iniciado!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

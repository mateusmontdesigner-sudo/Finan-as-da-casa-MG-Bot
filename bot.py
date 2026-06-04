#!/usr/bin/env python3
# -<b>- coding: utf-8 -</b>-
"""
Finanças Casa MG - Bot do Telegram
"""

import os
import re
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SPREADSHEET_ID = '1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE'
# Link fixo — evita que o Telegram quebre a URL com underscores do Markdown
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit'

MESES_PT = {
    1: 'JANEIRO', 2: 'FEVEREIRO', 3: 'MARÇO', 4: 'ABRIL',
    5: 'MAIO', 6: 'JUNHO', 7: 'JULHO', 8: 'AGOSTO',
    9: 'SETEMBRO', 10: 'OUTUBRO', 11: 'NOVEMBRO', 12: 'DEZEMBRO'
}

USER_MAPPING = {
    'mateus': 'Mateus',
    'cristhian': 'Cristhian',
    'marcelo': 'Marcelo',
    'eli': 'Eli'
}

# Divisão por 4 (inclui Eli)
CATEGORIAS_COM_ELI = ['água', 'agua', 'luz', 'energia']

# Divisão por 2
CATEGORIAS_2_PESSOAS = ['gastos gata', 'gata']

CATEGORIA_MAP = {
    'mercado': 'Supermercado', 'supermercado': 'Supermercado',
    'aluguel': 'Aluguel',
    'água': 'Água', 'agua': 'Água',
    'luz': 'Luz', 'energia': 'Luz',
    'internet': 'Internet', 'wifi': 'Internet',
    'gás': 'Gás', 'gas': 'Gás',
    'limpeza': 'Limpeza',
    'açougue': 'Açougue', 'acougue': 'Açougue', 'carne': 'Açougue',
    'sacolão': 'Sacolão', 'sacalao': 'Sacolão', 'feira': 'Sacolão',
    'padaria': 'Padaria', 'pão': 'Padaria',
    'lanches': 'Lanches', 'lanche': 'Lanches',
    'gata': 'Gastos Gata', 'veterinário': 'Gastos Gata',
    'condução': 'Condução', 'uber': 'Condução', 'ônibus': 'Condução',
    'rolê': 'Rolê', 'role': 'Rolê', 'passeio': 'Rolê',
    'adobe': 'Pacote Adobe',
    'nubank': 'Fatura Nubank',
    'santander': 'Fatura Santander',
    'bradesco': 'Fatura Bradesco',
    'moto': 'Gastos Moto',
    'investimento': 'Investimento',
    'caixinha': 'Caixinha',
    'família': 'Família', 'familia': 'Família',
}


class SheetsManager:
    def __init__(self):
        self.client = None
        self.spreadsheet = None
        self._connect()

    def _connect(self):
        try:
            creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
            if not creds_json:
                logger.error("GOOGLE_CREDENTIALS_JSON não configurado")
                return
            creds_dict = json.loads(creds_json)
            scope = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(SPREADSHEET_ID)
            logger.info("✅ Conectado ao Google Sheets")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar: {e}")

    def _get_or_create_sheet(self, nome_aba):
        """Pega a aba do mês atual, cria se não existir"""
        try:
            return self.spreadsheet.worksheet(nome_aba)
        except gspread.WorksheetNotFound:
            # Cria a aba com cabeçalho
            ws = self.spreadsheet.add_worksheet(title=nome_aba, rows=100, cols=10)
            ws.append_row([
                'Data', 'Quem Pagou', 'Descrição', 'Categoria',
                'Valor Total', 'Divisão', 'Quem irá Repassar',
                'Valor por Pessoa', 'Quitações', 'TOTAL DO MÊS'
            ])
            return ws

    def add_expense(self, quem_pagou, descricao, categoria, valor, divisao, quem_repassa):
        try:
            if not self.spreadsheet:
                self._connect()
            if not self.spreadsheet:
                return False

            now = datetime.now()
            nome_aba = MESES_PT[now.month]
            ws = self._get_or_create_sheet(nome_aba)

            data_fmt = now.strftime('%d/%m/%Y')
            valor_pessoa = valor / divisao
            next_row = len(ws.get_all_values()) + 1

            ws.append_row([
                data_fmt,
                quem_pagou,
                descricao,
                categoria,
                f'R$ {valor:.2f}'.replace('.', ','),
                divisao,
                quem_repassa,
                f'R$ {valor_pessoa:.2f}'.replace('.', ','),
                '',
                ''
            ])
            logger.info(f"✅ Registrado: {quem_pagou} - {descricao} - R${valor:.2f}")
            return True, valor_pessoa
        except Exception as e:
            logger.error(f"❌ Erro ao registrar: {e}")
            return False, 0

    def get_summary(self):
        """Resumo da aba do mês atual"""
        try:
            if not self.spreadsheet:
                self._connect()
            nome_aba = MESES_PT[datetime.now().month]
            try:
                ws = self.spreadsheet.worksheet(nome_aba)
            except gspread.WorksheetNotFound:
                return None

            rows = ws.get_all_values()
            if len(rows) <= 1:
                return {'mes': nome_aba, 'gastos': [], 'total': 0, 'por_pessoa': {}}

            totais = {'Mateus': 0, 'Cristhian': 0, 'Marcelo': 0, 'Eli': 0}
            gastos = []
            total = 0

            for row in rows[1:]:
                if len(row) < 5 or not row[4]:
                    continue
                val_str = row[4].replace('R$', '').replace('.', '').replace(',', '.').strip()
                try:
                    val = float(val_str)
                except:
                    continue

                pagador = row[1]
                descr = row[2] or row[3]
                gastos.append({'pagador': pagador, 'descricao': descr, 'valor': val})
                total += val

                # Acumula por pessoa
                pagadores = [p.strip() for p in pagador.split(',')]
                val_cada = val / len(pagadores)
                for p in pagadores:
                    if p in totais:
                        totais[p] += val_cada

            return {
                'mes': nome_aba,
                'gastos': gastos[-10:],  # últimos 10
                'total': total,
                'por_pessoa': {k: v for k, v in totais.items() if v > 0}
            }
        except Exception as e:
            logger.error(f"❌ Erro no resumo: {e}")
            return None

    def get_acerto(self):
        """Calcula quem deve pra quem no mês atual"""
        try:
            summary = self.get_summary()
            if not summary:
                return None

            nome_aba = MESES_PT[datetime.now().month]
            ws = self.spreadsheet.worksheet(nome_aba)
            rows = ws.get_all_values()

            # Calcula quanto cada um DEVE (soma do que foi dividido com ele)
            deve = {'Mateus': 0, 'Cristhian': 0, 'Marcelo': 0, 'Eli': 0}

            for row in rows[1:]:
                if len(row) < 8 or not row[4]:
                    continue
                val_str = row[4].replace('R$', '').replace('.', '').replace(',', '.').strip()
                try:
                    val = float(val_str)
                except:
                    continue

                divisao = int(row[5]) if row[5].isdigit() else 3
                quem_repassa = [p.strip() for p in row[6].split(',') if p.strip()]
                pagador = row[1].strip()
                val_pessoa = val / divisao

                # Quem repassa deve ao pagador
                for pessoa in quem_repassa:
                    if pessoa in deve:
                        deve[pessoa] += val_pessoa

            return {'mes': nome_aba, 'deve': deve}
        except Exception as e:
            logger.error(f"❌ Erro no acerto: {e}")
            return None


sheets = SheetsManager()


def identify_user(update: Update) -> str:
    user = update.effective_user
    for attr in [user.username, user.first_name]:
        if attr:
            for key, name in USER_MAPPING.items():
                if key in attr.lower():
                    return name
    return user.first_name or "Usuário"


def parse_valor(valor_str: str) -> float:
    """Converte string de valor para float"""
    return float(valor_str.replace('.', '').replace(',', '.'))


def detectar_gasto(text: str):
    """Tenta extrair valor e descrição do texto"""
    patterns = [
        r'gastei\s+r?\$?\s*([\d.,]+)\s+(?:com|de|em|no|na)\s+(.+)',
        r'paguei\s+r?\$?\s*([\d.,]+)\s+(?:de|da|do|com|no|na)\s+(.+)',
        r'comprei\s+(.+?)\s+(?:por|de)\s+r?\$?\s*([\d.,]+)',
        r'r?\$\s*([\d.,]+)\s+(?:de|da|do|com|em|no|na)\s+(.+)',
        r'([\d.,]+)\s+(?:reais?|rs?)\s+(?:de|da|do|com)\s+(.+)',
    ]
    for i, p in enumerate(patterns):
        m = re.search(p, text.lower())
        if m:
            if i == 2:  # "comprei X por Y"
                return parse_valor(m.group(2)), m.group(1).strip().title()
            else:
                return parse_valor(m.group(1)), m.group(2).strip().title()
    return None, None


def detectar_categoria(descricao: str):
    desc_lower = descricao.lower()
    for key, cat in CATEGORIA_MAP.items():
        if key in desc_lower:
            return cat
    return 'Outros'


def calcular_divisao(categoria: str, quem_pagou: str):
    cat_lower = categoria.lower()
    desc_lower = categoria.lower()

    if any(c in cat_lower for c in ['água', 'agua', 'luz', 'energia']):
        divisao = 4
        todos = ['Mateus', 'Cristhian', 'Marcelo', 'Eli']
    elif any(c in desc_lower for c in ['gata', 'veterinário']):
        divisao = 2
        todos = ['Mateus', 'Cristhian']
    else:
        divisao = 3
        todos = ['Mateus', 'Cristhian', 'Marcelo']

    pagadores = [p.strip() for p in quem_pagou.split(',')]
    quem_repassa = [p for p in todos if p not in pagadores]
    return divisao, ', '.join(quem_repassa)


# ─── HANDLERS ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = identify_user(update)
    msg = f"""👋 Olá, <b>{nome}</b>! Sou o <b>Finanças Casa MG</b> 🏠💰

━━━━━━━━━━━━━━━━━━━━━━━
📋 <b>COMO REGISTRAR GASTOS:</b>

• "Gastei R$150 com mercado"
• "Paguei R$80 de luz"
• "Comprei carne por R$45"
• "R$120 de supermercado"

📊 <b>COMANDOS:</b>
/resumo — gastos do mês
/acerto — quem deve pra quem
/historico — últimos registros
/ajuda — instruções

━━━━━━━━━━━━━━━━━━━━━━━
📊 <a href="{SHEET_URL}">Abrir Planilha</a>"""
    await update.message.reply_text(msg, parse_mode='HTML')


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """📋 <b>COMO USAR O BOT</b>

━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>Registrar gasto:</b>
• "Gastei R$150 com mercado"
• "Paguei R$80 de luz"
• "R$45 de açougue"

⚡ <b>Regras de divisão:</b>
🏠 Gastos gerais → ÷ 3 (Mateus, Cristhian, Marcelo)
💧 Água e Luz → ÷ 4 (+ Eli)
🐱 Gastos Gata → ÷ 2 (Mateus, Cristhian)

📊 <b>Comandos:</b>
/resumo — total do mês por pessoa
/acerto — quanto cada um deve
/historico — últimos lançamentos
━━━━━━━━━━━━━━━━━━━━━━━"""
    await update.message.reply_text(msg, parse_mode='HTML')


async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Consultando planilha...")
    data = sheets.get_summary()

    if not data:
        await update.message.reply_text("❌ Não encontrei dados para este mês. Pode ser que a aba ainda não exista.")
        return

    msg = f"📊 <b>RESUMO — {data['mes']}</b>\n\n"
    msg += f"💰 <b>Total geral: R$ {data['total']:.2f}</b>\n\n"
    msg += "👥 <b>Pago por cada um:</b>\n"
    for pessoa, val in data['por_pessoa'].items():
        msg += f"   • {pessoa}: R$ {val:.2f}\n"

    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def acerto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Calculando acerto...")
    data = sheets.get_acerto()

    if not data:
        await update.message.reply_text("❌ Não foi possível calcular o acerto.")
        return

    msg = f"💸 <b>ACERTO — {data['mes']}</b>\n\n"
    msg += "Valor que cada um ainda precisa repassar:\n\n"
    for pessoa, val in data['deve'].items():
        if val > 0:
            msg += f"   • {pessoa}: R$ {val:.2f}\n"

    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Buscando histórico...")
    data = sheets.get_summary()

    if not data or not data['gastos']:
        await update.message.reply_text("❌ Nenhum gasto encontrado neste mês.")
        return

    msg = f"📜 <b>ÚLTIMOS GASTOS — {data['mes']}</b>\n\n"
    for g in reversed(data['gastos']):
        msg += f"• {g['pagador']}: {g['descricao']} — R$ {g['valor']:.2f}\n"

    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_name = identify_user(update)

    valor, descricao = detectar_gasto(text)

    if valor is None or valor <= 0:
        return  # Ignora mensagens que não são gastos

    categoria = detectar_categoria(descricao)
    divisao, quem_repassa = calcular_divisao(categoria, user_name)
    valor_pessoa = valor / divisao

    success, vp = sheets.add_expense(
        user_name, descricao, categoria, valor, divisao, quem_repassa
    )

    if success:
        msg = f"""✅ <b>GASTO REGISTRADO!</b>

👤 <b>Pago por:</b> {user_name}
📝 <b>Descrição:</b> {descricao}
🏷️ <b>Categoria:</b> {categoria}
💰 <b>Total:</b> R$ {valor:.2f}
👥 <b>Divisão:</b> {divisao} pessoas → R$ {vp:.2f} cada
🔄 <b>Repassar:</b> {quem_repassa}
📅 <b>Data:</b> {datetime.now().strftime('%d/%m/%Y')}

📊 <a href="{SHEET_URL}">Ver na planilha</a>"""
        await update.message.reply_text(msg, parse_mode='HTML')
    else:
        await update.message.reply_text(
            "❌ Erro ao registrar na planilha.\n\n"
            "Verifique se a conta de serviço tem acesso à planilha:\n"
            "Planilha → Compartilhar → adicione o e-mail do JSON com permissão de Editor."
        )


def main():
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN não configurado!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("help", ajuda))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("acerto", acerto))
    app.add_handler(CommandHandler("historico", historico))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Bot iniciado!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Finanças Casa MG - Bot do Telegram
"""

import os
import re
import json
import logging
import unicodedata
import anthropic
from datetime import datetime, date
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
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
SPREADSHEET_ID = '1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE'
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit'

MESES_PT = {
    1: 'JANEIRO', 2: 'FEVEREIRO', 3: 'MARÇO', 4: 'ABRIL',
    5: 'MAIO', 6: 'JUNHO', 7: 'JULHO', 8: 'AGOSTO',
    9: 'SETEMBRO', 10: 'OUTUBRO', 11: 'NOVEMBRO', 12: 'DEZEMBRO'
}

USER_MAPPING = {
    'mateus': 'Mateus', 'cristhian': 'Cristhian',
    'marcelo': 'Marcelo', 'eli': 'Eli'
}

CATEGORIAS_COM_ELI = ['água', 'agua', 'luz', 'energia']
CATEGORIAS_2_PESSOAS = ['gastos gata', 'gata']

CATEGORIA_MAP = {
    'mercado': 'Supermercado', 'supermercado': 'Supermercado',
    'aluguel': 'Aluguel', 'água': 'Água', 'agua': 'Água',
    'luz': 'Luz', 'energia': 'Luz', 'internet': 'Internet', 'wifi': 'Internet',
    'gás': 'Gás', 'gas': 'Gás', 'limpeza': 'Limpeza',
    'açougue': 'Açougue', 'acougue': 'Açougue', 'carne': 'Açougue',
    'sacolão': 'Sacolão', 'sacalao': 'Sacolão', 'feira': 'Sacolão',
    'padaria': 'Padaria', 'pão': 'Padaria', 'lanches': 'Lanches', 'lanche': 'Lanches',
    'gata': 'Gastos Gata', 'veterinário': 'Gastos Gata',
    'condução': 'Condução', 'uber': 'Condução', 'ônibus': 'Condução',
    'rolê': 'Rolê', 'role': 'Rolê', 'passeio': 'Rolê',
    'adobe': 'Pacote Adobe', 'nubank': 'Fatura Nubank',
    'santander': 'Fatura Santander', 'bradesco': 'Fatura Bradesco',
    'moto': 'Gastos Moto', 'investimento': 'Investimento',
    'caixinha': 'Caixinha', 'família': 'Família', 'familia': 'Família',
}


def normalizar(texto):
    """Remove acentos e coloca em maiúsculo"""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto.upper())
        if unicodedata.category(c) != 'Mn'
    ).replace('MARCO', 'MARÇO')


def parse_data(data_str):
    """Converte dd/mm/yyyy para objeto date, retorna None se inválido"""
    try:
        return datetime.strptime(data_str.strip(), '%d/%m/%Y').date()
    except:
        return None


def parse_valor(valor_str):
    try:
        return float(valor_str.replace('R$', '').replace('.', '').replace(',', '.').strip())
    except:
        return 0.0


# ─── SHEETS MANAGER ──────────────────────────────────────────

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
        try:
            return self.spreadsheet.worksheet(nome_aba)
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(title=nome_aba, rows=100, cols=10)
            ws.append_row([
                'Data', 'Quem Pagou', 'Descrição', 'Categoria',
                'Valor Total', 'Divisão', 'Quem irá Repassar',
                'Valor por Pessoa', 'Quitações', 'TOTAL DO MÊS'
            ])
            return ws

    def listar_abas(self):
        try:
            if not self.spreadsheet:
                self._connect()
            abas = [ws.title for ws in self.spreadsheet.worksheets()]
            return [a for a in abas if a.upper() in MESES_PT.values()]
        except Exception as e:
            logger.error(f"❌ Erro ao listar abas: {e}")
            return []

    def get_rows(self, nome_aba):
        """Retorna todas as linhas de uma aba como lista de dicts"""
        try:
            if not self.spreadsheet:
                self._connect()
            ws = self.spreadsheet.worksheet(nome_aba)
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            result = []
            for row in rows[1:]:
                while len(row) < 10:
                    row.append('')
                result.append({
                    'data_str': row[0],
                    'data':     parse_data(row[0]),
                    'pagador':  row[1].strip(),
                    'descricao': row[2].strip() or row[3].strip(),
                    'categoria': row[3].strip(),
                    'valor':    parse_valor(row[4]),
                    'divisao':  int(row[5]) if row[5].isdigit() else 3,
                    'repassa':  [p.strip() for p in row[6].split(',') if p.strip()],
                    'val_pessoa': parse_valor(row[7]),
                    'quitacao': row[8].strip().lower(),
                })
            return [r for r in result if r['valor'] > 0]
        except gspread.WorksheetNotFound:
            return None
        except Exception as e:
            logger.error(f"❌ Erro ao ler aba {nome_aba}: {e}")
            return None

    def add_expense(self, quem_pagou, descricao, categoria, valor, divisao, quem_repassa):
        try:
            if not self.spreadsheet:
                self._connect()
            now = datetime.now()
            nome_aba = MESES_PT[now.month]
            ws = self._get_or_create_sheet(nome_aba)
            valor_pessoa = valor / divisao
            ws.append_row([
                now.strftime('%d/%m/%Y'), quem_pagou, descricao, categoria,
                f'R$ {valor:.2f}'.replace('.', ','), divisao, quem_repassa,
                f'R$ {valor_pessoa:.2f}'.replace('.', ','), '', ''
            ])
            logger.info(f"✅ Registrado: {quem_pagou} - {descricao} - R${valor:.2f}")
            return True, valor_pessoa
        except Exception as e:
            logger.error(f"❌ Erro ao registrar: {e}")
            return False, 0

    def get_summary(self, nome_aba=None):
        if not nome_aba:
            nome_aba = MESES_PT[datetime.now().month]
        rows = self.get_rows(nome_aba)
        if rows is None:
            return None
        totais = {'Mateus': 0, 'Cristhian': 0, 'Marcelo': 0, 'Eli': 0}
        total = 0
        for r in rows:
            total += r['valor']
            pagadores = [p.strip() for p in r['pagador'].split(',')]
            for p in pagadores:
                if p in totais:
                    totais[p] += r['valor'] / len(pagadores)
        return {
            'mes': nome_aba,
            'gastos': rows[-10:],
            'total': total,
            'por_pessoa': {k: v for k, v in totais.items() if v > 0}
        }

    def get_acerto(self, nome_aba=None, data_inicio=None, data_fim=None, apenas_nao_quitados=False):
        """
        Calcula acerto com filtros opcionais:
        - data_inicio / data_fim: objetos date
        - apenas_nao_quitados: ignora linhas marcadas como 'quitado'
        """
        if not nome_aba:
            nome_aba = MESES_PT[datetime.now().month]
        rows = self.get_rows(nome_aba)
        if rows is None:
            return None

        # Aplicar filtros
        filtrados = []
        for r in rows:
            if apenas_nao_quitados and 'quitado' in r['quitacao'] and 'não' not in r['quitacao'] and 'nao' not in r['quitacao']:
                continue
            if data_inicio and r['data'] and r['data'] < data_inicio:
                continue
            if data_fim and r['data'] and r['data'] > data_fim:
                continue
            filtrados.append(r)

        # Calcula débitos: quem repassa → deve ao pagador
        deve = {'Mateus': 0, 'Cristhian': 0, 'Marcelo': 0, 'Eli': 0}
        detalhes = []

        for r in filtrados:
            val_pessoa = r['valor'] / r['divisao']
            for pessoa in r['repassa']:
                if pessoa in deve:
                    deve[pessoa] += val_pessoa
            detalhes.append(r)

        return {
            'mes': nome_aba,
            'deve': {k: v for k, v in deve.items() if v > 0},
            'detalhes': detalhes,
            'filtro_periodo': (data_inicio, data_fim),
            'apenas_nao_quitados': apenas_nao_quitados,
        }

    def get_dados_completos(self):
        """Retorna dados de todas as abas para a IA analisar"""
        abas = self.listar_abas()
        resultado = {}
        for aba in abas:
            rows = self.get_rows(aba)
            if rows:
                resultado[aba] = rows
        return resultado


sheets = SheetsManager()


# ─── HELPERS ─────────────────────────────────────────────────

def identify_user(update: Update) -> str:
    user = update.effective_user
    for attr in [user.username, user.first_name]:
        if attr:
            for key, name in USER_MAPPING.items():
                if key in attr.lower():
                    return name
    return user.first_name or "Usuário"


def resolver_mes(args):
    """Extrai nome de aba de lista de args. Retorna (nome_aba, restante)"""
    if not args:
        return None, []
    candidato = normalizar(args[0])
    if candidato in MESES_PT.values():
        return candidato, args[1:]
    return None, args


def parse_data_arg(texto):
    """Tenta parsear dd/mm ou dd/mm/yyyy do texto"""
    m = re.match(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', texto.strip())
    if m:
        dia, mes, ano = m.group(1), m.group(2), m.group(3) or str(datetime.now().year)
        try:
            return date(int(ano), int(mes), int(dia))
        except:
            return None
    return None


def detectar_gasto(text: str):
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
            if i == 2:
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
    if any(c in cat_lower for c in ['água', 'agua', 'luz', 'energia']):
        divisao, todos = 4, ['Mateus', 'Cristhian', 'Marcelo', 'Eli']
    elif any(c in cat_lower for c in ['gata', 'veterinário']):
        divisao, todos = 2, ['Mateus', 'Cristhian']
    else:
        divisao, todos = 3, ['Mateus', 'Cristhian', 'Marcelo']
    pagadores = [p.strip() for p in quem_pagou.split(',')]
    quem_repassa = [p for p in todos if p not in pagadores]
    return divisao, ', '.join(quem_repassa)


def chamar_claude(pergunta: str, dados: dict) -> str:
    """Chama a API do Claude para responder perguntas sobre a planilha"""
    if not ANTHROPIC_API_KEY:
        return "❌ IA não configurada. Adicione a variável ANTHROPIC_API_KEY no Railway."

    # Formatar dados para o contexto
    contexto = "Dados da planilha Finanças Casa MG:\n\n"
    for mes, rows in dados.items():
        contexto += f"=== {mes} ===\n"
        for r in rows:
            quitado = r['quitacao'] or 'não informado'
            contexto += (
                f"  {r['data_str'] or 'sem data'} | {r['pagador']} pagou R${r['valor']:.2f} "
                f"de {r['descricao'] or r['categoria']} | dividido por {r['divisao']} | "
                f"repassa: {', '.join(r['repassa'])} | quitação: {quitado}\n"
            )
        contexto += "\n"

    system_prompt = (
        "Você é o assistente financeiro do grupo 'Finanças Casa MG'. "
        "Os moradores são Mateus, Cristhian, Marcelo e Eli (Eli só divide água e luz). "
        "Responda de forma direta, clara e em português. "
        "Use os dados fornecidos para calcular e responder com precisão. "
        "Formate valores como R$ X,XX. Seja conciso mas completo."
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"{contexto}\n\nPergunta: {pergunta}"}
            ]
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"❌ Erro na API Claude: {e}")
        return f"❌ Erro ao consultar a IA: {str(e)}"


# ─── HANDLERS ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = identify_user(update)
    msg = f"""👋 Olá, <b>{nome}</b>! Sou o <b>Finanças Casa MG</b> 🏠💰

━━━━━━━━━━━━━━━━━━━━━━━
📋 <b>REGISTRAR GASTOS:</b>
• "Gastei R$150 com mercado"
• "Paguei R$80 de luz"
• "R$45 de açougue"

📊 <b>COMANDOS:</b>
/resumo [mês] — gastos do mês
/acerto [mês] [período] — quem deve pra quem
/historico [mês] — últimos registros
/perguntar — consulte a IA sobre a planilha
/ajuda — instruções completas

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

📊 <b>Resumo:</b>
• /resumo → mês atual
• /resumo MAIO → mês específico

💸 <b>Acerto:</b>
• /acerto → mês atual, todos os gastos
• /acerto MAIO → mês específico
• /acerto MAIO 17/05 31/05 → período específico
• /acerto MAIO nao → só não quitados
• /acerto MAIO 17/05 31/05 nao → período + não quitados

🤖 <b>Perguntar à IA:</b>
• /perguntar qual o total que o Mateus gastou em maio?
• /perguntar quem gastou mais em supermercado?
• /perguntar detalhe dos acertos não quitados de maio

⚡ <b>Regras de divisão:</b>
🏠 Gastos gerais → ÷ 3 (Mateus, Cristhian, Marcelo)
💧 Água e Luz → ÷ 4 (+ Eli)
🐱 Gastos Gata → ÷ 2 (Mateus, Cristhian)
━━━━━━━━━━━━━━━━━━━━━━━"""
    await update.message.reply_text(msg, parse_mode='HTML')


async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome_aba, _ = resolver_mes(context.args)

    await update.message.reply_text("⏳ Consultando planilha...")
    data = sheets.get_summary(nome_aba)

    if not data:
        abas = sheets.listar_abas()
        await update.message.reply_text(
            f"❌ Mês não encontrado.\nDisponíveis: <b>{', '.join(abas)}</b>",
            parse_mode='HTML'
        )
        return

    msg = f"📊 <b>RESUMO — {data['mes']}</b>\n\n"
    msg += f"💰 <b>Total geral: R$ {data['total']:.2f}</b>\n\n"
    msg += "👥 <b>Pago por cada um:</b>\n"
    for pessoa, val in data['por_pessoa'].items():
        msg += f"   • {pessoa}: R$ {val:.2f}\n"
    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def acerto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Uso: /acerto [MES] [dd/mm] [dd/mm] [nao]
    Exemplos:
      /acerto
      /acerto MAIO
      /acerto MAIO 17/05 31/05
      /acerto MAIO nao
      /acerto MAIO 17/05 31/05 nao
    """
    args = list(context.args)
    nome_aba, args = resolver_mes(args)

    # Detectar flags e datas nos args restantes
    data_inicio = None
    data_fim = None
    apenas_nao_quitados = False
    datas_encontradas = []

    for arg in args:
        arg_norm = normalizar(arg)
        if arg_norm in ('NAO', 'NÃO', 'NAOQUITADO', 'NQUITADO', 'N'):
            apenas_nao_quitados = True
        else:
            d = parse_data_arg(arg)
            if d:
                datas_encontradas.append(d)

    if len(datas_encontradas) >= 1:
        data_inicio = datas_encontradas[0]
    if len(datas_encontradas) >= 2:
        data_fim = datas_encontradas[1]

    await update.message.reply_text("⏳ Calculando acerto...")
    data = sheets.get_acerto(nome_aba, data_inicio, data_fim, apenas_nao_quitados)

    if data is None:
        abas = sheets.listar_abas()
        await update.message.reply_text(
            f"❌ Mês não encontrado.\nDisponíveis: <b>{', '.join(abas)}</b>",
            parse_mode='HTML'
        )
        return

    # Cabeçalho com filtros aplicados
    filtro_desc = []
    if data_inicio:
        filtro_desc.append(f"de {data_inicio.strftime('%d/%m')}")
    if data_fim:
        filtro_desc.append(f"até {data_fim.strftime('%d/%m')}")
    if apenas_nao_quitados:
        filtro_desc.append("não quitados")
    filtro_str = f" ({', '.join(filtro_desc)})" if filtro_desc else ""

    msg = f"💸 <b>ACERTO — {data['mes']}{filtro_str}</b>\n\n"

    if not data['deve']:
        msg += "✅ Nenhum valor pendente para esse filtro!"
    else:
        msg += "Valor que cada um precisa repassar:\n\n"
        for pessoa, val in data['deve'].items():
            msg += f"   • <b>{pessoa}:</b> R$ {val:.2f}\n"

        # Detalhamento dos gastos incluídos
        if data['detalhes']:
            msg += f"\n📋 <b>Gastos incluídos ({len(data['detalhes'])}):</b>\n"
            for r in data['detalhes']:
                data_fmt = r['data_str'] or 'sem data'
                msg += f"   {data_fmt} | {r['pagador']} | {r['descricao'] or r['categoria']} | R$ {r['valor']:.2f}\n"

    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome_aba, _ = resolver_mes(context.args)

    await update.message.reply_text("⏳ Buscando histórico...")
    data = sheets.get_summary(nome_aba)

    if not data or not data['gastos']:
        await update.message.reply_text("❌ Nenhum gasto encontrado neste mês.")
        return

    msg = f"📜 <b>ÚLTIMOS GASTOS — {data['mes']}</b>\n\n"
    for g in reversed(data['gastos']):
        msg += f"• {g['pagador']}: {g['descricao']} — R$ {g['valor']:.2f}\n"
    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def perguntar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde perguntas em linguagem natural usando IA"""
    if not context.args:
        await update.message.reply_text(
            "🤖 <b>Como usar:</b>\n"
            "/perguntar qual o total do Mateus em maio?\n"
            "/perguntar quem gastou mais em supermercado?\n"
            "/perguntar detalhe dos não quitados de maio",
            parse_mode='HTML'
        )
        return

    pergunta = ' '.join(context.args)
    await update.message.reply_text("🤖 Consultando a IA, aguarde...")

    dados = sheets.get_dados_completos()
    if not dados:
        await update.message.reply_text("❌ Não consegui acessar a planilha.")
        return

    resposta = chamar_claude(pergunta, dados)
    await update.message.reply_text(f"🤖 {resposta}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_name = identify_user(update)

    valor, descricao = detectar_gasto(text)
    if valor is None or valor <= 0:
        return

    categoria = detectar_categoria(descricao)
    divisao, quem_repassa = calcular_divisao(categoria, user_name)

    success, vp = sheets.add_expense(user_name, descricao, categoria, valor, divisao, quem_repassa)

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
            "❌ Erro ao registrar na planilha.\n"
            "Verifique se a conta de serviço tem acesso à planilha."
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
    app.add_handler(CommandHandler("perguntar", perguntar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Bot iniciado!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

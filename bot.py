#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Finanças Casa MG - Bot do Telegram
Otimizado: regex-first para gastos, keywords para intenções simples,
Groq chamado APENAS quando necessário (uma única chamada unificada).
"""

import os
import re
import json
import logging
import unicodedata
import requests
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
GROQ_API_KEY   = os.getenv('GROQ_API_KEY')
SPREADSHEET_ID = '1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE'
SHEET_URL      = 'https://docs.google.com/spreadsheets/d/1r4krKnW3L_DHp6hAn5uIO_4xJQ0ugGdBNCLpNco7DnE/edit'

MESES_PT = {
    1: 'JANEIRO', 2: 'FEVEREIRO', 3: 'MARÇO',  4: 'ABRIL',
    5: 'MAIO',    6: 'JUNHO',     7: 'JULHO',   8: 'AGOSTO',
    9: 'SETEMBRO',10: 'OUTUBRO', 11: 'NOVEMBRO',12: 'DEZEMBRO'
}
MESES_NOMES = set(MESES_PT.values())

USER_MAPPING = {
    'mateus': 'Mateus', 'cristhian': 'Cristhian',
    'marcelo': 'Marcelo', 'eli': 'Eli'
}
PESSOAS = ['Mateus', 'Cristhian', 'Marcelo', 'Eli']

CATEGORIA_MAP = {
    'mercado': 'Supermercado', 'supermercado': 'Supermercado',
    'aluguel': 'Aluguel', 'agua': 'Água', 'luz': 'Luz', 'energia': 'Luz',
    'internet': 'Internet', 'wifi': 'Internet',
    'gas': 'Gás', 'limpeza': 'Limpeza',
    'acougue': 'Açougue', 'carne': 'Açougue',
    'sacolao': 'Sacolão', 'feira': 'Sacolão',
    'padaria': 'Padaria', 'pao': 'Padaria',
    'lanches': 'Lanches', 'lanche': 'Lanches',
    'gata': 'Gastos Gata', 'veterinario': 'Gastos Gata',
    'conducao': 'Condução', 'uber': 'Condução', 'onibus': 'Condução',
    'role': 'Rolê', 'passeio': 'Rolê',
    'adobe': 'Pacote Adobe', 'nubank': 'Fatura Nubank',
    'santander': 'Fatura Santander', 'bradesco': 'Fatura Bradesco',
    'moto': 'Gastos Moto', 'investimento': 'Investimento',
    'caixinha': 'Caixinha', 'familia': 'Família',
}
# Com acentos (para lookup direto)
CATEGORIA_MAP_ACENTUADO = {
    'água': 'Água', 'gás': 'Gás', 'açougue': 'Açougue', 'sacolão': 'Sacolão',
    'pão': 'Padaria', 'condução': 'Condução', 'rolê': 'Rolê',
    'veterinário': 'Gastos Gata', 'família': 'Família',
}
CATEGORIA_MAP.update(CATEGORIA_MAP_ACENTUADO)

# ── Palavras-chave de intenção (sem precisar de IA) ──────────
_KEYWORDS_ACERTO  = {'acerto', 'deve ', 'devem', 'quem deve', 'quem paga'}
_KEYWORDS_RESUMO  = {'resumo', 'quanto gastamos', 'quanto foi', 'total do mes',
                     'total do mês', 'quanto gastei', 'gasto do mes', 'gasto do mês'}
_KEYWORDS_EXTRATO = {'extrato', 'mostra tudo', 'lista tudo', 'todos os registros', 'ver tudo'}
_KEYWORDS_QUITAR  = {'quitar', 'quita ', 'marca como quitado', 'marcar quitado'}
_KEYWORDS_AJUDA   = {'ajuda', '/help', 'como usar', 'o que voce faz', 'comandos'}

# ── Regex para gastos sem IA ──────────────────────────────────
_REGEX_GASTOS = [
    re.compile(r'gastei\s+r?\$?\s*([\d.,]+)\s+(?:com|de|em|no|na)\s+(.+)',     re.I),
    re.compile(r'paguei\s+r?\$?\s*([\d.,]+)\s+(?:de|da|do|com|no|na)\s+(.+)', re.I),
    re.compile(r'comprei\s+(.+?)\s+(?:por|de)\s+r?\$?\s*([\d.,]+)',            re.I),
    re.compile(r'r?\$\s*([\d.,]+)\s+(?:de|da|do|com|em|no|na)\s+(.+)',         re.I),
    re.compile(r'([\d.,]+)\s+(?:reais?|rs?)\s+(?:de|da|do|com)\s+(.+)',        re.I),
    # "mercado 87,50" ou "açougue 120"
    re.compile(
        r'^(' + '|'.join(re.escape(k) for k in sorted(CATEGORIA_MAP.keys(), key=len, reverse=True))
        + r')\s+([\d.,]+)$',
        re.I | re.UNICODE
    ),
]


# ─── UTILS ───────────────────────────────────────────────────

def normalizar(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto.upper())
        if unicodedata.category(c) != 'Mn'
    ).replace('MARCO', 'MARÇO')


def parse_data(data_str: str):
    try:
        return datetime.strptime(data_str.strip(), '%d/%m/%Y').date()
    except Exception:
        return None


def parse_valor(valor_str: str) -> float:
    try:
        return float(
            str(valor_str).replace('R$', '').replace('.', '').replace(',', '.').strip()
        )
    except Exception:
        return 0.0


def parse_data_arg(texto: str):
    m = re.match(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', texto.strip())
    if m:
        dia, mes, ano = m.group(1), m.group(2), m.group(3) or str(datetime.now().year)
        try:
            return date(int(ano), int(mes), int(dia))
        except Exception:
            return None
    return None


def detectar_categoria(descricao: str) -> str:
    desc_norm = normalizar(descricao)
    for key, cat in CATEGORIA_MAP.items():
        if normalizar(key) in desc_norm:
            return cat
    return 'Outros'


def calcular_divisao(categoria: str, quem_pagou: str):
    cat_norm = normalizar(categoria)
    if any(c in cat_norm for c in ['AGUA', 'LUZ', 'ENERGIA']):
        divisao, todos = 4, list(PESSOAS)
    elif any(c in cat_norm for c in ['GATA', 'VETERINARIO']):
        divisao, todos = 2, ['Mateus', 'Cristhian']
    else:
        divisao, todos = 3, ['Mateus', 'Cristhian', 'Marcelo']
    pagadores = [p.strip() for p in quem_pagou.split(',')]
    quem_repassa = [p for p in todos if p not in pagadores]
    return divisao, ', '.join(quem_repassa)


def resolver_mes(args: list):
    if not args:
        return None, []
    candidato = normalizar(args[0])
    if candidato in MESES_NOMES:
        return candidato, args[1:]
    return None, args


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

    def _get_or_create_sheet(self, nome_aba: str):
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

    def listar_abas(self) -> list:
        try:
            if not self.spreadsheet:
                self._connect()
            return [ws.title for ws in self.spreadsheet.worksheets()
                    if ws.title.upper() in MESES_NOMES]
        except Exception as e:
            logger.error(f"❌ Erro ao listar abas: {e}")
            return []

    def get_rows(self, nome_aba: str):
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
                    'data_str':   row[0],
                    'data':       parse_data(row[0]),
                    'pagador':    row[1].strip(),
                    'descricao':  row[2].strip() or row[3].strip(),
                    'categoria':  row[3].strip(),
                    'valor':      parse_valor(row[4]),
                    'divisao':    int(row[5]) if row[5].strip().isdigit() else 3,
                    'repassa':    [p.strip() for p in row[6].split(',') if p.strip()],
                    'val_pessoa': parse_valor(row[7]),
                    'quitacao':   row[8].strip().lower(),
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
                f'R$ {valor_pessoa:.2f}'.replace('.', ','), 'Não Quitado', ''
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
        totais = {p: 0.0 for p in PESSOAS}
        total = 0.0
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

    def get_acerto(self, nome_aba=None, data_inicio=None, data_fim=None,
                   apenas_nao_quitados=True, pessoa_filtro=None):
        if not nome_aba:
            nome_aba = MESES_PT[datetime.now().month]
        rows = self.get_rows(nome_aba)
        if rows is None:
            return None

        filtrados = []
        for r in rows:
            if apenas_nao_quitados:
                q = r['quitacao']
                if 'quitado' in q and 'não' not in q and 'nao' not in q:
                    continue
            if data_inicio and r['data'] and r['data'] < data_inicio:
                continue
            if data_fim and r['data'] and r['data'] > data_fim:
                continue
            filtrados.append(r)

        saldo = {p: {q: 0.0 for q in PESSOAS} for p in PESSOAS}
        detalhes_por_item = []

        for r in filtrados:
            pagador  = r['pagador']
            val_parte = r['valor'] / r['divisao'] if r['divisao'] else r['valor']
            devedores = []
            for devedor in r['repassa']:
                if devedor in PESSOAS and devedor != pagador:
                    saldo[devedor][pagador] += val_parte
                    devedores.append((devedor, val_parte))
            if devedores:
                detalhes_por_item.append({
                    'data':        r['data_str'] or 'sem data',
                    'pagador':     pagador,
                    'descricao':   r['descricao'] or r['categoria'],
                    'valor_total': r['valor'],
                    'valor_parte': val_parte,
                    'devedores':   devedores,
                })

        transferencias = []
        processados = set()
        for a in PESSOAS:
            for b in PESSOAS:
                if a >= b or (a, b) in processados:
                    continue
                processados.add((a, b))
                liquido = saldo[a][b] - saldo[b][a]
                if liquido > 0.01:
                    transferencias.append((a, b, liquido))
                elif liquido < -0.01:
                    transferencias.append((b, a, -liquido))

        if pessoa_filtro:
            transferencias = [
                (de, para, val) for de, para, val in transferencias
                if de == pessoa_filtro or para == pessoa_filtro
            ]
            detalhes_por_item = [
                item for item in detalhes_por_item
                if item['pagador'] == pessoa_filtro or
                any(d == pessoa_filtro for d, _ in item['devedores'])
            ]

        return {
            'mes':               nome_aba,
            'transferencias':    transferencias,
            'detalhes_por_item': detalhes_por_item,
            'filtro_periodo':    (data_inicio, data_fim),
            'apenas_nao_quitados': apenas_nao_quitados,
            'total_itens':       len(filtrados),
            'pessoa_filtro':     pessoa_filtro,
        }

    def quitar_registros(self, nome_aba, data_inicio=None, data_fim=None):
        try:
            if not self.spreadsheet:
                self._connect()
            ws = self.spreadsheet.worksheet(nome_aba)
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return 0, 0

            atualizacoes = []
            total_nao_quitados = 0

            for i, row in enumerate(rows[1:], start=2):
                while len(row) < 9:
                    row.append('')
                if row[8].strip() != 'Não Quitado':
                    continue
                total_nao_quitados += 1
                data_row = parse_data(row[0])
                if data_inicio and data_row and data_row < data_inicio:
                    continue
                if data_fim and data_row and data_row > data_fim:
                    continue
                atualizacoes.append(i)

            if not atualizacoes:
                return 0, total_nao_quitados

            cell_list = [gspread.Cell(row=r, col=9, value='Quitado') for r in atualizacoes]
            ws.update_cells(cell_list, value_input_option='USER_ENTERED')
            logger.info(f"✅ {len(atualizacoes)} registros quitados em {nome_aba}")
            return len(atualizacoes), total_nao_quitados

        except gspread.WorksheetNotFound:
            return None, None
        except Exception as e:
            logger.error(f"❌ Erro ao quitar: {e}")
            return None, None

    def get_dados_completos(self):
        resultado = {}
        for aba in self.listar_abas():
            rows = self.get_rows(aba)
            if rows:
                resultado[aba] = rows
        return resultado


sheets = SheetsManager()


# ─── DETECÇÃO LOCAL (sem Groq) ────────────────────────────────

def _detectar_gasto_regex(text: str, user_name: str) -> dict | None:
    """Tenta detectar gasto via regex puro. Retorna dict ou None."""
    tl = text.lower().strip()
    for i, pat in enumerate(_REGEX_GASTOS):
        m = pat.search(tl)
        if not m:
            continue
        if i == 2:          # "comprei X por Y"
            descricao_raw = m.group(1).strip().title()
            valor = parse_valor(m.group(2))
        elif i == 5:        # "categoria valor"
            descricao_raw = m.group(1).strip().title()
            valor = parse_valor(m.group(2))
        else:
            valor = parse_valor(m.group(1))
            descricao_raw = m.group(2).strip().title()

        if valor <= 0:
            continue

        # Detecta se outra pessoa foi mencionada como pagadora
        pagador = user_name
        for nome in PESSOAS:
            if nome.lower() in tl and nome != user_name:
                if re.search(rf'\b{nome.lower()}\b\s+(?:pagou|gastou|comprou)', tl):
                    pagador = nome
                    break

        return {
            'tipo':      'gasto',
            'pagador':   pagador,
            'descricao': descricao_raw,
            'categoria': detectar_categoria(descricao_raw),
            'valor':     valor,
        }
    return None


def _detectar_intencao_keywords(text: str) -> dict | None:
    """Detecta intenções por palavras-chave. Retorna dict ou None."""
    tl   = text.lower()
    norm = normalizar(text)

    mes   = next((m for m in MESES_NOMES if m in norm), None)
    pessoa = next(
        (p for p in PESSOAS if normalizar(p) in norm),
        None
    )

    datas = [parse_data_arg(t) for t in text.split() if re.match(r'\d{1,2}/\d{1,2}', t)]
    datas = [d for d in datas if d]
    data_inicio = datas[0] if len(datas) >= 1 else None
    data_fim    = datas[1] if len(datas) >= 2 else None

    def _r(intencao):
        return {
            'tipo':       'intencao',
            'intencao':   intencao,
            'mes':        mes,
            'data_inicio': data_inicio.strftime('%d/%m') if data_inicio else None,
            'data_fim':    data_fim.strftime('%d/%m')    if data_fim    else None,
            'pessoa':      pessoa,
        }

    if any(k in tl for k in _KEYWORDS_ACERTO):
        return _r('acerto')
    if any(k in tl for k in _KEYWORDS_RESUMO):
        return _r('resumo')
    if any(k in tl for k in _KEYWORDS_EXTRATO):
        return _r('extrato')
    if any(k in tl for k in _KEYWORDS_QUITAR):
        return _r('quitar')
    if any(k in tl for k in _KEYWORDS_AJUDA):
        return _r('ajuda')
    return None


# ─── GROQ: chamada única e unificada ─────────────────────────

def _chamar_groq_unificado(text: str, user_name: str) -> dict:
    """
    Chamada ao Groq usada SOMENTE quando regex e keywords não resolveram.
    Detecta gasto OU intenção em uma única requisição.
    """
    if not GROQ_API_KEY:
        return {'tipo': 'intencao', 'intencao': 'perguntar'}

    categorias = sorted(set(CATEGORIA_MAP.values()))
    mes_atual  = MESES_PT[datetime.now().month]

    system_prompt = (
        f"Bot financeiro 'Finanças Casa MG'. Moradores: {', '.join(PESSOAS)}. "
        f"Remetente: {user_name}. Mês atual: {mes_atual}.\n"
        f"Categorias: {', '.join(categorias)}.\n\n"
        "Responda APENAS com JSON:\n"
        "GASTO: {\"tipo\":\"gasto\",\"pagador\":\"<nome>\",\"descricao\":\"<curta>\","
        "\"categoria\":\"<da lista ou Outros>\",\"valor\":<decimal>}\n"
        "OUTRO: {\"tipo\":\"intencao\",\"intencao\":\"<acerto|extrato|resumo|quitar|ajuda|perguntar|fora_escopo>\","
        "\"mes\":\"<MES ou null>\",\"data_inicio\":\"<dd/mm ou null>\",\"data_fim\":\"<dd/mm ou null>\","
        "\"pessoa\":\"<nome ou null>\"}\n\n"
        f"Exemplos:\n"
        f"\"gastei 50 mercado\" -> gasto, pagador={user_name}, categoria=Supermercado, valor=50.0\n"
        f"\"faz o acerto de maio\" -> intencao=acerto, mes=MAIO\n"
        f"\"bom dia\" -> intencao=fora_escopo"
    )

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": text}
                ],
                "max_tokens": 150,
                "temperature": 0.0,
            },
            timeout=15,
        )
        resp.raise_for_status()
        raw = re.sub(r"```json|```", "", resp.json()["choices"][0]["message"]["content"]).strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Erro Groq unificado: {e}")
        return {'tipo': 'intencao', 'intencao': 'perguntar'}


def chamar_groq_perguntar(pergunta: str, dados: dict) -> str:
    """Responde perguntas livres. Chamado apenas por /perguntar."""
    if not GROQ_API_KEY:
        return "❌ IA não configurada. Adicione GROQ_API_KEY no Railway."

    contexto = "Dados Finanças Casa MG:\n\n"
    for mes, rows in dados.items():
        contexto += f"=== {mes} ===\n"
        for r in rows[:50]:
            contexto += (
                f"  {r['data_str'] or 'sem data'} | {r['pagador']} R${r['valor']:.2f} "
                f"{r['descricao'] or r['categoria']} | ÷{r['divisao']} | "
                f"repassa: {', '.join(r['repassa'])} | {r['quitacao'] or 'sem status'}\n"
            )
        contexto += "\n"

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": (
                        "Assistente financeiro de 'Finanças Casa MG'. "
                        "Moradores: Mateus, Cristhian, Marcelo, Eli (Eli só divide água/luz). "
                        "Responda em português, direto, valores em R$ X,XX."
                    )},
                    {"role": "user", "content": f"{contexto}\nPergunta: {pergunta}"}
                ],
                "max_tokens": 800,
                "temperature": 0.2,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"❌ Erro Groq /perguntar: {e}")
        return f"❌ Erro ao consultar a IA: {e}"


# ─── HELPERS ─────────────────────────────────────────────────

def identify_user(update: Update) -> str:
    user = update.effective_user
    for attr in [user.username, user.first_name]:
        if attr:
            for key, name in USER_MAPPING.items():
                if key in attr.lower():
                    return name
    return user.first_name or "Usuário"


# ─── HANDLERS ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = identify_user(update)
    msg = (
        f"👋 Olá, <b>{nome}</b>! Sou o <b>Finanças Casa MG</b> 🏠💰\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>REGISTRAR GASTOS:</b>\n"
        '• "Gastei R$150 com mercado"\n'
        '• "Paguei R$80 de luz"\n'
        '• "R$45 de açougue"\n\n'
        "📊 <b>COMANDOS:</b>\n"
        "/resumo [mês] — gastos do mês\n"
        "/acerto [mês] [período] — acerto dos não quitados\n"
        "/extrato [mês] [período] — todos os registros\n"
        "/historico [mês] — últimos registros\n"
        "/perguntar — consulte a IA\n"
        "/ajuda — instruções completas\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f'📊 <a href="{SHEET_URL}">Abrir Planilha</a>'
    )
    await update.message.reply_text(msg, parse_mode='HTML')


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📋 <b>COMO USAR O BOT</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>Registrar gasto (texto livre):</b>\n"
        '• "Gastei R$150 com mercado"\n'
        '• "Paguei R$80 de luz"\n'
        '• "Marcelo pagou 90 de açougue"\n'
        '• "mercado 87,50"\n\n'
        "📊 <b>Resumo:</b>\n"
        "• /resumo → mês atual\n"
        "• /resumo MAIO → mês específico\n\n"
        "💸 <b>Acerto (não quitados):</b>\n"
        "• /acerto → mês atual\n"
        "• /acerto MAIO → mês específico\n"
        "• /acerto MAIO 17/05 31/05 → período\n"
        "• /acerto MAIO Mateus → filtrar pessoa\n\n"
        "📒 <b>Extrato (todos):</b>\n"
        "• /extrato → mês atual\n"
        "• /extrato MAIO Mateus → filtrar pessoa\n\n"
        "✅ <b>Quitar:</b>\n"
        "• /quitar MAIO\n"
        "• /quitar MAIO 17/05 31/05\n\n"
        "🤖 <b>Perguntar à IA:</b>\n"
        "• /perguntar qual o total do Mateus em maio?\n\n"
        "⚡ <b>Regras de divisão:</b>\n"
        "🏠 Gastos gerais → ÷3 (Mateus, Cristhian, Marcelo)\n"
        "💧 Água e Luz → ÷4 (+ Eli)\n"
        "🐱 Gastos Gata → ÷2 (Mateus, Cristhian)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode='HTML')


async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome_aba, _ = resolver_mes(list(context.args))
    await update.message.reply_text("⏳ Consultando planilha...")
    data = sheets.get_summary(nome_aba)

    if data is None:
        abas = sheets.listar_abas()
        await update.message.reply_text(
            f"❌ Mês não encontrado.\nDisponíveis: <b>{', '.join(abas)}</b>",
            parse_mode='HTML'
        )
        return

    msg = f"📊 <b>RESUMO — {data['mes']}</b>\n\n💰 <b>Total: R$ {data['total']:.2f}</b>\n\n👥 <b>Pago por:</b>\n"
    for pessoa, val in data['por_pessoa'].items():
        msg += f"   • {pessoa}: R$ {val:.2f}\n"
    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
    await update.message.reply_text(msg, parse_mode='HTML')


async def acerto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = list(context.args)
    nome_aba, args = resolver_mes(args)

    data_inicio = data_fim = pessoa_filtro = None
    datas_encontradas = []
    pessoas_validas = {normalizar(p): p for p in PESSOAS}

    for arg in args:
        arg_norm = normalizar(arg)
        if arg_norm in pessoas_validas:
            pessoa_filtro = pessoas_validas[arg_norm]
        else:
            d = parse_data_arg(arg)
            if d:
                datas_encontradas.append(d)

    if len(datas_encontradas) >= 1:
        data_inicio = datas_encontradas[0]
    if len(datas_encontradas) >= 2:
        data_fim = datas_encontradas[1]

    await update.message.reply_text("⏳ Calculando acerto...")
    data = sheets.get_acerto(nome_aba, data_inicio, data_fim,
                             apenas_nao_quitados=True, pessoa_filtro=pessoa_filtro)

    if data is None:
        abas = sheets.listar_abas()
        await update.message.reply_text(
            f"❌ Mês não encontrado.\nDisponíveis: <b>{', '.join(abas)}</b>",
            parse_mode='HTML'
        )
        return

    filtro_desc = ["não quitados"]
    if data_inicio:
        filtro_desc.append(f"de {data_inicio.strftime('%d/%m')}")
    if data_fim:
        filtro_desc.append(f"até {data_fim.strftime('%d/%m')}")
    if pessoa_filtro:
        filtro_desc.append(f"filtro: {pessoa_filtro}")
    filtro_str = f" ({', '.join(filtro_desc)})"

    msg  = f"💸 <b>ACERTO — {data['mes']}{filtro_str}</b>\n"
    msg += f"📦 {data['total_itens']} item(s) considerado(s)\n\n"

    if not data['transferencias']:
        msg += "✅ Tudo quitado! Nenhum saldo pendente."
    else:
        msg += "💰 <b>RESUMO FINAL (após abatimento):</b>\n"
        for de, para, val in sorted(data['transferencias'], key=lambda x: -x[2]):
            msg += f"   ➡️ <b>{de}</b> deve pagar <b>R$ {val:.2f}</b> para <b>{para}</b>\n"

        if data['detalhes_por_item']:
            msg += "\n📋 <b>DETALHAMENTO POR ITEM:</b>\n"
            for item in data['detalhes_por_item']:
                devs = ", ".join(f"{d} (R$ {v:.2f})" for d, v in item['devedores'])
                msg += (
                    f"\n• <b>{item['data']}</b> — {item['pagador']} pagou "
                    f"R$ {item['valor_total']:.2f} de {item['descricao']}\n"
                    f"  Deve repassar: {devs}\n"
                )

    msg += f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'

    if len(msg) <= 4096:
        await update.message.reply_text(msg, parse_mode='HTML')
    else:
        corte = msg.find('\n📋 <b>DETALHAMENTO')
        parte1 = (msg[:corte] if corte != -1 else msg[:4000]) + f'\n📊 <a href="{SHEET_URL}">Ver planilha</a>'
        await update.message.reply_text(parte1, parse_mode='HTML')
        parte2 = f"📋 <b>DETALHAMENTO ({data['mes']}):</b>\n"
        for item in data['detalhes_por_item']:
            devs  = ", ".join(f"{d} (R$ {v:.2f})" for d, v in item['devedores'])
            linha = (
                f"\n• <b>{item['data']}</b> — {item['pagador']} pagou "
                f"R$ {item['valor_total']:.2f} de {item['descricao']}\n"
                f"  Deve repassar: {devs}\n"
            )
            if len(parte2) + len(linha) > 4096:
                await update.message.reply_text(parte2, parse_mode='HTML')
                parte2 = ""
            parte2 += linha
        if parte2:
            await update.message.reply_text(parte2, parse_mode='HTML')


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome_aba, _ = resolver_mes(list(context.args))
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


async def extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = list(context.args)
    nome_aba, args = resolver_mes(args)

    data_inicio = data_fim = pessoa_filtro = None
    datas_encontradas = []
    pessoas_validas = {normalizar(p): p for p in PESSOAS}

    for arg in args:
        arg_norm = normalizar(arg)
        if arg_norm in pessoas_validas:
            pessoa_filtro = pessoas_validas[arg_norm]
        else:
            d = parse_data_arg(arg)
            if d:
                datas_encontradas.append(d)

    if len(datas_encontradas) >= 1:
        data_inicio = datas_encontradas[0]
    if len(datas_encontradas) >= 2:
        data_fim = datas_encontradas[1]

    await update.message.reply_text("⏳ Buscando registros...")

    if not nome_aba:
        nome_aba = MESES_PT[datetime.now().month]
    rows = sheets.get_rows(nome_aba)

    if rows is None:
        abas = sheets.listar_abas()
        await update.message.reply_text(
            f"❌ Mês não encontrado.\nDisponíveis: <b>{', '.join(abas)}</b>",
            parse_mode='HTML'
        )
        return

    filtrados = [
        r for r in rows
        if not (data_inicio and r['data'] and r['data'] < data_inicio)
        and not (data_fim    and r['data'] and r['data'] > data_fim)
        and not (pessoa_filtro and r['pagador'] != pessoa_filtro and pessoa_filtro not in r['repassa'])
    ]

    filtro_desc = []
    if data_inicio:
        filtro_desc.append(f"de {data_inicio.strftime('%d/%m')}")
    if data_fim:
        filtro_desc.append(f"até {data_fim.strftime('%d/%m')}")
    if pessoa_filtro:
        filtro_desc.append(f"filtro: {pessoa_filtro}")
    filtro_str = f" ({', '.join(filtro_desc)})" if filtro_desc else ""

    if not filtrados:
        await update.message.reply_text(
            f"📒 <b>EXTRATO — {nome_aba}{filtro_str}</b>\n\nNenhum registro encontrado.",
            parse_mode='HTML'
        )
        return

    total_geral = sum(r['valor'] for r in filtrados)
    header = (
        f"📒 <b>EXTRATO — {nome_aba}{filtro_str}</b>\n"
        f"📦 {len(filtrados)} registro(s) | Total: R$ {total_geral:.2f}\n\n"
    )
    rodape = f'📊 <a href="{SHEET_URL}">Ver planilha</a>'

    def _linha(r):
        quitado = 'quitado' in r['quitacao'] and 'não' not in r['quitacao'] and 'nao' not in r['quitacao']
        vp = r['valor'] / r['divisao'] if r['divisao'] else r['valor']
        rep = ", ".join(r['repassa']) if r['repassa'] else "ninguém"
        return (
            f"{'✅' if quitado else '🔴'} <b>{r['data_str'] or 'sem data'}</b> — {r['pagador']}\n"
            f"   {r['descricao'] or r['categoria']} — R$ {r['valor']:.2f}\n"
            f"   Repasse (R$ {vp:.2f} cada): {rep}\n\n"
        )

    msg = header + "".join(_linha(r) for r in filtrados) + rodape
    if len(msg) <= 4096:
        await update.message.reply_text(msg, parse_mode='HTML')
    else:
        parte = header
        for r in filtrados:
            l = _linha(r)
            if len(parte) + len(l) > 4000:
                await update.message.reply_text(parte, parse_mode='HTML')
                parte = ""
            parte += l
        parte += rodape
        await update.message.reply_text(parte, parse_mode='HTML')


async def quitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = list(context.args)
    nome_aba, args = resolver_mes(args)

    if not nome_aba:
        await update.message.reply_text(
            "❌ Informe o mês. Exemplo:\n/quitar MAIO\n/quitar MAIO 17/05 31/05"
        )
        return

    datas = [d for d in (parse_data_arg(a) for a in args) if d]
    data_inicio = datas[0] if len(datas) >= 1 else None
    data_fim    = datas[1] if len(datas) >= 2 else None

    filtro_parts = []
    if data_inicio:
        filtro_parts.append(f"de {data_inicio.strftime('%d/%m')}")
    if data_fim:
        filtro_parts.append(f"até {data_fim.strftime('%d/%m')}")
    filtro_str = f" ({', '.join(filtro_parts)})" if filtro_parts else ""

    await update.message.reply_text(
        f"⏳ Quitando registros de <b>{nome_aba}{filtro_str}</b>...", parse_mode='HTML'
    )

    qtd, total = sheets.quitar_registros(nome_aba, data_inicio, data_fim)

    if qtd is None:
        abas = sheets.listar_abas()
        await update.message.reply_text(
            f"❌ Mês não encontrado.\nDisponíveis: <b>{', '.join(abas)}</b>",
            parse_mode='HTML'
        )
    elif qtd == 0:
        await update.message.reply_text(
            f"⚠️ Nenhum registro pendente em <b>{nome_aba}{filtro_str}</b>.",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"✅ <b>{qtd} registro(s)</b> marcado(s) como Quitado em <b>{nome_aba}{filtro_str}</b>!\n"
            f"📊 Pendentes antes: {total} → agora: {total - qtd}",
            parse_mode='HTML'
        )


async def perguntar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🤖 <b>Como usar:</b>\n"
            "/perguntar qual o total do Mateus em maio?\n"
            "/perguntar quem gastou mais em supermercado?",
            parse_mode='HTML'
        )
        return

    pergunta      = ' '.join(context.args)
    pergunta_norm = normalizar(pergunta)

    await update.message.reply_text("🤖 Consultando a IA, aguarde...")

    meses_mencionados = [m for m in MESES_NOMES if m in pergunta_norm]
    if meses_mencionados:
        dados = {m: rows for m in meses_mencionados if (rows := sheets.get_rows(m))}
    else:
        mes_atual = MESES_PT[datetime.now().month]
        rows = sheets.get_rows(mes_atual)
        dados = {mes_atual: rows} if rows else {}

    if not dados:
        await update.message.reply_text("❌ Não consegui acessar a planilha.")
        return

    resposta = chamar_groq_perguntar(pergunta, dados)
    await update.message.reply_text(f"🤖 {resposta}")


# ─── HANDLER PRINCIPAL ───────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    user_name = identify_user(update)

    # ── 1. Regex local (sem Groq) ────────────────────────────
    resultado = _detectar_gasto_regex(text, user_name)

    # ── 2. Keywords locais (sem Groq) ────────────────────────
    if resultado is None:
        resultado = _detectar_intencao_keywords(text)

    # ── 3. Groq — somente se as etapas 1 e 2 falharam ────────
    if resultado is None:
        resultado = _chamar_groq_unificado(text, user_name)

    tipo = resultado.get('tipo', 'intencao')

    # ── Processar GASTO ──────────────────────────────────────
    if tipo == 'gasto':
        pagador   = resultado.get('pagador', user_name)
        descricao = resultado.get('descricao', '')
        categoria = resultado.get('categoria', 'Outros')
        valor     = float(resultado.get('valor', 0))

        if valor <= 0:
            await update.message.reply_text(
                "⚠️ Não consegui identificar o valor.\nTente: \"gastei R$50 de mercado\""
            )
            return

        divisao, quem_repassa = calcular_divisao(categoria, pagador)
        success, vp = sheets.add_expense(pagador, descricao, categoria, valor, divisao, quem_repassa)
        if success:
            await update.message.reply_text(
                f"✅ <b>GASTO REGISTRADO!</b>\n\n"
                f"👤 <b>Pago por:</b> {pagador}\n"
                f"📝 <b>Descrição:</b> {descricao}\n"
                f"🏷️ <b>Categoria:</b> {categoria}\n"
                f"💰 <b>Total:</b> R$ {valor:.2f}\n"
                f"👥 <b>Divisão:</b> {divisao} pessoas → R$ {vp:.2f} cada\n"
                f"🔄 <b>Repassar:</b> {quem_repassa}\n"
                f"📅 <b>Data:</b> {datetime.now().strftime('%d/%m/%Y')}\n\n"
                f'📊 <a href="{SHEET_URL}">Ver na planilha</a>',
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                "❌ Erro ao registrar na planilha.\n"
                "Verifique se a conta de serviço tem acesso."
            )
        return

    # ── Processar INTENÇÃO ────────────────────────────────────
    acao        = resultado.get('intencao', 'perguntar')
    mes         = resultado.get('mes')
    data_inicio = resultado.get('data_inicio')
    data_fim    = resultado.get('data_fim')
    pessoa      = resultado.get('pessoa')

    if acao == 'fora_escopo':
        await update.message.reply_text(
            "🏠 Sou o assistente de <b>Finanças Casa MG</b>!\n\n"
            "Trato apenas de finanças da casa. Exemplos:\n"
            "• <i>faz o acerto de maio</i>\n"
            "• <i>quanto gastamos esse mês</i>\n"
            "• <i>gastei R$50 de mercado</i>\n\n"
            "Use /ajuda para ver todos os comandos. 😊",
            parse_mode='HTML'
        )
        return

    args = [x for x in [mes, data_inicio, data_fim, pessoa] if x]
    context.args = args if acao != 'perguntar' else text.split()

    handler_map = {
        'acerto':    acerto,
        'extrato':   extrato,
        'resumo':    resumo,
        'quitar':    quitar,
        'ajuda':     ajuda,
        'perguntar': perguntar,
    }
    await handler_map.get(acao, perguntar)(update, context)


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN não configurado!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("ajuda",     ajuda))
    app.add_handler(CommandHandler("help",      ajuda))
    app.add_handler(CommandHandler("resumo",    resumo))
    app.add_handler(CommandHandler("acerto",    acerto))
    app.add_handler(CommandHandler("historico", historico))
    app.add_handler(CommandHandler("extrato",   extrato))
    app.add_handler(CommandHandler("quitar",    quitar))
    app.add_handler(CommandHandler("perguntar", perguntar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Bot iniciado!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

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
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
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
BOT_USERNAME   = os.getenv('BOT_USERNAME', '').lower().lstrip('@')  # ex: financascasamg_bot
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
_KEYWORDS_ACERTO  = {
    'acerto', 'deve ', 'devem', 'quem deve', 'quem paga', 'fazer acerto',
    'faz acerto', 'faz o acerto', 'fazer o acerto', 'calcular acerto',
    'calcula acerto', 'fechar acerto', 'fecha acerto', 'acerto do mes',
    'acerto do mês', 'quem ta devendo', 'quem está devendo',
    'quanto devo', 'quanto eu devo', 'saldo', 'quem deve o que',
}
_KEYWORDS_RESUMO  = {
    'resumo', 'quanto gastamos', 'quanto foi', 'total do mes',
    'total do mês', 'quanto gastei', 'gasto do mes', 'gasto do mês',
    'ver resumo', 'mostra resumo', 'total gasto', 'quanto gastou',
    'quanto foi gasto', 'relatorio', 'relatório', 'balanço', 'balanco',
    'quanto saiu', 'gastos do mes', 'gastos do mês', 'gastos totais',
}
_KEYWORDS_EXTRATO = {
    'extrato', 'mostra tudo', 'lista tudo', 'todos os registros', 'ver tudo',
    'listar tudo', 'ver registros', 'mostra registros', 'lista registros',
    'ver extrato', 'mostra extrato', 'tudo de', 'todos os gastos',
    'ver todos', 'listar gastos',
}
_KEYWORDS_QUITAR  = {
    'quitar', 'quita ', 'marca como quitado', 'marcar quitado',
    'marcar como quitado', 'definir quitado', 'setar quitado',
    'quitar tudo', 'quita tudo', 'pagar tudo', 'zerar dividas',
    'zerar dívidas', 'liquidar',
}
_KEYWORDS_HISTORICO = {
    'historico', 'histórico', 'ultimos gastos', 'últimos gastos',
    'ultimos registros', 'últimos registros', 'recentes', 'ver historico',
    'mostra historico', 'o que foi gasto', 'o que gastamos',
}
_KEYWORDS_AJUDA   = {
    'ajuda', '/help', 'como usar', 'o que voce faz', 'comandos',
    'como funciona', 'o que você faz', 'instrucoes', 'instruções',
    'me ajuda', 'help', 'o que posso fazer', 'o que tu faz',
}
_KEYWORDS_FORA_ESCOPO = {
    'oi', 'olá', 'ola', 'bom dia', 'boa tarde', 'boa noite', 'tudo bem',
    'como vai', 'e ai', 'é aí', 'eai', 'opa', 'hey', 'hi', 'hello',
    'obrigado', 'obrigada', 'valeu', 'vlw', 'tmj', 'ok', 'certo', 'blz',
    'entendi', 'show', 'perfeito', 'ótimo', 'otimo', 'legal', 'bacana',
}

# ── Regex adicionais para variações de gasto ─────────────────
_REGEX_VARIACAO_GASTO = [
    # "coloca X de Y" / "adiciona X de Y" / "lança X de Y"
    re.compile(r'(?:coloca|adiciona|lança|lanca|bota|registra)\s+r?\$?\s*([\d.,]+)\s+(?:de|da|do|com|no|na)\s+(.+)', re.I),
    # "X reais no/na Y"
    re.compile(r'([\d.,]+)\s+(?:reais?|conto[s]?|pila[s]?)\s+(?:no|na|de|do|da|com)\s+(.+)', re.I),
    # "Y custou X" / "Y foi X"
    re.compile(r'(.+?)\s+(?:custou|saiu|foi)\s+r?\$?\s*([\d.,]+)', re.I),
    # "paguei o Y de X" / "paguei a Y de X"
    re.compile(r'paguei\s+(?:o|a|os|as)\s+(.+?)\s+(?:de|da|do|por)\s+r?\$?\s*([\d.,]+)', re.I),
]

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
    """
    Extrai o mês dos args, aceitando:
    - ['MAIO', ...]           → 'MAIO'
    - ['de', 'MAIO', ...]     → 'MAIO'
    - ['do', 'MES', ...]      → 'MES'
    """
    if not args:
        return None, []
    # Tenta o primeiro arg direto
    candidato = normalizar(args[0])
    if candidato in MESES_NOMES:
        return candidato, args[1:]
    # Tenta pular preposições ('de', 'do', 'da', 'em') e pegar o próximo
    if candidato in {'DE', 'DO', 'DA', 'EM', 'NO', 'NA'} and len(args) > 1:
        candidato2 = normalizar(args[1])
        if candidato2 in MESES_NOMES:
            return candidato2, args[2:]
    # Busca o mês em qualquer posição nos args
    for i, arg in enumerate(args):
        if normalizar(arg) in MESES_NOMES:
            return normalizar(arg), args[:i] + args[i+1:]
    return None, args


# ─── SHEETS MANAGER ──────────────────────────────────────────

_CACHE_TTL = 60  # segundos — tempo máximo de cache por aba

class SheetsManager:
    def __init__(self):
        self.client = None
        self.spreadsheet = None
        self._cache: dict = {}          # {nome_aba: (timestamp, rows)}
        self._abas_cache: dict = {}     # {NOME_NORMALIZADO: nome_real} — evita roundtrip duplo
        self._abas_cache_ts: float = 0
        self._ABAS_CACHE_TTL = 120      # segundos
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

            # Força timeout de 15s em TODAS as chamadas HTTP do gspread
            original_request = self.client.http_client.request
            def request_com_timeout(*args, **kwargs):
                kwargs.setdefault('timeout', 15)
                return original_request(*args, **kwargs)
            self.client.http_client.request = request_com_timeout

            self.spreadsheet = self.client.open_by_key(SPREADSHEET_ID)
            logger.info("✅ Conectado ao Google Sheets")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar Sheets: {e}")

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

    def _atualizar_cache_abas(self):
        """Atualiza o mapeamento normalizado→real das abas. TTL de 2 minutos."""
        if time.time() - self._abas_cache_ts < self._ABAS_CACHE_TTL and self._abas_cache:
            return
        try:
            if not self.spreadsheet:
                self._connect()
            abas = self.spreadsheet.worksheets()
            self._abas_cache = {normalizar(ws.title): ws.title for ws in abas}
            self._abas_cache_ts = time.time()
            logger.info(f"📋 Cache de abas atualizado: {list(self._abas_cache.values())}")
        except Exception as e:
            logger.error(f"❌ Erro ao atualizar cache de abas: {e}")

    def listar_abas(self) -> list:
        """Retorna os títulos reais das abas que correspondem a meses."""
        try:
            self._atualizar_cache_abas()
            return [v for k, v in self._abas_cache.items() if k in MESES_NOMES]
        except Exception as e:
            logger.error(f"❌ Erro ao listar abas: {e}")
            return []

    def resolver_nome_aba(self, nome_mes_normalizado: str) -> str | None:
        """Dado 'MAIO', retorna o título real da aba (ex: 'Maio', 'maio', 'MAIO')."""
        self._atualizar_cache_abas()
        return self._abas_cache.get(nome_mes_normalizado)

    def invalidar_cache(self, nome_aba: str = None):
        """Invalida cache de uma aba específica ou de todas."""
        if nome_aba:
            self._cache.pop(nome_aba, None)
            # Invalida também pelo nome normalizado, caso seja a chave usada
            nome_norm = normalizar(nome_aba)
            nome_real = self._abas_cache.get(nome_norm, nome_aba)
            self._cache.pop(nome_real, None)
        else:
            self._cache.clear()
        # Força atualização do cache de abas na próxima chamada
        self._abas_cache_ts = 0

    def get_rows(self, nome_aba: str):
        try:
            if not self.spreadsheet:
                self._connect()

            # Resolve o nome real da aba usando o cache interno (sem roundtrip extra)
            nome_norm = normalizar(nome_aba)
            self._atualizar_cache_abas()
            nome_real = self._abas_cache.get(nome_norm) or nome_aba

            # Retorna do cache se ainda válido
            entrada = self._cache.get(nome_real)
            if entrada:
                ts, rows = entrada
                if time.time() - ts < _CACHE_TTL:
                    return rows

            ws = self.spreadsheet.worksheet(nome_real)
            logger.info(f"📡 Buscando dados da aba '{nome_real}' no Sheets...")
            t0 = time.time()
            raw = ws.get_all_values()
            logger.info(f"✅ Sheets respondeu em {time.time()-t0:.2f}s — {len(raw)} linhas")
            result = []
            for row in raw[1:]:
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
            final = [r for r in result if r['valor'] > 0]
            self._cache[nome_real] = (time.time(), final)   # chave = nome_real (consistente)
            return final
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
            self.invalidar_cache(nome_aba)   # força releitura na próxima consulta
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
        # get_rows já resolve o nome real internamente — sem roundtrip duplo
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

        # Determina o nome real (já foi resolvido em get_rows via cache de abas)
        nome_norm = normalizar(nome_aba)
        nome_display = self._abas_cache.get(nome_norm, nome_aba)

        return {
            'mes':               nome_display,
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
            nome_aba = self.resolver_nome_aba(nome_aba) or nome_aba
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
            self.invalidar_cache(nome_aba)   # força releitura na próxima consulta
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

# Executor dedicado para chamadas bloqueantes (Sheets, Groq)
_executor = ThreadPoolExecutor(max_workers=4)

async def _run(func, *args, **kwargs):
    """Executa função bloqueante em thread sem travar o event loop.
    Garante timeout máximo de 20s — se ultrapassar, lança TimeoutError."""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, lambda: func(*args, **kwargs)),
            timeout=20
        )
    except asyncio.TimeoutError:
        logger.error(f"⏰ Timeout em {func.__name__} após 20s")
        raise


# ─── DETECÇÃO LOCAL (sem Groq) ────────────────────────────────

def _detectar_gasto_regex(text: str, user_name: str) -> dict | None:
    """Tenta detectar gasto via regex puro. Retorna dict ou None."""
    tl = text.lower().strip()

    todos_regex = _REGEX_GASTOS + _REGEX_VARIACAO_GASTO

    for i, pat in enumerate(todos_regex):
        m = pat.search(tl)
        if not m:
            continue

        # Padrões com ordem (desc, valor)
        if i == 2 or i >= len(_REGEX_GASTOS):          # "comprei X por Y" e variações novas
            g1, g2 = m.group(1).strip().title(), m.group(2)
            # alguns novos regex também têm (desc, valor)
            if i in (2,) or i >= len(_REGEX_GASTOS):
                try:
                    valor = parse_valor(g2)
                    descricao_raw = g1
                    if valor <= 0:                      # tenta inverter
                        valor = parse_valor(g1)
                        descricao_raw = g2.strip().title()
                except Exception:
                    continue
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
                if re.search(rf'\b{nome.lower()}\b\s+(?:pagou|gastou|comprou|colocou|lancou|lançou)', tl):
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

    # Fora de escopo detectado localmente — sem chamar Groq
    if any(k == tl.strip() for k in _KEYWORDS_FORA_ESCOPO):
        return _r('fora_escopo')

    if any(k in tl for k in _KEYWORDS_ACERTO):
        return _r('acerto')
    if any(k in tl for k in _KEYWORDS_RESUMO):
        return _r('resumo')
    if any(k in tl for k in _KEYWORDS_EXTRATO):
        return _r('extrato')
    if any(k in tl for k in _KEYWORDS_QUITAR):
        return _r('quitar')
    if any(k in tl for k in _KEYWORDS_HISTORICO):
        return _r('historico')
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

    # ⚠️ Log para monitorar frequência de uso do Groq
    logger.warning(f"🤖 [GROQ] chamado para: '{text[:80]}' (user: {user_name})")

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
        for tentativa in range(2):   # tenta 2x antes de desistir
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
                    timeout=20,
                )
                resp.raise_for_status()
                raw = re.sub(r"```json|```", "", resp.json()["choices"][0]["message"]["content"]).strip()
                return json.loads(raw)
            except requests.exceptions.Timeout:
                if tentativa == 0:
                    logger.warning("Groq timeout, tentando novamente...")
                    continue
                raise
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
    mention = f"@{BOT_USERNAME}" if BOT_USERNAME else "@o_bot"
    msg = (
        f"👋 Olá, <b>{nome}</b>! Sou o <b>Finanças Casa MG</b> 🏠💰\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>REGISTRAR GASTOS</b> (texto livre):\n"
        '• "Gastei R$150 com mercado"\n'
        '• "Paguei R$80 de luz"\n'
        '• "R$45 de açougue"\n'
        '• "mercado 87,50"\n'
        '• "Marcelo pagou 90 de açougue"\n\n'
        "📊 <b>CONSULTAS:</b>\n"
        "/resumo [mês] — total gasto no mês\n"
        "/acerto [mês] — quem deve quanto a quem\n"
        "/extrato [mês] — todos os registros\n"
        "/historico [mês] — últimos lançamentos\n"
        "/quitar [mês] — marcar tudo como quitado\n"
        "/perguntar [pergunta] — consulta livre à IA\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>NO GRUPO</b>, me chame assim:\n"
        f'• {mention} gastei R$50 de mercado\n'
        f'• {mention} faz o acerto de maio\n'
        f'• {mention} /resumo\n'
        f'• Ou responda qualquer mensagem minha\n\n'
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f'📊 <a href="{SHEET_URL}">Abrir Planilha</a> • /ajuda para mais detalhes'
    )
    await update.message.reply_text(msg, parse_mode='HTML')


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mention = f"@{BOT_USERNAME}" if BOT_USERNAME else "@o_bot"
    msg = (
        "📋 <b>COMO USAR — FINANÇAS CASA MG</b>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>REGISTRAR GASTO (texto livre):</b>\n"
        '• "Gastei R$150 com mercado"\n'
        '• "Paguei R$80 de luz"\n'
        '• "R$45 de açougue"\n'
        '• "mercado 87,50"\n'
        '• "feira saiu 60"\n'
        '• "coloca 30 de padaria"\n'
        '• "Marcelo pagou 90 de açougue"\n\n'

        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>RESUMO</b> — total do mês:\n"
        "• /resumo → mês atual\n"
        "• /resumo MAIO → mês específico\n"
        '• "quanto gastamos em maio"\n\n'

        "💸 <b>ACERTO</b> — quem deve quanto:\n"
        "• /acerto → mês atual\n"
        "• /acerto MAIO → mês específico\n"
        "• /acerto MAIO 01/05 15/05 → por período\n"
        "• /acerto MAIO Mateus → filtrar pessoa\n"
        '• "faz o acerto de maio"\n\n'

        "📒 <b>EXTRATO</b> — todos os registros:\n"
        "• /extrato → mês atual\n"
        "• /extrato MAIO Mateus → filtrar pessoa\n"
        '• "mostra tudo de maio"\n\n'

        "📜 <b>HISTÓRICO</b> — últimos lançamentos:\n"
        "• /historico → mês atual\n"
        "• /historico MAIO\n"
        '• "últimos gastos"\n\n'

        "✅ <b>QUITAR</b> — marcar como pago:\n"
        "• /quitar MAIO → quita tudo\n"
        "• /quitar MAIO 01/05 15/05 → por período\n"
        '• "quitar maio"\n\n'

        "🤖 <b>PERGUNTAR À IA:</b>\n"
        "• /perguntar qual o total do Mateus em maio?\n"
        "• /perguntar quem gastou mais no supermercado?\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>USO NO GRUPO:</b>\n"
        f"Mencione o bot antes da mensagem:\n"
        f"  {mention} gastei R$50 de mercado\n"
        f"  {mention} faz o acerto de maio\n"
        f"  {mention} /resumo JUNHO\n"
        f"Ou responda (<i>Reply</i>) a qualquer mensagem minha.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>REGRAS DE DIVISÃO:</b>\n"
        "🏠 Gastos gerais → ÷3 (Mateus, Cristhian, Marcelo)\n"
        "💧 Água e Luz → ÷4 (todos, inclui Eli)\n"
        "🐱 Gastos Gata → ÷2 (Mateus, Cristhian)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode='HTML')


async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome_aba, _ = resolver_mes(list(context.args))
    await update.message.reply_text("⏳ Consultando planilha...")
    try:
        data = await _run(sheets.get_summary, nome_aba)
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ Tempo esgotado ao acessar a planilha. Tente novamente.")
        return

    if data is None:
        abas = await _run(sheets.listar_abas)
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
    try:
        data = await _run(sheets.get_acerto, nome_aba, data_inicio, data_fim, True, pessoa_filtro)
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ Tempo esgotado ao acessar a planilha. Tente novamente em alguns segundos.")
        return

    if data is None:
        abas = await _run(sheets.listar_abas)
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
    data = await _run(sheets.get_summary, nome_aba)

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
    rows = await _run(sheets.get_rows, nome_aba)

    if rows is None:
        abas = await _run(sheets.listar_abas)
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

    qtd, total = await _run(sheets.quitar_registros, nome_aba, data_inicio, data_fim)

    if qtd is None:
        abas = await _run(sheets.listar_abas)
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
        rows_list = await asyncio.gather(*[_run(sheets.get_rows, m) for m in meses_mencionados])
        dados = {m: r for m, r in zip(meses_mencionados, rows_list) if r}
    else:
        mes_atual = MESES_PT[datetime.now().month]
        rows = await _run(sheets.get_rows, mes_atual)
        dados = {mes_atual: rows} if rows else {}

    if not dados:
        await update.message.reply_text("❌ Não consegui acessar a planilha.")
        return

    resposta = await _run(chamar_groq_perguntar, pergunta, dados)
    await update.message.reply_text(f"🤖 {resposta}")


# ─── HANDLER PRINCIPAL ───────────────────────────────────────

def _limpar_mencao(text: str) -> str:
    """Remove a menção ao bot do início da mensagem."""
    if not BOT_USERNAME:
        return text.strip()
    # Remove @username do início, case-insensitive
    padrao = re.compile(rf'^@{re.escape(BOT_USERNAME)}\s*', re.I)
    return padrao.sub('', text).strip()


def _deve_responder_no_grupo(update: Update) -> bool:
    """
    Em grupos, o bot responde SOMENTE se:
    1. A mensagem menciona @bot_username
    2. A mensagem é uma resposta (reply) a uma mensagem do próprio bot
    3. É uma mensagem privada (chat individual)
    """
    msg = update.message
    if not msg:
        return False

    # Conversa privada → sempre responde
    if msg.chat.type == 'private':
        return True

    # Reply a uma mensagem do bot → responde
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.is_bot:
            return True

    # Menção direta ao bot no texto
    if BOT_USERNAME and msg.text:
        if f'@{BOT_USERNAME}'.lower() in msg.text.lower():
            return True

    # Menção via entities do Telegram (mais confiável)
    if msg.entities:
        for entity in msg.entities:
            if entity.type == 'mention':
                mention_text = msg.text[entity.offset: entity.offset + entity.length]
                if BOT_USERNAME and mention_text.lower() == f'@{BOT_USERNAME}'.lower():
                    return True

    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    # Em grupos: ignora se não foi chamado
    if not _deve_responder_no_grupo(update):
        return

    # Remove a menção do início para processar o texto limpo
    text = _limpar_mencao(msg.text)
    if not text:
        # Mencionaram o bot sem dizer nada — mostra ajuda rápida
        nome = identify_user(update)
        mention = f"@{BOT_USERNAME}" if BOT_USERNAME else "o bot"
        await msg.reply_text(
            f"👋 Oi, <b>{nome}</b>! Me chame com uma mensagem, por exemplo:\n"
            f"<i>{mention} gastei R$50 de mercado</i>\n"
            f"<i>{mention} faz o acerto de maio</i>\n\n"
            f"Use /ajuda para ver tudo que posso fazer.",
            parse_mode='HTML'
        )
        return

    user_name = identify_user(update)

    # ── 1. Regex local (sem Groq) ────────────────────────────
    resultado = _detectar_gasto_regex(text, user_name)

    # ── 2. Keywords locais (sem Groq) ────────────────────────
    if resultado is None:
        resultado = _detectar_intencao_keywords(text)

    # ── 3. Groq — somente se as etapas 1 e 2 falharam ────────
    if resultado is None:
        resultado = await _run(_chamar_groq_unificado, text, user_name)

    tipo = resultado.get('tipo', 'intencao')

    # ── Processar GASTO ──────────────────────────────────────
    if tipo == 'gasto':
        pagador   = resultado.get('pagador', user_name)
        descricao = resultado.get('descricao', '')
        categoria = resultado.get('categoria', 'Outros')
        valor     = float(resultado.get('valor', 0))

        if valor <= 0:
            await msg.reply_text(
                "⚠️ Não consegui identificar o valor.\nTente: \"gastei R$50 de mercado\""
            )
            return

        divisao, quem_repassa = calcular_divisao(categoria, pagador)
        success, vp = await _run(sheets.add_expense, pagador, descricao, categoria, valor, divisao, quem_repassa)
        if success:
            await msg.reply_text(
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
            await msg.reply_text(
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
        await msg.reply_text(
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
        'historico': historico,
        'perguntar': perguntar,
    }
    await handler_map.get(acao, perguntar)(update, context)


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN não configurado!")
        return

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("ajuda",     ajuda))
    app.add_handler(CommandHandler("help",      ajuda))
    app.add_handler(CommandHandler("resumo",    resumo))
    app.add_handler(CommandHandler("acerto",    acerto))
    app.add_handler(CommandHandler("historico", historico))
    app.add_handler(CommandHandler("extrato",   extrato))
    app.add_handler(CommandHandler("quitar",    quitar))
    app.add_handler(CommandHandler("perguntar", perguntar))
    # Texto livre — privado e grupos
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    logger.info("🚀 Bot iniciado!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

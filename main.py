import requests
import pandas as pd
import numpy as np
import time
import os
from datetime import datetime
import logging

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARES = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
TIMEFRAME = '5m'
LIMITE_VELAS = 200
BASE_URL = 'https://api.binance.com/api/v3/klines'

def enviar_mensagem_telegram(mensagem):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': mensagem, 'parse_mode': 'HTML'}
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("✅ Mensagem enviada")
        else:
            logger.error(f"❌ Erro: {response.text}")
    except Exception as e:
        logger.error(f"❌ Erro: {e}")

def buscar_dados_binance(symbol, interval, limit):
    try:
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        dados = response.json()
        df = pd.DataFrame(dados, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        logger.error(f"❌ Erro ao buscar {symbol}: {e}")
        return None

def calcular_indicadores(df):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['volume_media_20'] = df['volume'].rolling(window=20).mean()
    return df

def verificar_cruzamento_ema(df, n_velas=5):
    for i in range(1, n_velas + 1):
        if len(df) > i:
            if (df['ema9'].iloc[-i] > df['ema21'].iloc[-i]) and (df['ema9'].iloc[-i-1] <= df['ema21'].iloc[-i-1]):
                return True, 'compra'
            elif (df['ema9'].iloc[-i] < df['ema21'].iloc[-i]) and (df['ema9'].iloc[-i-1] >= df['ema21'].iloc[-i-1]):
                return True, 'venda'
    return False, None

def analisar_sinal(df, symbol):
    ultima_vela = df.iloc[-1]
    penultima_vela = df.iloc[-2]
    preco_atual = ultima_vela['close']
    rsi = ultima_vela['rsi']
    ema9 = ultima_vela['ema9']
    ema21 = ultima_vela['ema21']
    ema200 = ultima_vela['ema200']
    volume_atual = ultima_vela['volume']
    volume_medio = ultima_vela['volume_media_20']
    
    criterios = {
        'rsi': 30 <= rsi <= 45,
        'tendencia': preco_atual > ema200,
        'cruzamento': verificar_cruzamento_ema(df)[0] and verificar_cruzamento_ema(df)[1] == 'compra',
        'momentum': ema9 > penultima_vela['ema9'],
        'volume': volume_atual > volume_medio
    }
    
    score = sum(criterios.values())
    sinal_sem_cruzamento = criterios['rsi'] and criterios['tendencia'] and criterios['momentum']
    
    if score >= 4 or (score == 3 and sinal_sem_cruzamento):
        forca = "🚀 SINAL FORTE" if score >= 5 else "⚠️ SINAL MODERADO"
        return {'sinal': True, 'tipo': 'COMPRA', 'score': score, 'forca': forca, 'preco': preco_atual, 'rsi': rsi, 'cruzamento': criterios['cruzamento'], 'tendencia': criterios['tendencia'], 'momentum_subindo': criterios['momentum'], 'volume_alto': criterios['volume'], 'criterios': criterios}
    return {'sinal': False, 'score': score, 'criterios': criterios}

def formatar_mensagem_telegram(sinal_info, symbol):
    moeda = symbol.replace('USDT', '')
    tipo_emoji = "🚨" if sinal_info['score'] >= 5 else "⚠️"
    return f"""{tipo_emoji} SINAL DE {sinal_info['tipo']} - {moeda}/USDT
━━━━━━━━━━━━━━━━━━━━━━
💵 Preço: ${sinal_info['preco']:,.2f}
📊 Score: {sinal_info['score']}/5 ({sinal_info['forca']})
📈 Indicadores:
• RSI: {sinal_info['rsi']:.1f}
• EMA cruzamento: {'✅ sim' if sinal_info['cruzamento'] else '❌ não'}
• Tendência: {'⬆️ alta' if sinal_info['tendencia'] else '⬇️ baixa'}
• Momentum: {'⬆️ subindo' if sinal_info['momentum_subindo'] else '⬇️ descendo'}
• Volume: {'🔊 alto' if sinal_info['volume_alto'] else '📊 normal'}
💡 Sugestão: Entrada ${sinal_info['preco']:,.2f} - {sinal_info['forca']}
━━━━━━━━━━━━━━━━━━━━━━
⚠️ Sinal técnico. Gerencie risco."""

def mostrar_log_console(symbol, df, sinal_info):
    ultima_vela = df.iloc[-1]
    criterios = sinal_info.get('criterios', {})
    print(f"\n{'='*50}\n📊 {symbol}\n{'='*50}")
    print(f"💰 Preço: ${ultima_vela['close']:,.2f} | RSI: {ultima_vela['rsi']:.1f}")
    print(f"📊 EMA9: {ultima_vela['ema9']:.0f} | EMA21: {ultima_vela['ema21']:.0f} | EMA200: {ultima_vela['ema200']:.0f}")
    print(f"📋 Critérios: RSI: {'✅' if criterios.get('rsi') else '❌'} | Tendência: {'✅' if criterios.get('tendencia') else '❌'} | Cruzamento: {'✅' if criterios.get('cruzamento') else '❌'} | Momentum: {'✅' if criterios.get('momentum') else '❌'} | Volume: {'✅' if criterios.get('volume') else '❌'}")
    print(f"🎯 Score: {sinal_info['score']}/5")
    print(f"{'='*50}\n")

def main():
    logger.info("🤖 Bot Iniciado!")
    logger.info(f"📊 Monitorando: {', '.join(PARES)}")
    logger.info(f"⏱️ Timeframe: {TIMEFRAME}")
    logger.info(f"🔐 Bot: @agent_cripto_bot")
    ciclo = 0
    while True:
        try:
            ciclo += 1
            logger.info(f"🔄 CICLO #{ciclo} - {datetime.now().strftime('%H:%M:%S')}")
            for par in PARES:
                df = buscar_dados_binance(par, TIMEFRAME, LIMITE_VELAS)
                if df is None or len(df) < 200:
                    continue
                df = calcular_indicadores(df)
                sinal_info = analisar_sinal(df, par)
                mostrar_log_console(par, df, sinal_info)
                if sinal_info['sinal']:
                    logger.info(f"🎯 SINAL DETECTADO para {par} - Score: {sinal_info['score']}/5")
                    enviar_mensagem_telegram(formatar_mensagem_telegram(sinal_info, par))
            logger.info(f"💤 Aguardando 5 minutos...")
            time.sleep(300)
        except Exception as e:
            logger.error(f"Erro: {e}")
            time.sleep(60)

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error("❌ Configure TELEGRAM_TOKEN e CHAT_ID nas variáveis de ambiente")
        exit(1)
    main()

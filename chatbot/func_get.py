import ccxt
import pandas as pd
import datetime as dt
from dateutil import tz
import json

from func_cal import cal_unrealised


def get_config_params(bot_type, config_params_path):
    with open(config_params_path) as config_file:
        config_params = json.load(config_file)

    symbol = config_params['symbol']

    if bot_type == 'grid':
        grid = config_params['grid']
        init_budget = config_params['init_budget']
    else:
        grid = None
        init_budget = None

    return symbol, grid, init_budget


def get_keys_path(config_system_path):
    with open(config_system_path) as config_file:
        config_system = json.load(config_file)

    keys_path = config_system['keys_path']

    return keys_path


def get_date(timezone = 'Asia/Bangkok'):
    timestamp = dt.datetime.now(tz = tz.gettz(timezone))
    date = timestamp.date()
    
    return date


def get_exchange(keys_path):
    with open(keys_path) as keys_file:
        keys_dict = json.load(keys_file)
    
    exchange = ccxt.ftx({'apiKey': keys_dict['apiKey'],
                         'secret': keys_dict['secret'],
                         'headers': {'FTX-SUBACCOUNT': keys_dict['subaccount']},
                         'enableRateLimit': True})

    return exchange
    

def get_last_price(exchange, symbol):
    ticker = exchange.fetch_ticker(symbol)
    last_price = ticker['last']

    return last_price


def get_currency(symbol):
    base_currency = symbol.split('/')[0]
    quote_currency = symbol.split('/')[1]

    return base_currency, quote_currency    


def get_balance(exchange, base_currency, quote_currency, last_price, config_system_path):
    balance = exchange.fetch_balance()

    try:
        base_currency_amount = balance[base_currency]['total']
    except KeyError:
        base_currency_amount = 0

    base_currency_value = last_price * base_currency_amount

    try:    
        quote_currency_value = balance[quote_currency]['total']
    except KeyError:
        quote_currency_value = 0
    
    balance = base_currency_value + quote_currency_value

    return balance


def get_current_value(exchange, base_currency, last_price):
    balance = exchange.fetch_balance()
    
    try:
        amount = balance[base_currency]['total']
        current_value = last_price * amount
    except KeyError:
        current_value = 0

    return current_value


def get_hold_assets(grid, last_price, open_orders_df):
    unrealised, n_open_sell_oders, amount, avg_price = cal_unrealised(last_price, grid, open_orders_df)

    return unrealised, n_open_sell_oders, amount, avg_price


def get_pending_order(quote_currency, open_orders_df):
    open_buy_orders_df = open_orders_df[open_orders_df['side'] == 'buy']
    min_buy_price = min(open_buy_orders_df['price'], default = 0)
    max_buy_price = max(open_buy_orders_df['price'], default = 0)

    open_sell_orders_df = open_orders_df[open_orders_df['side'] == 'sell']
    min_sell_price = min(open_sell_orders_df['price'], default = 0)
    max_sell_price = max(open_sell_orders_df['price'], default = 0)

    return min_buy_price, max_buy_price, min_sell_price, max_sell_price


def get_rebalance_text(text, bot_type, sub_path, config_system_path, config_params_path, profit_df_path):
    keys_path = get_keys_path(sub_path + config_system_path)
    exchange = get_exchange(keys_path)

    symbol, _, _ = get_config_params(bot_type, sub_path + config_params_path)
    base_currency, quote_currency = get_currency(symbol)
    last_price = get_last_price(exchange, symbol)

    cur_date = get_date()
    profit_df = pd.read_csv(sub_path + profit_df_path)
    today_profit_df = profit_df[pd.to_datetime(profit_df['timestamp']).dt.date == cur_date]

    balance = get_balance(exchange, base_currency, quote_currency, last_price, config_system_path)
    current_value = get_current_value(exchange, base_currency, last_price)
    cash = balance - current_value
    cash_flow = sum(today_profit_df['profit'])

    text += '\nBalance: {:.2f} {}'.format(balance, quote_currency)
    text += '\nCurrent value: {:.2f} {}'.format(current_value, quote_currency)
    text += '\nCash: {:.2f} {}'.format(cash, quote_currency)
    text += '\nToday cash flow: {:.2f} {}'.format(cash_flow, quote_currency)

    return text


def get_grid_text(text, bot_name, bot_type, sub_path, config_system_path, config_params_path, last_loop_path, open_orders_df_path, transactions_df_path):
    keys_path = get_keys_path(sub_path + config_system_path)
    exchange = get_exchange(keys_path)

    symbol, grid, init_budget = get_config_params(bot_type, sub_path + config_params_path)
    base_currency, quote_currency = get_currency(symbol)
    last_price = get_last_price(exchange, symbol)
    
    open_orders_df = pd.read_csv(sub_path + open_orders_df_path)
    transactions_df = pd.read_csv(sub_path + transactions_df_path)

    cur_date = get_date()

    balance = get_balance(exchange, base_currency, quote_currency, last_price, config_system_path)
    unrealised, n_open_sell_oders, amount, avg_price = get_hold_assets(grid, last_price, open_orders_df)

    today_transactions_df = transactions_df[pd.to_datetime(transactions_df['timestamp']).dt.date == cur_date]
    today_sell_df = today_transactions_df[today_transactions_df['side'] == 'sell']
    cash_flow = sum(today_sell_df['amount'] * grid)
    
    min_buy_price, max_buy_price, min_sell_price, max_sell_price = get_pending_order(quote_currency, open_orders_df)

    text += '\nBalance: {:.2f} {}'.format(balance, quote_currency)
    text += '\nHold {:.4f} {} with {} orders at {:.2f} {}'.format(amount, base_currency, n_open_sell_oders, avg_price, quote_currency)
    text += '\nUnrealised: {:.2f} {}'.format(unrealised, quote_currency)
    text += '\nToday cash flow: {:.2f} {}'.format(cash_flow, quote_currency)
    text += '\nMin buy price: {:.2f} {}'.format(min_buy_price, quote_currency)
    text += '\nMax buy price: {:.2f} {}'.format(max_buy_price, quote_currency)
    text += '\nMin sell price: {:.2f} {}'.format(min_sell_price, quote_currency)
    text += '\nMax sell price: {:.2f} {}'.format(max_sell_price, quote_currency)

    return text
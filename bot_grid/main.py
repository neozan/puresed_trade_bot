import pandas as pd
import time
import os

from func_get import get_config_system, get_config_params, get_exchange, get_latest_price, print_pending_order, print_hold_assets, print_current_balance
from func_cal import cal_n_order
from func_order import check_orders_status, open_buy_orders

keys_path = '../_keys/kucoin_0_keys.json'
config_system_path = 'config_system.json'
config_params_path = 'config_params.json'
open_orders_df_path = 'open_orders.csv'
transactions_df_path = 'transactions.csv'
assets_df_path = 'assets.csv'

    
def run_bot(idle_stage, keys_path = keys_path, config_params_path = config_params_path, open_orders_df_path = open_orders_df_path, transactions_df_path = transactions_df_path, assets_df_path = assets_df_path):
    bot_name = os.path.basename(os.getcwd())
    exchange = get_exchange(keys_path)
    open_orders_df = pd.read_csv(open_orders_df_path)
    transactions_df = pd.read_csv(transactions_df_path)
    symbol, budget, grid, value, min_price, max_price, fee_percent, start_market = get_config_params(config_params_path)
    latest_price = get_latest_price(exchange, symbol)
    open_orders_df, transactions_df = check_orders_status(exchange, bot_name, 'buy', symbol, grid, latest_price, fee_percent, open_orders_df, transactions_df)
    time.sleep(idle_stage)
    open_orders_df, transactions_df = check_orders_status(exchange, bot_name, 'sell', symbol, grid, latest_price, fee_percent, open_orders_df, transactions_df)
    time.sleep(idle_stage)
    print_pending_order(symbol, open_orders_df)
    latest_price = get_latest_price(exchange, symbol)
    n_order, n_sell_order, n_open_order = cal_n_order(open_orders_df, budget, value)
    open_orders_df, transactions_df = open_buy_orders(exchange, n_order, n_sell_order, n_open_order, symbol, grid, value, latest_price, fee_percent, min_price, max_price, start_market, open_orders_df, transactions_df)
    print_hold_assets(symbol, grid, latest_price, open_orders_df)
    print_current_balance(exchange, symbol, latest_price)
    
    return open_orders_df, transactions_df

if __name__ == "__main__":
    loop_flag = True
    while loop_flag == True:
        print('start loop')
        loop_flag, idle_stage, idle_loop = get_config_system(config_system_path)
        open_orders_df, transactions_df = run_bot(idle_stage)
        open_orders_df.to_csv(open_orders_df_path, index = False)
        transactions_df.to_csv(transactions_df_path, index = False)
        print('end loop')
        time.sleep(idle_loop)
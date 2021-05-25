import pandas as pd
import time
import os

from func_get import get_config_system, get_config_params, get_exchange, get_latest_price, get_random, print_pending_order, print_current_balance
from func_order import check_open_orders, rebalance_port


keys_path = '../_keys/kucoin_0_keys.json'
config_system_path = 'config_system.json'
config_params_path = 'config_params.json'
open_orders_df_path = 'open_orders.csv'
transactions_df_path = 'transactions.csv'


def run_bot(idle_stage, keys_path, config_params_path = config_params_path, open_orders_df_path = open_orders_df_path, transactions_df_path = transactions_df_path):
    bot_name = os.path.basename(os.getcwd())
    exchange = get_exchange(keys_path)
    open_orders_df = pd.read_csv(open_orders_df_path)
    transactions_df = pd.read_csv(transactions_df_path)
    symbol, fix_value, min_value = get_config_params(config_params_path)
    open_orders_df, transactions_df, cont_flag = check_open_orders(exchange, bot_name, symbol, open_orders_df, transactions_df)
    time.sleep(idle_stage)
    print_pending_order(symbol, open_orders_df)
    latest_price = get_latest_price(exchange, symbol)
    
    if cont_flag == 1:
        rebalance_port(exchange, symbol, fix_value, min_value, latest_price, open_orders_df)

    print_current_balance(exchange, symbol, latest_price)
    
    return open_orders_df, transactions_df


if __name__ == "__main__":
    loop_flag = True
    while loop_flag == True:
        print('start loop')
        loop_flag, idle_stage, min_idle, max_idle, keys_path = get_config_system(config_system_path)
        open_orders_df, transactions_df = run_bot(idle_stage, keys_path)
        open_orders_df.to_csv(open_orders_df_path, index = False)
        transactions_df.to_csv(transactions_df_path, index = False)
        print('end loop')
        idle_loop = get_random(min_idle, max_idle)
        time.sleep(idle_loop)
import ccxt
import pandas as pd
from dateutil.relativedelta import relativedelta
import sys

import func_get
import func_cal
import func_update
import func_noti


def gen_fix_sequence(idel_sequence=10):
    sequence = [idel_sequence]

    return sequence


def gen_hexa_sequence(n=18, limit_min=4):
    def hexa(n) :
        if n in range(6):
            return 0
        elif n == 6:
            return 1
        else:
            return (hexa(n - 1) +
                    hexa(n - 2) +
                    hexa(n - 3) +
                    hexa(n - 4) +
                    hexa(n - 5) +
                    hexa(n - 6))
    
    sequence = []
    for i in range(6, n):
        sequence.append(hexa(i))
        
    sequence = [x for x in sequence if x >= limit_min]
    
    if len(sequence) == 0:
        print("No sequence generated, increase n size!!!")
        sys.exit(1)
        
    return sequence


def get_cash_flow_rebalance(date, profit_df_path):
    profit_df = pd.read_csv(profit_df_path)
    ref_profit_df = profit_df[pd.to_datetime(profit_df['timestamp']).dt.date == date]
    cash_flow = sum(ref_profit_df['profit'])

    return cash_flow


def get_total_value(exchange, config_params):
    total_value = 0
    value_dict = {}
    
    for symbol in config_params['symbol']:
        last_price = func_get.get_last_price(exchange, symbol)
        sub_value = func_get.get_base_currency_value(last_price, exchange, symbol)
        
        value_dict[symbol] = {
            'current_value': sub_value
            }

        if '-PERP' not in symbol:
            total_value += sub_value

    return total_value, value_dict


def cal_fix_value(exchange, symbol, config_params, transfer_path, profit_df_path, cash_flow_df_path):
    if config_params['weight'] == 'ratio':
        base_budget = config_params['budget']
    elif config_params['weight'] == 'value':
        transfer = func_get.get_json(transfer_path)
        cash_flow_df = pd.read_csv(cash_flow_df_path)
        cur_date = func_get.get_date()

        total_value, _ = get_total_value(exchange, config_params)

        cash_flow = get_cash_flow_rebalance(cur_date, profit_df_path)
        funding_payment = func_get.get_funding_payment(exchange, range='today')
        reserve = func_get.get_reserve(transfer, cash_flow_df)
        available_cash = func_cal.cal_available_cash(exchange, cash_flow, funding_payment, reserve, config_params, transfer)
        
        base_budget = total_value + available_cash

    fix_value = base_budget * config_params['symbol'][symbol]

    return fix_value


def update_order_loop(order_loop, sequence, last_loop, last_loop_path):
    order_loop += 1
    if order_loop >= len(sequence):
        order_loop = 0

    last_loop['order_loop'] = order_loop

    func_update.update_json(last_loop, last_loop_path)


def update_sequence_loop(config_params, last_loop_path):
    last_loop = func_get.get_json(last_loop_path)

    if config_params['sequence_rule'] == 'fix':
        sequence = gen_fix_sequence()
    elif config_params['sequence_rule'] == 'hexa':
        sequence = gen_hexa_sequence()

    order_loop = last_loop['order_loop']
    sequence_loop = sequence[order_loop]
    
    update_order_loop(order_loop, sequence, last_loop, last_loop_path)

    timestamp = func_get.get_time()
    last_loop['last_rebalance_timestamp'] = str(timestamp)
    last_loop['next_rebalance_timestamp'] = str(timestamp + relativedelta(seconds=sequence_loop))

    func_update.update_json(last_loop, last_loop_path)


def reset_order_loop(last_loop_path):
    last_loop = func_get.get_json(last_loop_path)
    last_loop['order_loop'] = 0
    last_loop['last_rebalance_timestamp'] = 0
    last_loop['next_rebalance_timestamp'] = 0

    func_update.update_json(last_loop, last_loop_path)


def update_budget(transfer, config_params, config_params_path, last_loop_path):
    net_transfer = transfer['deposit'] - transfer['withdraw']

    if net_transfer != 0:
        config_params['budget'] += net_transfer

        last_loop = func_get.get_json(last_loop_path)
        last_loop['transfer_flag'] = 1

        func_update.update_json(config_params, config_params_path)
        func_update.update_json(last_loop, last_loop_path)


def append_profit_rebalance(sell_order, exchange, exe_amount, symbol, config_system, queue_df, profit_df_path):
    timestamp = func_get.get_time()
    profit_df = pd.read_csv(profit_df_path)

    buy_id = queue_df['order_id'][len(queue_df) - 1]
    sell_id = sell_order['id']
    buy_price = queue_df['price'][len(queue_df) - 1]

    # Sell order fee currency is always USD.
    fee, _ = func_get.get_order_fee(sell_order, exchange, symbol, config_system)
    sell_price = func_cal.cal_adjusted_price(sell_order, fee, side='sell')
    profit = exe_amount * (sell_price - buy_price)

    profit_df.loc[len(profit_df)] = [timestamp, buy_id, sell_id, symbol, exe_amount, buy_price, sell_price, profit]
    profit_df.to_csv(profit_df_path, index=False)


def update_average_cost(added_amount, add_price, exchange, symbol, last_loop_path):
    last_loop = func_get.get_json(last_loop_path)

    total_amount = func_get.get_base_currency_amount(exchange, symbol)
    hold_amount = total_amount - added_amount
    hold_price = last_loop['symbol'][symbol]['average_cost']

    average_price, _ = cal_average_price(hold_amount, hold_price, added_amount, add_price)
    last_loop['symbol'][symbol]['average_cost'] = average_price
    
    func_update.update_json(last_loop, last_loop_path)


def update_hold_cost(added_amount, add_price, timestamp, queue_df):
    hold_amount = queue_df.loc[0, 'amount']
    hold_price = queue_df.loc[0, 'price']

    average_price, new_hold_amount = cal_average_price(hold_amount, hold_price, added_amount, add_price)

    queue_df.loc[0, 'timestamp'] = timestamp
    queue_df.loc[0, 'amount'] = new_hold_amount
    queue_df.loc[0, 'price'] = average_price

    return queue_df


def update_hold(buy_order, exchange, symbol, config_system, last_loop_path, queue_df_path):
    timestamp = func_get.get_time()
    queue_df = pd.read_csv(queue_df_path)

    base_currency, quote_currency = func_get.get_currency(buy_order['symbol'])
    fee, fee_currency = func_get.get_order_fee(buy_order, exchange, symbol, config_system)

    if fee_currency == quote_currency:
        buy_amount = buy_order['filled']
        buy_price = func_cal.cal_adjusted_price(buy_order, fee, side='buy')
    elif fee_currency == base_currency:
        buy_amount = buy_order['filled'] - fee
        buy_price = buy_order['price']

    update_average_cost(buy_amount, buy_price, exchange, symbol, last_loop_path)
    queue_df = update_hold_cost(buy_amount, buy_price, timestamp, queue_df)
    queue_df.to_csv(queue_df_path, index=False)


def append_queue(buy_order, exchange, config_system, last_loop_path, queue_df_path):
    timestamp = func_get.get_time()
    queue_df = pd.read_csv(queue_df_path)

    base_currency, quote_currency = func_get.get_currency(buy_order['symbol'])
    fee, fee_currency = func_get.get_order_fee(buy_order, exchange, buy_order['symbol'], config_system)

    if fee_currency == quote_currency:
        buy_price = func_cal.cal_adjusted_price(buy_order, fee, side='buy')
        buy_amount = buy_order['filled']
        added_queue = buy_order['filled']
    elif fee_currency == base_currency:
        buy_price = buy_order['price']
        buy_amount = buy_order['filled'] - fee

        if len(queue_df) > 0:
            added_queue = float(exchange.amount_to_precision(buy_order['symbol'], buy_amount))
            added_hold_amount = buy_amount - added_queue
            queue_df = update_hold_cost(added_hold_amount, buy_price, timestamp, queue_df)
        else:
            # Fist loop.
            added_queue = buy_amount

    update_average_cost(buy_amount, buy_price, exchange, buy_order['symbol'], last_loop_path)
    queue_df.loc[len(queue_df)] = [timestamp, buy_order['id'], added_queue, buy_price]
    queue_df.to_csv(queue_df_path, index=False)


def update_queue(sell_order, exchange, method, amount_key, symbol, config_system, queue_df_path, profit_df_path):
    sell_amount = sell_order[amount_key]

    while sell_amount > 0:
        queue_df = pd.read_csv(queue_df_path)
        
        if method == 'fifo':
            order_index = 0
        elif method == 'lifo':
            order_index = len(queue_df) - 1
    
        sell_queue = queue_df['amount'][order_index]
        exe_amount = min(sell_amount, sell_queue)
        remaining_queue = sell_queue - exe_amount

        if method == 'lifo':
            append_profit_rebalance(sell_order, exchange, exe_amount, symbol, config_system, queue_df, profit_df_path)
        
        if remaining_queue == 0:
            queue_df = queue_df.drop([order_index]).reset_index(drop=True)
        else:
            queue_df.loc[order_index, 'amount'] = remaining_queue

        queue_df.to_csv(queue_df_path, index=False)
        sell_amount -= exe_amount


def manage_queue(order, method, exchange, symbol, config_system, last_loop_path, queue_df_path, profit_df_path):
    base_currency, _ = func_get.get_currency(symbol)

    if (order['side'] == 'buy') & (method == 'lifo'):
        append_queue(order, exchange, config_system ,last_loop_path, queue_df_path.format(base_currency))
    elif (order['side'] == 'buy') & (method == 'fifo'):
        update_hold(order, exchange, symbol, config_system, last_loop_path, queue_df_path.format(base_currency))
    elif order['side'] == 'sell':
        update_queue(order, exchange, method, 'filled', symbol, config_system, queue_df_path.format(base_currency), profit_df_path)


def cal_average_price(hold_amount, hold_price, added_amount, add_price):
    new_hold_amount = hold_amount + added_amount
    average_price = ((hold_amount * hold_price) + (added_amount * add_price)) / new_hold_amount

    return average_price, new_hold_amount


def cal_min_value(exchange, symbol, grid_percent, last_loop_path):
    last_loop = func_get.get_json(last_loop_path)

    amount = func_get.get_base_currency_amount(exchange, symbol)
    grid = last_loop['symbol'][symbol]['last_action_price'] * (grid_percent / 100)
    min_value = grid * amount

    return min_value


def get_rebalance_time_flag(last_loop_path):
    last_loop = func_get.get_json(last_loop_path)
    timestamp = func_get.get_time()

    if last_loop['next_rebalance_timestamp'] == 0:
        # First loop.
        rebalance_time_flag = True
    elif timestamp >= pd.to_datetime(last_loop['next_rebalance_timestamp']):
        rebalance_time_flag = True
    else:
        rebalance_time_flag = False

    return rebalance_time_flag


def get_rebalance_budget_flag(exchange, config_params, transfer_path, profit_df_path, cash_flow_df_path):
    transfer = func_get.get_json(transfer_path)
    cash_flow_df = pd.read_csv(cash_flow_df_path)

    cur_date = func_get.get_date()
    cash_flow = get_cash_flow_rebalance(cur_date, profit_df_path)
    funding_payment = func_get.get_funding_payment(exchange, range='today')
    reserve = func_get.get_reserve(transfer, cash_flow_df)

    available_cash = func_cal.cal_available_cash(exchange, cash_flow, funding_payment, reserve, config_params, transfer)

    if available_cash > 0:
        rebalance_budget_flag = 1
    else:
        rebalance_budget_flag = 0
        print("Not available cash!!!")

    return rebalance_budget_flag


def get_rebalance_flag(exchange, config_params, last_loop_path, transfer_path, profit_df_path, cash_flow_df_path):
    rebalance_time_flag = get_rebalance_time_flag(last_loop_path)
    rebalance_budget_flag = get_rebalance_budget_flag(exchange, config_params, transfer_path, profit_df_path, cash_flow_df_path)

    if rebalance_time_flag & rebalance_budget_flag:
        rebalance_flag = True
    else:
        rebalance_flag = False

    return rebalance_flag

    
def get_rebalance_action(exchange, symbol, config_params, last_loop_path, transfer_path, profit_df_path, cash_flow_df_path):
    last_price = func_get.get_last_price(exchange, symbol)
    min_value = cal_min_value(exchange, symbol, config_params['grid_percent'], last_loop_path)
    fix_value = cal_fix_value(exchange, symbol, config_params, transfer_path, profit_df_path, cash_flow_df_path)

    bid_price = func_get.get_bid_price(exchange, symbol)
    ask_price = func_get.get_ask_price(exchange, symbol)
    bid_current_value = func_get.get_base_currency_value(bid_price, exchange, symbol)
    ask_current_value = func_get.get_base_currency_value(ask_price, exchange, symbol)

    print(f"Last price: {last_price} USD")
    print(f"Fix value: {fix_value} USD")
    print(f"Min value: {min_value} USD")
    print(f"Bid current value: {bid_current_value} USD")
    print(f"Ask current value: {ask_current_value} USD")

    if bid_current_value < fix_value - min_value:
        action_flag = True
        side = 'buy'
        diff_value = fix_value - bid_current_value
        price = bid_price
        print(f"Send buy order")
    elif ask_current_value > fix_value + min_value:
        action_flag = True
        side = 'sell'
        diff_value = ask_current_value - fix_value
        price = ask_price
        print(f"Send sell order")
    else:
        action_flag = False
        side = None
        diff_value = None
        price = None
        print("No action")

    return action_flag, side, diff_value, price


def get_clear_method(last_loop_path):
    last_loop = func_get.get_json(last_loop_path)

    if last_loop['transfer_flag'] == 1:
        method = 'fifo'
        order_remark = 'transfer'
        last_loop['transfer_flag'] = 0
        func_update.update_json(last_loop, last_loop_path)
    else:
        method = 'lifo'
        order_remark = 'close_order'

    return method, order_remark


def create_order(exchange, symbol, order_type, side, amount, price=None):
    if order_type == 'limit':
        order = exchange.create_order(symbol, 'limit', side, amount, price, params={'postOnly': True})
    elif order_type == 'market':
        order = exchange.create_order(symbol, 'market', side, amount)

    return order


def send_order(exchange, symbol, side, amount, price, config_params, last_loop_path, open_orders_df_path):
    last_loop = func_get.get_json(last_loop_path)

    if last_loop['transfer_flag'] == 1:
        order = create_order(exchange, symbol, 'market', side, amount)
    else:
        order = create_order(exchange, symbol, config_params['order_type'], side, amount, price)

    func_update.append_order(order, 'amount', 'open_order', open_orders_df_path)


def resend_order(order, exchange, symbol, config_params, last_loop_path, transfer_path, open_orders_df_path, profit_df_path, cash_flow_df_path):
    print(f"Resend {order['symbol']}")
    action_flag, side, diff_value, price = get_rebalance_action(exchange, symbol, config_params, last_loop_path, transfer_path, profit_df_path, cash_flow_df_path)

    if action_flag & (side == order['side']):
        amount = diff_value / price
        rounded_amount = func_cal.round_amount(amount, exchange, symbol, round_direction='down')
    else:
        rounded_amount = 0

    if rounded_amount > 0:
        order = create_order(exchange, symbol, config_params['order_type'], side, rounded_amount, price)
        func_update.append_order(order, 'amount', 'resend_order', open_orders_df_path)


def check_cancel_order(order, exchange, config_params, last_loop_path, transfer_path, open_orders_df_path, profit_df_path, cash_flow_df_path, resend_flag):
    if order['status'] != 'closed':
        try:
            exchange.cancel_order(order['id'])
        except ccxt.InvalidOrder:
            # The order has already been closed by postOnly param.
            pass

        if (resend_flag == True) & (order['remaining'] > 0):
            resend_order(order, exchange, order['symbol'], config_params, last_loop_path, transfer_path, open_orders_df_path, profit_df_path, cash_flow_df_path)


def clear_orders_rebalance(exchange, bot_name, config_system, config_params, last_loop_path, transfer_path, open_orders_df_path, transactions_df_path, queue_df_path, profit_df_path, cash_flow_df_path, resend_flag):
    open_orders_df = pd.read_csv(open_orders_df_path)
    method, order_remaerk = get_clear_method(last_loop_path)

    for order_id in open_orders_df['order_id'].unique():
        symbol = open_orders_df.loc[open_orders_df['order_id'] == order_id, 'symbol'].item()
        
        order = exchange.fetch_order(order_id, symbol)
        check_cancel_order(order, exchange, config_params, last_loop_path, transfer_path, open_orders_df_path, profit_df_path, cash_flow_df_path, resend_flag)

        if order['filled'] > 0:
            manage_queue(order, method, exchange, symbol, config_system, last_loop_path, queue_df_path, profit_df_path)

            last_loop = func_get.get_json(last_loop_path)
            last_loop['symbol'][symbol]['last_action_price'] = order['price']

            func_update.append_order(order, 'filled', order_remaerk, transactions_df_path)
            func_update.update_json(last_loop, last_loop_path)
            func_noti.noti_success_order(order, bot_name, symbol)

        func_update.remove_order(order_id, open_orders_df_path)


def rebalance(exchange, symbol, config_params, last_loop_path, transfer_path, open_orders_df_path, profit_df_path, cash_flow_df_path):
    print(f"Rebalance {symbol}")

    base_currency, _ = func_get.get_currency(symbol)
    action_flag, side, diff_value, price = get_rebalance_action(exchange, symbol, config_params, last_loop_path, transfer_path, profit_df_path, cash_flow_df_path)

    if action_flag:
        amount = diff_value / price
        rounded_amount = func_cal.round_amount(amount, exchange, symbol, round_direction='down')

        if rounded_amount > 0:
            print(f"Diff value: {diff_value} USD")
            send_order(exchange, symbol, side, rounded_amount, price, config_params, last_loop_path, open_orders_df_path)
        else:
            print(f"Cannot {side} {diff_value} value, {amount} {base_currency} is too small amount to place order!!!")


def update_end_date_rebalance(prev_date, exchange, config_system, config_params, config_params_path, last_loop_path, transfer_path, profit_df_path, cash_flow_df_path):
    cash_flow_df = pd.read_csv(cash_flow_df_path)
    transfer = func_get.get_json(transfer_path)
    
    symbol_list = list(config_params['symbol'])
    total_value, _ = get_total_value(exchange, config_params)
    cash = func_get.get_quote_currency_value(exchange, symbol_list[0])

    end_balance = func_cal.cal_end_balance(total_value, cash, transfer)
    end_cash = func_cal.cal_end_cash(cash, transfer)

    cash_flow = get_cash_flow_rebalance(prev_date, profit_df_path)
    funding_payment, _ = func_get.get_funding_payment(exchange, range='end_date')
    net_cash_flow = cash_flow - funding_payment

    reserve = func_get.get_reserve(transfer, cash_flow_df)
    reserve += net_cash_flow

    cash_flow_list = [
        prev_date,
        config_params['budget'],
        end_balance,
        end_cash,
        cash_flow,
        funding_payment,
        net_cash_flow,
        transfer['deposit'],
        transfer['withdraw'],
        transfer['withdraw_reserve'],
        reserve
        ]
    
    func_update.append_csv(cash_flow_list, cash_flow_df, cash_flow_df_path)
    update_budget(transfer, config_params, config_params_path, last_loop_path)
    func_update.update_transfer(config_system['taker_fee_percent'], transfer_path)
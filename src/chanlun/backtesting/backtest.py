import copy
import datetime
import os
import pickle
import time
import traceback
import numpy as np
import pandas as pd

import prettytable as pt
from pyecharts import options as opts
from pyecharts.charts import Line, Bar, Grid

from chanlun import cl, kcharts, fun
from chanlun.backtesting.backtest_klines import BackTestKlines
from chanlun.backtesting.backtest_trader import BackTestTrader
from chanlun.backtesting.base import POSITION
from chanlun.cl_interface import *


class BackTest:
    """
    回测类
    """

    def __init__(self, config: dict = None):
        # 日志记录
        self.log = fun.get_logger()

        if config is None:
            return
        check_keys = ['mode', 'market', 'base_code', 'codes', 'frequencys',
                      'start_datetime', 'end_datetime',
                      'init_balance', 'fee_rate', 'max_pos',
                      'cl_config', 'is_stock', 'is_futures', 'strategy']
        for _k in check_keys:
            if _k not in config.keys():
                raise Exception(f'回测配置缺少必要参数:{_k}')

        self.mode = config['mode']
        self.market = config['market']
        self.base_code = config['base_code']
        self.codes = config['codes']
        self.frequencys = config['frequencys']
        self.start_datetime = config['start_datetime']
        self.end_datetime = config['end_datetime']

        self.init_balance = config['init_balance']
        self.fee_rate = config['fee_rate']
        self.max_pos = config['max_pos']

        self.cl_config = config['cl_config']
        self.is_stock = config['is_stock']
        self.is_futures = config['is_futures']

        # 执行策略
        self.strategy = config['strategy']

        self.save_file = config.get('save_file')

        # 交易对象
        self.trader = BackTestTrader(
            '回测', self.mode,
            is_stock=self.is_stock, is_futures=self.is_futures,
            init_balance=self.init_balance, fee_rate=self.fee_rate, max_pos=self.max_pos,
            log=self.log.info
        )
        self.trader.set_strategy(self.strategy)
        self.datas = BackTestKlines(
            self.market, self.start_datetime, self.end_datetime, self.frequencys, self.cl_config
        )
        self.trader.set_data(self.datas)

        # 回测循环加载下次周期，默认None 为回测最小周期
        self.next_frequency = None

    def save(self):
        """
        保存回测结果到配置的文件中
        """
        if self.save_file is None:
            return
        save_dict = {
            'save_file': self.save_file,
            'mode': self.mode,
            'market': self.market,
            'base_code': self.base_code,
            'codes': self.codes,
            'frequencys': self.frequencys,
            'start_datetime': self.start_datetime,
            'end_datetime': self.end_datetime,
            'init_balance': self.init_balance,
            'fee_rate': self.fee_rate,
            'max_pos': self.max_pos,
            'cl_config': self.cl_config,
            'is_stock': self.is_stock,
            'is_futures': self.is_futures,
            'strategy': self.strategy,
            'trader': self.trader,
            'next_frequency': self.next_frequency,
        }
        # 保存策略结果到 file 中，进行页面查看
        self.log.info(f'save to : {self.save_file}')
        with open(file=self.save_file, mode='wb') as file:
            pickle.dump(save_dict, file)

    def load(self, _file: str):
        """
        从指定的文件中恢复回测结果
        """
        file = open(file=_file, mode='rb')
        config_dict = pickle.load(file)
        self.save_file = config_dict['save_file']
        self.mode = config_dict['mode']
        self.market = config_dict['market']
        self.base_code = config_dict['base_code']
        self.codes = config_dict['codes']
        self.frequencys = config_dict['frequencys']
        self.start_datetime = config_dict['start_datetime']
        self.end_datetime = config_dict['end_datetime']
        self.init_balance = config_dict['init_balance']
        self.fee_rate = config_dict['fee_rate']
        self.max_pos = config_dict['max_pos']
        self.cl_config = config_dict['cl_config']
        self.is_stock = config_dict['is_stock']
        self.is_futures = config_dict['is_futures']
        self.strategy = config_dict['strategy']
        self.trader = config_dict['trader']
        self.next_frequency = config_dict['next_frequency']
        self.datas = BackTestKlines(
            self.market, self.start_datetime, self.end_datetime, self.frequencys, self.cl_config
        )
        self.log.info('Load OK')
        return

    def info(self):
        """
        输出回测信息
        """
        self.log.info(fun.now_dt())
        self.log.info(f'Save File : {self.save_file}')
        self.log.info(f'Mode {self.mode} init balance {self.init_balance} fee rate {self.fee_rate}')
        self.log.info(f'is stock {self.is_stock} is futures {self.is_futures}')
        self.log.info(f'STR Class : {self.strategy}')
        self.log.info(f'Base Code : {self.base_code}')
        self.log.info(f'Run Codes : {self.codes}')
        self.log.info(f'Frequencys : {self.frequencys}')
        self.log.info(f'Start time : {self.start_datetime} End time : {self.end_datetime}')
        self.log.info(f'CL Config : {self.cl_config}')
        return True

    def run(self, next_frequency: str = None):
        """
        执行回测
        """
        if next_frequency is None:
            next_frequency = self.frequencys[-1]

        self.next_frequency = next_frequency
        self.datas.init(self.base_code, next_frequency)

        _st = time.time()

        while True:
            is_ok = self.datas.next()
            if is_ok is False:
                break
            # 更新持仓盈亏与资金变化
            self.trader.update_position_record()
            for code in self.codes:
                try:
                    self.trader.run(code)
                except Exception:
                    self.log.info(f'执行 {code} 异常')
                    self.log.info(traceback.format_exc())

        # 清空持仓
        self.trader.end()
        self.trader.datas = None
        _et = time.time()

        self.log.info(f'运行完成，执行时间：{_et - _st}')
        return True

    def show_charts(self, code, frequency, change_cl_config=None, show_futu='macd'):
        """
        显示指定代码指定周期的图表
        """
        # 根据配置中指定的缠论配置进行展示图表
        if frequency in self.cl_config.keys():
            cl_config = self.cl_config[frequency]
        elif 'default' in self.cl_config.keys():
            cl_config = self.cl_config['default']
        else:
            cl_config = self.cl_config

        # 根据传递的参数，暂时修改其缠论配置
        if change_cl_config is None:
            change_cl_config = {}
        show_cl_config = copy.deepcopy(cl_config)
        for _i, _v in change_cl_config.items():
            show_cl_config[_i] = _v

        # 获取行情数据（回测周期内所有的）
        bk = BackTestKlines(
            self.market, self.start_datetime, self.end_datetime, [frequency], cl_config=show_cl_config
        )
        bk.klines(code, frequency)
        klines = bk.all_klines['%s-%s' % (code, frequency)]
        cd: ICL = cl.CL(code, frequency, show_cl_config).process_klines(klines)
        orders = self.trader.orders[code] if code in self.trader.orders else []
        render = kcharts.render_charts('%s - %s' % (code, frequency), cd, show_futu=show_futu, orders=orders)
        return render

    def result(self):
        """
        输出回测结果
        """

        if self.mode == 'trade':
            # 实际交易所需要看的指标
            # 基准收益率
            base_klines = self.datas.ex.klines(
                self.base_code, self.frequencys[0], start_date=self.start_datetime, end_date=self.end_datetime,
                args={'limit': None}
            )
            base_open = float(base_klines.iloc[0]['open'])
            base_close = float(base_klines.iloc[-1]['close'])

            # 每年交易日设置
            annual_days = 240 if self.market in ['a', 'us', 'hk' 'futures'] else 365
            # 无风险收益率
            risk_free = 0.03

            # 按照日期聚合资产变化
            new_day_balances = {}
            for dt, b in self.trader.balance_history.items():
                day = fun.str_to_datetime(fun.datetime_to_str(fun.str_to_datetime(dt), '%Y-%m-%d'), '%Y-%m-%d')
                new_day_balances[day] = b
            df = pd.DataFrame.from_dict(new_day_balances, orient='index', columns=['balance'])
            df.index.name = 'date'
            pre_balance = df["balance"].shift(1)
            pre_balance.iloc[0] = self.init_balance
            x = df["balance"] / pre_balance
            x[x <= 0] = np.nan
            df["return"] = np.log(x).fillna(0)
            df["highlevel"] = (
                df["balance"].rolling(
                    min_periods=1, window=len(df), center=False).max()
            )
            df["drawdown"] = df["balance"] - df["highlevel"]
            df["ddpercent"] = df["drawdown"] / df["highlevel"] * 100
            # Calculate statistics value
            start_date = df.index[0]
            end_date = df.index[-1]
            total_days = len(df)
            end_balance = df["balance"].iloc[-1]
            max_drawdown = df["drawdown"].min()
            max_ddpercent = df["ddpercent"].min()
            max_drawdown_end = df["drawdown"].idxmin()
            if isinstance(max_drawdown_end, datetime.datetime):
                max_drawdown_start = df["balance"][:max_drawdown_end].idxmax()
                max_drawdown_duration = (max_drawdown_end - max_drawdown_start).days
            else:
                max_drawdown_duration = 0

            total_return = (end_balance / self.init_balance - 1) * 100
            annual_return = total_return / total_days * annual_days
            daily_return = df["return"].mean() * 100
            return_std = df["return"].std() * 100

            if return_std:
                daily_risk_free = risk_free / np.sqrt(annual_days)
                sharpe_ratio = (daily_return - daily_risk_free) / return_std * np.sqrt(annual_days)
            else:
                sharpe_ratio = 0

            return_drawdown_ratio = -total_return / max_ddpercent

            # 总的手续费
            total_fee = self.trader.fee_total
            base_year_rate = (base_close / base_open - 1) / total_days * annual_days * 100

            print(f'首个交易日：{start_date} 最后交易日：{end_date} 总交易日：{total_days}')
            print(f'起始资金：{self.init_balance} 结束资金：{end_balance:,.2f} 总手续费：{total_fee:,.2f}')
            print('基准收益率：%.2f%%  基准年化收益：%.2f%%' % ((base_close - base_open) / base_open * 100, base_year_rate))
            print(f'总收益率：{total_return:,.2f}% 年化收益率：{annual_return:,.2f}%')
            print(f'最大回撤：{max_drawdown:,.2f} 百分比最大回撤：{max_ddpercent:,.2f}% 最长回撤天数：{max_drawdown_duration}')
            print(
                f'日均收益率：{daily_return:,.2f}% 收益标准差：{return_std:,.2f}% Sharpe Ratio: {sharpe_ratio:,.2f} 收益回撤比：{return_drawdown_ratio:,.2f} '
            )

        tb = pt.PrettyTable()
        tb.field_names = ["买卖点", "成功", "失败", '胜率', "盈利", '亏损', '净利润', '回吐比例', '平均盈利', '平均亏损', '盈亏比']

        mmds = {
            '1buy': '一类买点', '2buy': '二类买点', 'l2buy': '类二类买点', '3buy': '三类买点', 'l3buy': '类三类买点',
            'down_pz_bc_buy': '下跌盘整背驰', 'down_qs_bc_buy': '下跌趋势背驰',
            '1sell': '一类卖点', '2sell': '二类卖点', 'l2sell': '类二类卖点', '3sell': '三类卖点', 'l3sell': '类三类卖点',
            'up_pz_bc_sell': '上涨盘整背驰', 'up_qs_bc_sell': '上涨趋势背驰',
        }
        for k in self.trader.results.keys():
            mmd = mmds[k]
            win_num = self.trader.results[k]['win_num']
            loss_num = self.trader.results[k]['loss_num']
            shenglv = 0 if win_num == 0 and loss_num == 0 else win_num / (win_num + loss_num) * 100
            win_balance = self.trader.results[k]['win_balance']
            loss_balance = self.trader.results[k]['loss_balance']
            net_balance = win_balance - loss_balance
            back_rate = 0 if win_balance == 0 else loss_balance / win_balance * 100
            win_mean_balance = 0 if win_num == 0 else win_balance / win_num
            loss_mean_balance = 0 if loss_num == 0 else loss_balance / loss_num
            ykb = 0 if loss_mean_balance == 0 or win_mean_balance == 0 else win_mean_balance / loss_mean_balance

            tb.add_row(
                [mmd, win_num, loss_num, f'{str(round(shenglv, 2))}%', round(win_balance, 2), round(loss_balance, 2),
                 round(net_balance, 2), round(back_rate, 2), round(win_mean_balance, 2), round(loss_mean_balance, 2),
                 round(ykb, 4)])

        return tb

    def backtest_charts(self):
        """
        输出盈利图表
        """
        base_prices = {'datetime': [], 'val': []}
        balance_history = {'datetime': [], 'val': []}
        net_profit_history = {'datetime': [], 'val': []}
        hold_profit_history = {'datetime': [], 'val': []}
        hold_num_history = {'datetime': [], 'val': []}

        # 获取所有的交易日期节点
        base_klines = self.datas.ex.klines(
            self.base_code, self.next_frequency, start_date=self.start_datetime, end_date=self.end_datetime,
            args={'limit': None}
        )
        dts = list(base_klines['date'].to_list())
        base_prices['val'] = list(base_klines['close'].to_list())

        # 获取所有的持仓历史，并按照平仓时间排序
        positions: List[POSITION] = []
        for _code in self.trader.positions_history:
            positions.extend(iter(self.trader.positions_history[_code]))
        positions = sorted(positions, key=lambda p: p.close_datetime, reverse=False)

        # 按照平仓时间统计其中的收益总和
        dts_total_nps = {}
        for _p in positions:
            net_profit = (_p.profit_rate / 100) * _p.balance
            if _p.close_datetime not in dts_total_nps.keys():
                dts_total_nps[_p.close_datetime] = net_profit
            else:
                dts_total_nps[_p.close_datetime] += net_profit

        # 按照时间统计当前时间持仓累计盈亏
        _hold_profit_sums = {}
        _hold_num_sums = {}
        for _code, _hp in self.trader.hold_profit_history.items():
            for _dt, _p in _hp.items():
                if _dt not in _hold_profit_sums.keys():
                    _hold_profit_sums[_dt] = _p
                    _hold_num_sums[_dt] = 1 if _p != 0 else 0
                else:
                    _hold_profit_sums[_dt] += _p
                    _hold_num_sums[_dt] += 1 if _p != 0 else 0

        # 按照时间累加总的收益
        total_np = 0
        for _dt in dts:
            _dt = _dt.strftime('%Y-%m-%d %H:%M:%S')

            base_prices['datetime'].append(_dt)

            # 资金余额
            if _dt in self.trader.balance_history.keys():
                balance_history['datetime'].append(_dt)
                balance_history['val'].append(self.trader.balance_history[_dt])
            else:
                balance_history['datetime'].append(_dt)
                balance_history['val'].append(balance_history['val'][-1] if len(balance_history['val']) > 0 else 0)

            # 累计净收益数据
            if _dt in dts_total_nps.keys():
                total_np += dts_total_nps[_dt]
            net_profit_history['datetime'].append(_dt)
            net_profit_history['val'].append(total_np)

            # 当前时间持仓累计
            hold_profit_history['datetime'].append(_dt)
            if _dt in _hold_profit_sums.keys():
                hold_profit_history['val'].append(_hold_profit_sums[_dt])
            else:
                hold_profit_history['val'].append(0)

            # 当前时间持仓数量
            hold_num_history['datetime'].append(_dt)
            if _dt in _hold_num_sums.keys():
                hold_num_history['val'].append(_hold_num_sums[_dt])
            else:
                hold_num_history['val'].append(0)

        return self.__create_backtest_charts(
            base_prices, balance_history, net_profit_history, hold_profit_history, hold_num_history
        )

    def positions(self, code=None, add_columns=None):
        """
        输出历史持仓信息
        如果 code 为 str 返回 特定 code 的数据
        """
        pos_objs = []

        for _code in self.trader.positions_history.keys():
            if code is not None and _code != code:
                continue
            for p in self.trader.positions_history[_code]:
                p_obj = {
                    'code': _code,
                    'mmd': p.mmd,
                    'open_datetime': p.open_datetime,
                    'close_datetime': p.close_datetime,
                    'type': p.type,
                    'price': p.price,
                    'amount': p.amount,
                    'loss_price': p.loss_price,
                    'profit_rate': p.profit_rate,
                    'max_profit_rate': p.max_profit_rate,
                    'max_loss_rate': p.max_loss_rate,
                    'open_msg': p.open_msg,
                    'close_msg': p.close_msg,
                }
                if add_columns is not None:
                    for _col in add_columns:
                        p_obj[_col] = p.info[_col]
                pos_objs.append(p_obj)

        return pd.DataFrame(pos_objs)

    def orders(self, code: str = None):
        """
        输出订单列表
        如果 code 返回 特定 code 的数据
        """
        order_objs = []
        for _code, orders in self.trader.orders.items():
            if code is not None and _code != code:
                continue
            order_objs.extend(iter(orders))
        return pd.DataFrame(order_objs)

    @staticmethod
    def __orders_pd(trades: List[BackTestTrader]):
        """
        持仓历史转换成 pandas 数据，便于做分析
        """
        order_objs = []
        for td in trades:
            for code, orders in td.orders.items():
                order_objs.extend(iter(orders))
        return pd.DataFrame(order_objs)

    def __create_backtest_charts(self, base_prices, balance_history: dict, net_profit_history: dict,
                                 hold_profit_history: dict,
                                 hold_num_history: dict):
        """
        回测结果图表展示
        :return:
        """
        if self.mode == 'signal':
            main_name = '净收益累计'
            main_x = net_profit_history['datetime']
            main_y = net_profit_history['val']
        else:
            main_name = '资金变化'
            main_x = balance_history['datetime']
            main_y = balance_history['val']

        main_chart = (Line().add_xaxis(
            xaxis_data=main_x
        ).add_yaxis(
            series_name=main_name, y_axis=main_y, label_opts=opts.LabelOpts(is_show=False),
            markpoint_opts=opts.MarkPointOpts(
                data=[
                    opts.MarkPointItem(
                        type_="max", name="最大值", symbol='pin', symbol_size=25,
                        itemstyle_opts=opts.ItemStyleOpts(color="red")
                    ),
                    opts.MarkPointItem(
                        type_="min", name="最小值", symbol='pin', symbol_size=25,
                        itemstyle_opts=opts.ItemStyleOpts(color="green")
                    )
                ], label_opts=opts.LabelOpts(color='black')
            ),
        ).set_global_opts(
            title_opts=opts.TitleOpts(title='回测结果图表展示'),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            yaxis_opts=opts.AxisOpts(position="right", type_='value', min_=min(main_y), max_=max(main_y)),
            legend_opts=opts.LegendOpts(is_show=False),
            datazoom_opts=[
                opts.DataZoomOpts(is_show=False, type_="inside", xaxis_index=[0, 0], range_start=0, range_end=100),
                opts.DataZoomOpts(is_show=True, xaxis_index=[0, 1], pos_top="97%", range_start=0, range_end=100),
                opts.DataZoomOpts(is_show=False, xaxis_index=[0, 2], range_start=0, range_end=100),
            ]
        ))

        base_chart = (Line().add_xaxis(
            xaxis_data=base_prices['datetime']
        ).add_yaxis(
            series_name='基准', y_axis=base_prices['val'], label_opts=opts.LabelOpts(is_show=False)
        ).set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            yaxis_opts=opts.AxisOpts(position="right"),
            legend_opts=opts.LegendOpts(is_show=False),
        ))

        hold_profit_chart = (Bar().add_xaxis(
            xaxis_data=hold_profit_history['datetime']
        ).add_yaxis(
            series_name='持仓盈亏变动', y_axis=hold_profit_history['val'], label_opts=opts.LabelOpts(is_show=False)
        ).set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            yaxis_opts=opts.AxisOpts(position="right"),
            legend_opts=opts.LegendOpts(is_show=False),
        ))

        hold_num_chart = (Bar().add_xaxis(
            xaxis_data=hold_num_history['datetime']
        ).add_yaxis(
            series_name='持仓数', y_axis=hold_num_history['val'], label_opts=opts.LabelOpts(is_show=False)
        ).set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            yaxis_opts=opts.AxisOpts(position="right"),
            legend_opts=opts.LegendOpts(is_show=False),
        ))

        chart = Grid(init_opts=opts.InitOpts(width="90%", height="700px", theme='white'))
        chart.add(
            main_chart,
            grid_opts=opts.GridOpts(width="96%", height="50%", pos_left='1%', pos_right='3%'),
        )

        chart.add(
            base_chart,
            grid_opts=opts.GridOpts(
                height="40%", width="96%", pos_left='1%', pos_right='3%', pos_bottom='20%'
            ),
        )
        chart.add(
            hold_profit_chart,
            grid_opts=opts.GridOpts(
                height="10%", width="96%", pos_left='1%', pos_right='3%', pos_bottom='10%'
            )
        )
        chart.add(
            hold_num_chart,
            grid_opts=opts.GridOpts(
                height="10%", width="96%", pos_left='1%', pos_right='3%', pos_bottom='0%'
            ),
        )
        if "JPY_PARENT_PID" in os.environ:
            return chart.render_notebook()
        else:
            return chart.dump_options()

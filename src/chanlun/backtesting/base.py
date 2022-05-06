import datetime
from abc import ABC
from dataclasses import dataclass

import numpy as np
import talib

from chanlun.cl_interface import *


@dataclass
class POSITION:
    """
    持仓对象
    """
    code: str
    mmd: str
    type: str = None
    balance: float = 0
    price: float = 0
    amount: float = 0
    loss_price: float = None
    open_date: str = None
    open_datetime: str = None
    close_datetime: str = None
    profit_rate: float = 0
    max_profit_rate: float = 0  # 仅供参考，不太精确
    max_loss_rate: float = 0  # 仅供参考，不太精确
    open_msg: str = ''
    close_msg: str = ''
    info: Dict = None


@dataclass
class Operation:
    """
    策略返回的操作指示对象
    """
    opt: str  # 操作指示  buy  买入  sell  卖出
    # 触发指示的
    # 买卖点 例如：1buy  2buy l2buy 3buy l3buy  1sell 2sell l2sell 3sell l3sell down_pz_bc_buy
    # 背驰点 例如：down_pz_bc_buy down_qs_bc_buy up_pz_bc_sell up_qs_bc_sell
    mmd: str
    loss_price: float = None  # 止损价格
    info: Dict[str, object] = None  # 自定义保存的一些信息
    msg: str = ''

    def __str__(self):
        return f'mmd {self.mmd} opt {self.opt} loss_price {self.loss_price} msg: {self.msg}'


class MarketDatas(ABC):
    """
    市场数据类，用于在回测与实盘获取指定行情数据类
    """

    def __init__(self, market: str, frequencys: List[str], cl_config=None):
        """
        初始化
        """
        self.market = market
        self.frequencys = frequencys
        self.cl_config = cl_config

        # 按照 code_frequency 进行索引保存，存储周期对应的缠论数据
        self.cl_datas: Dict[str, ICL] = {}

        # 按照 code_frequency 进行索引保存，减少多次计算时间消耗；每次循环缓存的计算，在下次循环会重置为 {}
        self.cache_cl_datas: Dict[str, ICL] = {}

    @abstractmethod
    def klines(self, code, frequency) -> pd.DataFrame:
        """
        获取标的周期内的k线数据
        """

    @abstractmethod
    def last_k_info(self, code) -> dict:
        """
        获取最后一根K线数据，根据 frequencys 最后一个 小周期获取数据
        return dict {'date', 'open', 'close', 'high', 'low'}
        """

    @abstractmethod
    def get_cl_data(self, code, frequency) -> ICL:
        """
        获取标的周期的缠论数据
        """


class Strategy(ABC):
    """
    交易策略基类
    """

    def __init__(self):
        pass

    @abstractmethod
    def open(self, code, market_data: MarketDatas) -> List[Operation]:
        """
        观察行情数据，给出开仓操作建议
        :param code:
        :param market_data:
        :return:
        """

    @abstractmethod
    def close(self, code, mmd: str, pos: POSITION, market_data: MarketDatas) -> [Operation, None]:
        """
        盯当前持仓，给出平仓当下建议
        :param code:
        :param mmd:
        :param pos:
        :param market_data:
        :return:
        """

    @staticmethod
    def check_loss(mmd: str, pos: POSITION, price: float):
        """
        检查是否触发止损，止损返回操作对象，不出发返回 None
        """
        # 止盈止损检查
        if pos.loss_price is None:
            return None

        if 'buy' in mmd:
            if price < pos.loss_price:
                return Operation('sell', mmd, msg='%s 止损' % mmd)
        elif 'sell' in mmd:
            if price > pos.loss_price:
                return Operation('sell', mmd, msg='%s 止损' % mmd)
        return None

    @staticmethod
    def check_back_return(mmd: str, pos: POSITION, price: float, max_back_rate: float):
        """
        检查是否触发最大回撤
        """
        if max_back_rate is not None:
            profit_rate = (pos.price - price) / pos.price * 100 \
                if 'sell' in mmd else \
                (price - pos.price) / pos.price * 100
            if profit_rate > 0 and pos.max_profit_rate - profit_rate >= max_back_rate:
                return Operation('sell', mmd, msg='%s 回调止损' % mmd)
        return None

    @staticmethod
    def last_done_bi(bis: List[BI]):
        """
        获取最后一个 完成笔
        """
        for bi in bis[::-1]:
            if bi.is_done():
                return bi
        return None

    @staticmethod
    def bi_qiang_td(bi: BI, cd: ICL):
        """
        笔的强停顿判断
        判断方法：收盘价要突破分型的高低点，并且K线要是阳或阴
        距离分型太远就直接返回 False
        """
        if bi.end.done is False:
            return False
        last_k = cd.get_klines()[-1]
        # 当前bar与分型第三个bar相隔大于2个bar，直接返回 False
        if last_k.index - bi.end.klines[-1].klines[-1].index > 2:
            return False
        if bi.end.klines[-1].index == last_k.index:
            return False
        if bi.end.type == 'ding' and last_k.o > last_k.c and last_k.c < bi.end.low(cd.get_config()['fx_qj']):
            return True
        elif bi.end.type == 'di' and last_k.o < last_k.c and last_k.c > bi.end.high(cd.get_config()['fx_qj']):
            return True
        return False

    @staticmethod
    def bi_yanzhen_fx(bi: BI, cd: ICL):
        """
        检查是否符合笔验证分型条件
        查找与笔结束分型一致的后续分型，并且该分型不能高于或低于笔结束分型
        """
        last_k = cd.get_klines()[-1]
        price = last_k.c
        fxs = cd.get_fxs()
        next_fxs = [_fx for _fx in fxs if (_fx.index > bi.end.index and _fx.type == bi.end.type)]
        if len(next_fxs) == 0:
            return False
        next_fx = next_fxs[0]
        # # 当前bar与验证分型第三个bar相隔大于2个bar，直接返回 False
        # if last_k.index - next_fx.klines[-1].klines[-1].index > 2:
        #     return False

        # 两个分型不能相隔太远，两个分型中间最多两根缠论K线
        if next_fx.k.k_index - bi.end.k.k_index > 3:
            return False
        if bi.type == 'up':
            # 笔向上，验证下一个顶分型不高于笔的结束顶分型，并且当前价格要低于顶分型的最低价格
            if next_fx.done and next_fx.val < bi.end.val and price < bi.end.low(cd.get_config()['fx_qj']):
                return True
        elif bi.type == 'down':
            # 笔向下，验证下一个底分型不低于笔的结束底分型，并且两个分型不能离得太远
            if next_fx.done and next_fx.val > bi.end.val and price > bi.end.high(cd.get_config()['fx_qj']):
                return True
        return False

    def dynamic_change_loss_by_bi(self, pos: POSITION, bis: List[BI]):
        """
        动态按照笔进行止损价格的移动
        """
        if pos.loss_price is None:
            return
        last_done_bi = self.last_done_bi(bis)
        if 'buy' in pos.mmd and last_done_bi.type == 'up':
            pos.loss_price = max(pos.loss_price, last_done_bi.low)
        elif 'sell' in pos.mmd and last_done_bi.type == 'down':
            pos.loss_price = min(pos.loss_price, last_done_bi.high)

        return

    @staticmethod
    def points_jiaodu(points: List[float], position='up'):
        """
        提供一系列数据点，给出其趋势角度，以此判断其方向
        用于判断类似 macd 背驰，macd柱子创新低而黄白线则新高
        """
        if len(points) == 0:
            return 0
        # 去一下棱角
        points = talib.MA(np.array(points), 2)
        # 先给原始数据编序号
        new_points = []
        for i in range(len(points)):
            if points[i] is not None:
                new_points.append([i, points[i]])

        # 根据位置参数，决定找分型类型
        fxs = []
        for i in range(1, len(new_points)):
            p1 = new_points[i - 1]
            p2 = new_points[i]
            p3 = new_points[i + 1] if len(new_points) > (i + 1) else None
            if position == 'up' and p1[1] <= p2[1] and ((p3 is not None and p2[1] >= p3[1]) or p3 is None):
                fxs.append(p2)
            elif position == 'down' and p1[1] >= p2[1] and ((p3 is not None and p2[1] <= p3[1]) or p3 is None):
                fxs.append(p2)

        if len(fxs) < 2:
            return 0
        # 按照大小排序
        fxs = sorted(fxs, key=lambda f: f[1], reverse=True if position == 'up' else False)

        def jiaodu(_p1: list, _p2: list):
            # 计算斜率
            k = (_p1[1] - _p2[1]) / (_p1[0] - _p2[0])
            # 斜率转弧度
            k = math.atan(k)
            # 弧度转角度
            j = math.degrees(k)
            return j

        return jiaodu(fxs[0], fxs[1])

    @staticmethod
    def check_datetime_mmd(start_datetime: datetime.datetime, cd: ICL, check_line: str = 'bi'):
        """
        检查指定时间后出现的买卖点信息
        """
        mmd_infos = {}
        lines = cd.get_bis() if check_line == 'bi' else cd.get_xds()
        for _l in lines[::-1]:
            if _l.start.k.date >= start_datetime:
                line_mmds = _l.line_mmds()
                for _m in line_mmds:
                    if _m not in mmd_infos.keys():
                        mmd_infos[_m] = 1
                    else:
                        mmd_infos[_m] += 1
            else:
                break
        return mmd_infos

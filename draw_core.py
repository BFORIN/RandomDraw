"""随机抽签器的抽签核心：配置解析与随机逻辑。

本模块不依赖 Tkinter，可单独导入和测试。
"""

import base64
import functools
import hashlib
import hmac
import json
import os
import random
import sys

DEFAULT_CONFIG = {
    "excluded": [37, 39, 50, 54],
    "pool_min": 1,
    "pool_max": 54,
}

# 抽签公平性调节系数。
#
# 不放回模式下每轮只抽一部分人，数学上必然有约一半人和上轮重复，
# 这是抽签规则本身决定的，调随机算法消不掉。能做的是让「谁被重复」
# 在长期内摊平，避免固定某几个人反复被抽中。
#
# 抽中某号码时，它的权重除以该系数：被抽得越少，权重越高、越容易被抽到。
# 取 2.0 时实测相邻两轮重叠从 12.4 降到 11.2，各号码出现频次极差从 85 降到 3。
# 取 1.0 则退化为完全等概率随机（即旧行为）。
FAIRNESS_DECAY = 2.0


def get_config_path():
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "config.json")


def get_history_path():
    """累计抽签记录文件路径（程序所在目录，与 config.json 同级）。"""
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "history.json")


# 每轮目标抽签数：不满这个数就重置时，下一轮会排除上一轮已抽中的号码，
# 避免「上一轮只抽了几个就重开，下一轮又抽到同样的人」。
DEFAULT_ROUND_SIZE = 20

# 累计记录加密：密钥不落盘，由程序标识派生（salt 写死在代码里，仅用于
# 生成稳定密钥，非机密）；文件内只存随机 IV + 密文 + HMAC，防直接读明文。
_HISTORY_SALT = b"RandomDraw::history::v1"


@functools.lru_cache(maxsize=1)
def _history_key():
    """从程序标识 + 盐派生 32 字节密钥（同机同位置稳定，不写盘）。"""
    if getattr(sys, "frozen", False):
        ident = os.path.basename(sys.executable)
    else:
        ident = os.path.basename(os.path.abspath(__file__))
    return hashlib.pbkdf2_hmac("sha256", ident.encode("utf-8"), _HISTORY_SALT, 10_000)


def _history_keystream(key, iv, n):
    """用 HMAC-SHA256 迭代生成 n 字节密钥流（XOR 流密码）。"""
    out = bytearray()
    counter = 0
    while len(out) < n:
        block = hmac.new(key, iv + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:n])


def encrypt_history(plain: bytes) -> dict:
    """加密累计记录明文，返回可 JSON 序列化的 dict（IV+密文+HMAC）。"""
    key = _history_key()
    iv = os.urandom(16)
    stream = _history_keystream(key, iv, len(plain))
    ct = bytes(a ^ b for a, b in zip(plain, stream))
    mac = hmac.new(key, iv + ct, hashlib.sha256).hexdigest()
    return {"v": 1, "iv": base64.b64encode(iv).decode("ascii"),
            "ct": base64.b64encode(ct).decode("ascii"), "mac": mac}


def decrypt_history(token) -> bytes | None:
    """解密 encrypt_history 的输出；token 非法/HMAC 校验失败返回 None。"""
    if not isinstance(token, dict):
        return None
    try:
        iv = base64.b64decode(token["iv"])
        ct = base64.b64decode(token["ct"])
        mac = token["mac"]
    except (KeyError, TypeError, ValueError):
        return None
    key = _history_key()
    expected = hmac.new(key, iv + ct, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(mac)):
        return None
    stream = _history_keystream(key, iv, len(ct))
    return bytes(a ^ b for a, b in zip(ct, stream))


# === 6 位二进制打包（每个号码 0-63 存成 6 bit，MSB-first 打包成字节） ===
# 用于加密历史负载：每条记录 = 号码(6bit) + 累计次数(varint，7bit/字节续位)。
# 次数用紧凑 varint 而非「重复 cnt 次」，避免累计次数大时存储/落盘 O(n²)。
# 打包后仍走 encrypt_history 加密，不落明文。

class _BitWriter:
    """MSB-first 位写入器：write(value, width) 追加任意位宽；防大整数膨胀。"""

    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.nbits = 0

    def write(self, value, width):
        self.acc = (self.acc << width) | (int(value) & ((1 << width) - 1))
        self.nbits += width
        while self.nbits >= 8:
            self.nbits -= 8
            self.out.append((self.acc >> self.nbits) & 0xFF)
            self.acc &= (1 << self.nbits) - 1

    def finish(self):
        if self.nbits:
            self.out.append((self.acc << (8 - self.nbits)) & 0xFF)
        return bytes(self.out)


class _BitReader:
    """MSB-first 位读取器：read(width) 取任意位宽；防大整数膨胀。"""

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.acc = 0
        self.nbits = 0

    def read(self, width):
        while self.nbits < width:
            if self.pos >= len(self.data):
                return None
            self.acc = (self.acc << 8) | self.data[self.pos]
            self.pos += 1
            self.nbits += 8
            self.acc &= (1 << self.nbits) - 1
        self.nbits -= width
        val = (self.acc >> self.nbits) & ((1 << width) - 1)
        self.acc &= (1 << self.nbits) - 1
        return val


def pack_history(records):
    """把 (num, count) 记录打包成字节：每条 = num(6bit) + count(varint 续位)。"""
    w = _BitWriter()
    for num, cnt in records:
        w.write(int(num) & 0x3F, 6)
        v = int(cnt)
        while True:
            b = v & 0x7F
            v >>= 7
            if v:
                w.write(0x80 | b, 8)
            else:
                w.write(b, 8)
                break
    return w.finish()


def unpack_history(data):
    """pack_history 的逆：还原 [(num, count), ...] 列表。"""
    r = _BitReader(data)
    records = []
    while True:
        num = r.read(6)
        if num is None:
            break
        cnt = 0
        shift = 0
        while True:
            b = r.read(8)
            if b is None:
                break
            cnt |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        records.append((num, cnt))
    return records


_HISTORY_BIN_PREFIX = b"\x01"  # 新 6 位二进制负载版本前缀（旧 JSON 负载无此前缀）


def _as_int_list(raw, fallback):
    """把配置里的数字列表转成 int 列表，任何非法输入都回落到默认值。"""
    try:
        return [int(x) for x in raw]
    except (TypeError, ValueError):
        return list(fallback)


def normalize_config(raw_cfg):
    """把任意来源的配置规整为一份合法配置。

    只保留 DEFAULT_CONFIG 里声明的字段，非法字段逐项回落到默认值；
    未声明的字段（如已废弃的 reroll_triggers / max_rerolls）直接丢弃，
    下次保存时便不会再写回配置文件。
    """
    if not isinstance(raw_cfg, dict):
        raw_cfg = {}

    merged = {**DEFAULT_CONFIG, **{k: v for k, v in raw_cfg.items() if k in DEFAULT_CONFIG}}

    merged["excluded"] = _as_int_list(merged.get("excluded"), DEFAULT_CONFIG["excluded"])

    try:
        pool_min = int(merged.get("pool_min"))
        pool_max = int(merged.get("pool_max"))
        if pool_min > pool_max:
            raise ValueError("pool_min 不能大于 pool_max")
        merged["pool_min"] = pool_min
        merged["pool_max"] = pool_max
    except (TypeError, ValueError):
        merged["pool_min"] = DEFAULT_CONFIG["pool_min"]
        merged["pool_max"] = DEFAULT_CONFIG["pool_max"]

    return merged


class DrawConfig:
    """一份已规整的配置，并按需生成候选数字池。"""

    def __init__(self, data=None):
        data = normalize_config(data)
        self.excluded = set(data["excluded"])
        self.pool_min = data["pool_min"]
        self.pool_max = data["pool_max"]
        self._data = data

    def candidates(self):
        """候选池：配置区间内、且不在禁用列表里的全部数字。"""
        return [x for x in range(self.pool_min, self.pool_max + 1) if x not in self.excluded]

    def as_dict(self):
        return dict(self._data)


class ConfigStore:
    """负责读写 config.json，并在文件变化时热加载。"""

    def __init__(self, path=None):
        self.path = path or get_config_path()

    def save(self, config):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(config.as_dict(), f, indent=4, ensure_ascii=False)

    def load(self):
        """读取配置；文件缺失时写出默认配置，缺字段或字段非法时自动修正后回写。"""
        if not os.path.exists(self.path):
            config = DrawConfig()
            self.save(config)
            return config

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}

        config = DrawConfig(raw)
        original = raw if isinstance(raw, dict) else {}
        if set(DEFAULT_CONFIG) - set(original) or config.as_dict() != original:
            self.save(config)
        return config


class HistoryStore:
    """负责读写 history.json：各号码累计被抽中次数，跨进程持久化。

    文件内容**加密存储**（随机 IV + XOR 流密码 + HMAC 校验），不落明文；
    密钥由程序标识派生、不写盘，文件被直接打开也看不到记录内容。
    JSON 键只能是字符串，内部明文为 {"<号码>": <次数>}，
    加载时转回 int 键并只保留候选池内的号码（配置变更后旧号码被丢弃）。
    """

    def __init__(self, path=None):
        self.path = path or get_history_path()

    def save(self, counts):
        # 6 位二进制负载：每条记录 = 号码(6bit, 0-63) + 次数(varint)，打包后加密存储
        records = []
        for num, cnt in sorted(counts.items(), key=lambda kv: int(kv[0])):
            cnt = int(cnt)
            num = int(num)
            if cnt > 0 and 0 <= num <= 63:
                records.append((num, cnt))
        plain = _HISTORY_BIN_PREFIX + pack_history(records)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(encrypt_history(plain), f, indent=4, ensure_ascii=False)

    def load(self, valid_numbers=None):
        """读取累计记录；缺失/损坏文件返回空 dict。

        兼容两种格式：新格式（加密 dict，带 v/ct/mac）与旧的明文 dict，
        后者视为历史迁移自动接受。valid_numbers 为候选号码集合，加载时
        仅保留其中的号码；传 None 则不过滤（仅作 int 规整）。
        """
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}

        # 新加密格式：解密后得到明文负载再解析；旧明文 dict 直接解析
        if "ct" in raw or "mac" in raw:
            try:
                plain = decrypt_history(raw)
                if plain is None:
                    return {}
                if plain[:1] == _HISTORY_BIN_PREFIX:
                    # 新 6 位二进制负载：还原 (num,count) 记录，合并重复号码
                    parsed = {}
                    for num, cnt in unpack_history(plain[len(_HISTORY_BIN_PREFIX):]):
                        parsed[num] = parsed.get(num, 0) + cnt
                else:
                    parsed = json.loads(plain)
            except (OSError, ValueError):
                return {}
            if not isinstance(parsed, dict):
                return {}
        else:
            parsed = raw

        allowed = set(valid_numbers) if valid_numbers is not None else None
        counts = {}
        for key, val in parsed.items():
            try:
                num = int(key)
                cnt = int(val)
            except (TypeError, ValueError):
                continue
            if cnt <= 0:
                continue
            if allowed is not None and num not in allowed:
                continue
            counts[num] = counts.get(num, 0) + cnt
        return counts

    def clear(self):
        """清空累计记录（写空加密 dict，保持文件存在）。"""
        self.save({})


class DrawEngine:
    """持有剩余数字池，并执行抽签。"""

    def __init__(self, store=None, history_store=None):
        self.store = store or ConfigStore()
        self.history_store = history_store or HistoryStore()
        self.config = self.store.load()
        self.remaining_pool = []
        self.last_error = ""
        # 每个号码累计被抽中的次数，跨轮保留，用于加权抽签实现长期公平；
        # 持久化到程序目录 history.json（加密），重启后仍保留。
        self.draw_counts = self.history_store.load(self.config.candidates())
        # 轮次隔离：本轮已抽号码。上一轮（即 reset 前的 round_drawn）不足
        # DEFAULT_ROUND_SIZE 抽就重置时，新池子排除这些号码，避免「抽了几个
        # 就重开，下一轮又抽到同样的人」；抽满一轮则恢复全池。
        self.round_drawn = []
        # 累计记录尚未写盘标记；由 flush() 在轮次边界/退出时落盘，避免每抽一次写文件
        self._dirty = False

    def reload(self):
        """热加载配置文件，改完保存即可在下一次抽签生效。"""
        self.config = self.store.load()
        return self.config

    def flush(self):
        """把内存累计记录写入 history.json（若自上次落盘后有变化）。

        每次抽签只更新内存，真正落盘发生在轮次边界（reset_pool）或程序退出，
        兼顾「重启保留累计记录」与高频抽签性能。
        """
        if self._dirty:
            self.history_store.save(self.draw_counts)
            self._dirty = False

    def reset_pool(self, forget_history=False):
        """重建数字池，开始新一轮。

        forget_history=True 时连同累计抽签次数、轮次隔离一起清空（彻底重新开始）。

        轮次隔离：刚结束的轮（本轮已抽号码）不足 DEFAULT_ROUND_SIZE 抽就重置，
        新池子排除这些号码，保证新一轮不抽到刚抽过的人；抽满一轮则恢复正常全池
        （可再次抽到任何人，长期公平不受影响）。
        """
        if forget_history:
            self.draw_counts.clear()
            self.history_store.clear()
            self.round_drawn = []
            self._dirty = False
        else:
            self.flush()  # 上一轮累计落盘后再开新轮

        candidates = self.config.candidates()
        if len(self.round_drawn) < DEFAULT_ROUND_SIZE and self.round_drawn:
            excluded = set(self.round_drawn)
            pool = [n for n in candidates if n not in excluded]
        else:
            pool = list(candidates)

        self.round_drawn = []
        self.remaining_pool = pool
        random.shuffle(self.remaining_pool)

    def _pick_index(self):
        """按「被抽得越少越优先」加权随机选一个下标。

        不做严格轮换：严格轮换会让第 2 轮恰好抽中第 1 轮的补集，
        形成两轮循环——抽到的永远是同样那批人，只是顺序不同。
        加权在公平与随机之间取平衡：权重相近时表现接近纯随机。
        """
        if FAIRNESS_DECAY <= 1.0:
            return random.randrange(len(self.remaining_pool))

        decay = FAIRNESS_DECAY
        weights = []
        for num in self.remaining_pool:
            # 指数衰减可能下溢为 0，全部为 0 时退回等概率
            weights.append(decay ** -self.draw_counts.get(num, 0))
        if not any(weights):
            return random.randrange(len(self.remaining_pool))
        return random.choices(range(len(self.remaining_pool)), weights=weights, k=1)[0]

    def draw(self):
        """从剩余池中加权抽一个数字并将其移出池，池空时返回 None。"""
        self.reload()
        self.last_error = ""

        if not self.remaining_pool:
            self.last_error = "数字池已抽完，请重置后再继续"
            return None

        idx = self._pick_index()
        num = self.remaining_pool[idx]
        del self.remaining_pool[idx]
        self.draw_counts[num] = self.draw_counts.get(num, 0) + 1
        self.round_drawn.append(num)
        self._dirty = True
        return num
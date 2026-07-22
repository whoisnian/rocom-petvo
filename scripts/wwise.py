"""Wwise SoundBank(bank version 135 / Wwise 2021.1)最小解析。

只实现本项目需要的两件事:
  1. 事件名 -> 该事件会播的 wem 列表(HIRC 对象图下行);
  2. Game Parameter 对 Pitch 的 RTPC 曲线。

偏移均为对本作 bnk 的实测结果,换游戏/换 Wwise 版本不保证适用。详见
https://github.com/whoisnian/rocom-capture/blob/master/docs/audio.md
"""
import struct

# HIRC 对象类型
SOUND, ACTION, EVENT, RAN_SEQ, SWITCH, ACTOR_MIXER = 2, 3, 4, 5, 6, 7
CONTAINERS = (RAN_SEQ, SWITCH, ACTOR_MIXER)


def fnv1_32(name):
    """Wwise 用 FNV-1(非 1a)32 位哈希,且**先转小写**,把名字映射成对象 id。"""
    h = 2166136261
    for b in name.lower().encode():
        h = ((h * 16777619) & 0xFFFFFFFF) ^ b
    return h


class Bank:
    def __init__(self, path):
        self.buf = buf = open(path, 'rb').read()
        self.objs = {}       # id -> (type, body_start, body_end)
        self.children = {}   # parent id -> [child id]

        p = 0
        while p < len(buf) - 8:
            tag, size = buf[p:p + 4], struct.unpack_from('<I', buf, p + 4)[0]
            if tag == b'HIRC':
                self._read_hirc(p + 8)
            p += 8 + size

        # 靠 directParentID 反建父子树。别用「扫描对象体里的 4 字节、命中已知 id 就当子节点」
        # 那种启发式 —— 引用会一路爬到 ActorMixer 根,把整个 bnk 的 Sound 全吞进来。
        for oid, (typ, s, e) in self.objs.items():
            par = self._direct_parent(typ, s, e)
            if par is not None:
                self.children.setdefault(par, []).append(oid)

    def _read_hirc(self, off):
        buf = self.buf
        n = struct.unpack_from('<I', buf, off)[0]
        p = off + 4
        for _ in range(n):
            typ = buf[p]
            size = struct.unpack_from('<I', buf, p + 1)[0]
            oid = struct.unpack_from('<I', buf, p + 5)[0]
            self.objs[oid] = (typ, p + 5, p + 5 + size)
            p += 5 + size

    def _direct_parent(self, typ, start, end):
        """NodeBaseParams.directParentID。偏移 = 前缀 + nFX 块 + 2 + 4;
        Sound 前缀 14B、容器无前缀,nFX=0 时实测落在 Sound @25 / 容器 @11。"""
        off = 25 if typ == SOUND else 11 if typ in CONTAINERS else None
        if off is None or start + off + 4 > end:
            return None
        par = struct.unpack_from('<I', self.buf, start + off)[0]
        return par if par in self.objs else None

    def event_wems(self, event_name):
        """事件名 -> 它会播到的所有 wem 的 sourceID(去重,保留遍历序)。"""
        eid = fnv1_32(event_name)
        if eid not in self.objs or self.objs[eid][0] != EVENT:
            return []
        _, s, _ = self.objs[eid]
        count = self.buf[s + 4]                       # Event 的 action 数量是 uint8
        targets = []
        for k in range(count):
            aid = struct.unpack_from('<I', self.buf, s + 5 + 4 * k)[0]
            if aid in self.objs and self.objs[aid][0] == ACTION:
                _, a_s, _ = self.objs[aid]
                targets.append(struct.unpack_from('<I', self.buf, a_s + 6)[0])

        out, seen = [], set()

        def walk(oid):
            if oid in seen or oid not in self.objs:
                return
            seen.add(oid)
            typ, s, _ = self.objs[oid]
            if typ == SOUND:
                out.append(struct.unpack_from('<I', self.buf, s + 9)[0])   # sourceID @9
            for c in sorted(self.children.get(oid, [])):
                walk(c)

        for t in targets:
            walk(t)
        return list(dict.fromkeys(out))

    def pitch_curve(self, param):
        """容器/ActorMixer 上 <param> 对 Pitch 的 RTPC 曲线 -> [(x, 音分)]。

        没有做完整的 RTPC 段游标解析(各节点结构差异大),而是全 buf 搜 Game Parameter 的
        id,再用「所属对象是容器 + ParameterID==2(Pitch) + 点数与取值在合理范围」三重
        校验筛掉误命中。效果器插件上的同名 RTPC 会因为宿主不是容器而被排除 —— 那边的
        ParameterID 是插件私有下标,和这里的枚举不是一套。
        """
        key = struct.pack('<I', fnv1_32(param))
        buf = self.buf
        spans = [(s, e, t) for t, s, e in self.objs.values()]
        for o in range(len(buf) - 4):
            if buf[o:o + 4] != key:
                continue
            owner = next((t for (s, e, t) in spans if s <= o < e), None)
            if owner not in CONTAINERS or buf[o + 6] != 2:
                continue
            npts = struct.unpack_from('<H', buf, o + 12)[0]
            if not 2 <= npts <= 8:
                continue
            pts = [struct.unpack_from('<ff', buf, o + 14 + 12 * k) for k in range(npts)]
            if any(abs(x) > 200 or abs(y) > 4800 for x, y in pts):
                continue
            return [(round(x), round(y)) for x, y in pts]
        return None

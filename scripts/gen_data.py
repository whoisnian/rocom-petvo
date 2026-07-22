# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""从《洛克王国：世界》解包数据生成本站的三样产物:data.js / sprite.webp / audio/*.m4a。

    uv run scripts/gen_data.py [--force] [--only data|sprite|audio]

前置(两份解包产物,均在仓库外,靠环境变量定位):
  ROCOM_PARSED  常规解包根,默认 ~/Downloads/rocom/parsed
  ROCOM_AUDIO   WwiseAudio 导出根,默认 ~/Downloads/rocom/audio
两者都由 rocom-capture 的 scripts/unpack.sh 产出;音频默认在排除清单里,要显式关掉:
    scripts/unpack.sh --no-exclude --no-post \
      --filter NRC/Content/NewRoco/WwiseAudio/Windows --out ~/Downloads/rocom/audio

外部命令:vgmstream-cli(解 Wwise Vorbis)、ffmpeg(转 m4a)。

收录规则:每只宠物取 `Pet_Vo_<拼音>_Common_Happy` 事件的**最小** sourceID 那一条变体
(该事件通常挂 3 个随机变体,取最小 id 是为了可复现)。没有该事件的(如画精灵,只有
World_Evo)和没有图鉴号的一律跳过,最终 425 只。

产物是否覆盖:data.js 每次重写(纯文本,diff 可读);sprite.webp 与 audio/*.m4a **默认跳过
已存在的**,要重编用 --force。m4a 在同版本 ffmpeg 下可复现到字节一致;sprite.webp 的
webp 编码会有字节漂移(见 README「重新生成」一节),不加 --force 就不会平白污染 git。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wwise import Bank  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARSED = os.environ.get("ROCOM_PARSED", os.path.expanduser("~/Downloads/rocom/parsed"))
AUDIO = os.environ.get("ROCOM_AUDIO", os.path.expanduser("~/Downloads/rocom/audio"))

BIN = os.path.join(PARSED, "NRC/Content/ScriptC/Data/Bin/BinDataCompressed")
HEAD = os.path.join(PARSED, "NRC/Content/NewRoco/Modules/System/Common/Icon/HeadIcon")
WWISE = os.path.join(AUDIO, "NRC/Content/NewRoco/WwiseAudio/Windows")

EVENT = "Pet_Vo_%s_Common_Happy"     # 取哪一类叫声:通用-开心
RTPC = "Pet_Vo_Pitch"                # 嗓音音调的 Game Parameter 名
COLS, CELL = 21, 128                 # 精灵图列数、源格边长(前端按 64/52 缩放显示)
D, DS = 64, 52                       # 前端格子边长:桌面 / 移动
BITRATE = "48k"                      # AAC 码率;单声道 48kHz,单只约 10K

FORCE = "--force" in sys.argv
_only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
ONLY = set(_only[0].split(",")) if _only else {"data", "sprite", "audio"}


def rows(name):
    with open(os.path.join(BIN, name), encoding="utf-8") as f:
        return json.load(f)["RocoDataRows"]


def texkey(ref):
    """从 UE 资产引用 <Cls>'/Game/.../NAME.NAME' 抠出文件名 NAME。"""
    m = re.search(r"/Game/.*/([^/.']+)\.", ref) if isinstance(ref, str) else None
    return m.group(1) if m else None


def collect():
    """扫全部 Pet_Vo_*.bnk,拼出宠物表(图鉴号/中文名/拼音/头像/wem/音调曲线)。"""
    namemap, base, model = (rows("PET_NAME_MAP_CONF.json"), rows("PETBASE_CONF.json"),
                            rows("MODEL_CONF.json"))
    # 拼音 -> conf_id;大小写不敏感(表里混有 Huohua / HuoHua 两种写法),
    # 同拼音多形态时优先取有图鉴号的,否则会拿到无图鉴号的分身。
    by_py = {}
    for r in namemap.values():
        by_py.setdefault(r["name"].lower(), []).append(str(r["id"]))

    pets, skipped = [], []
    for fn in sorted(os.listdir(WWISE)):
        if not (fn.startswith("Pet_Vo_") and fn.endswith(".bnk")):
            continue
        py = fn[len("Pet_Vo_"):-len(".bnk")]
        ids = by_py.get(py.lower(), [])
        ids = [i for i in ids if base.get(i, {}).get("pictorial_book_id")] or ids
        conf = base.get(ids[0]) if ids else None
        if not conf or not conf.get("pictorial_book_id"):
            skipped.append((py, "无图鉴号"))
            continue

        bank = Bank(os.path.join(WWISE, fn))
        wems = bank.event_wems(EVENT % py)
        if not wems:
            skipped.append((py, "无 Common_Happy 事件"))
            continue
        icon = texkey((model.get(str(conf.get("model_conf"))) or {}).get("icon"))
        if not icon or not os.path.exists(os.path.join(HEAD, icon + ".png")):
            skipped.append((py, "无头像"))
            continue

        curve = bank.pitch_curve(RTPC) or [(-100, 0), (0, 0), (100, 0)]
        pets.append({"book": conf["pictorial_book_id"], "name": conf["name"], "py": py,
                     # 同事件挂多个随机变体,固定取最小 sourceID,保证换机器/换次数都一样
                     "icon": icon, "wem": min(wems), "nvar": len(wems),
                     "l": curve[0][1], "h": curve[-1][1]})

    pets.sort(key=lambda p: (p["book"], p["py"]))
    for i, p in enumerate(pets):
        p["i"] = i
    return pets, skipped


def probe_duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True).stdout.strip())


def build_audio(pets):
    """解 wem -> 转 m4a,并回填每只的原声时长 d。

    d 取的是**解码后 wav** 的长度,不是成品 m4a(AAC 补帧会让 m4a 长几毫秒),
    也不是 vgmstream 元数据里的 total samples(个别文件与实际解码长度差 1 个采样)。
    所以即便 m4a 已存在、跳过重编,这里仍然要解一遍 wem —— vgmstream 很快,可以接受。
    """
    out = os.path.join(ROOT, "audio")
    os.makedirs(out, exist_ok=True)
    made = kept = 0
    for p in pets:
        dst = os.path.join(out, p["py"] + ".m4a")
        # vgmstream 的 wav **不能用管道**喂 ffmpeg:头部大小字段流式不可靠,ffmpeg 报 183。
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            subprocess.run(["vgmstream-cli", "-o", tmp.name,
                            os.path.join(WWISE, "%d.wem" % p["wem"])],
                           check=True, capture_output=True)
            p["d"] = round(probe_duration(tmp.name), 4)
            if os.path.exists(dst) and not FORCE:
                kept += 1
            else:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp.name,
                                "-ac", "1", "-ar", "48000", "-c:a", "aac",
                                "-b:a", BITRATE, "-movflags", "+faststart", dst],
                               check=True)
                made += 1
    print("audio: 新编 %d,沿用 %d" % (made, kept))


def build_sprite(pets):
    from PIL import Image
    dst = os.path.join(ROOT, "sprite.webp")
    if os.path.exists(dst) and not FORCE:
        print("sprite: 已存在,跳过(--force 重编)")
        return
    rows_n = (len(pets) + COLS - 1) // COLS
    sheet = Image.new("RGBA", (COLS * CELL, rows_n * CELL), (0, 0, 0, 0))
    for p in pets:
        icon = Image.open(os.path.join(HEAD, p["icon"] + ".png")).convert("RGBA")
        sheet.paste(icon, ((p["i"] % COLS) * CELL, (p["i"] // COLS) * CELL))
    sheet.save(dst, quality=87, method=4)
    print("sprite: %dx%d,%d 格,%.1fK" % (sheet.width, sheet.height, len(pets),
                                          os.path.getsize(dst) / 1024))


def build_data(pets):
    dst = os.path.join(ROOT, "data.js")
    body = ",\n".join(json.dumps(
        {k: p[k] for k in ("book", "name", "py", "i", "d", "l", "h")},
        ensure_ascii=False, separators=(",", ":")) for p in pets)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("""\
// 由 scripts/gen_data.py 从解包数据生成,勿手改。字段含义:
//   book 图鉴号 / name 中文名 / py 拼音(= audio/<py>.m4a 与 hash 锚点)
//   i    在 sprite.webp 中的序号(行主序)
//   d    原声时长(秒),用作 ended 不触发时的兜底定时
//   l,h  Wwise RTPC "%s" 曲线在 voice=-100 / +100 处的音分,逐宠手调
const COLS=%d, D=%d, DS=%d;   // 精灵图列数、格子边长(桌面/移动)
const PETS=[
%s
];
""" % (RTPC, COLS, D, DS, body))
    print("data: %d 只 -> data.js" % len(pets))


def main():
    for d, what in ((BIN, "ROCOM_PARSED"), (WWISE, "ROCOM_AUDIO")):
        if not os.path.isdir(d):
            sys.exit("目录不存在: %s\n请先跑 unpack.sh,或设 %s。" % (d, what))

    pets, skipped = collect()
    print("收录 %d 只,跳过 %d 只" % (len(pets), len(skipped)))
    for py, why in skipped[:10]:
        print("  跳过 %-20s %s" % (py, why))

    if "audio" in ONLY or "data" in ONLY:
        build_audio(pets)          # data.js 的 d 字段来自解码后的 wav,故 data 也要跑这步
    if "sprite" in ONLY:
        build_sprite(pets)
    if "data" in ONLY:
        build_data(pets)


if __name__ == "__main__":
    main()

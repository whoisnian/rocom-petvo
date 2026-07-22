# rocom-petvo · 宠物叫声图鉴

《洛克王国：世界》425 只宠物的叫声速查页。搜图鉴号或名字，点头像听原声，
点下方两个按钮听游戏内嗓音属性拉到两端时的效果。

纯静态、无构建、无依赖，`index.html` 双击即可打开，也可直接整目录传到
Cloudflare Pages 之类的静态托管。

## 目录

| 路径 | 说明 |
| --- | --- |
| `index.html` | 页面骨架 |
| `style.css` | 样式 |
| `app.js` | 全部交互逻辑 |
| `data.js` | **生成物**：425 只宠物的图鉴号 / 名称 / 拼音 / 精灵图序号 / 时长 / 音调曲线 |
| `sprite.webp` | **生成物**：425 张头像拼成的精灵图，21 列 × 128px |
| `audio/*.m4a` | **生成物**：每只一段原声，按拼音命名 |
| `scripts/gen_data.py` | 从解包数据重新生成上面三样 |
| `scripts/wwise.py` | Wwise SoundBank 最小解析（被 gen_data.py 引用） |

前三个是手写的，改动直接编辑即可；后三个由脚本产出，**不要手改**。

## 数据从哪来

全部自行解包提取，不依赖任何外部数据仓库。完整的推导过程（音频藏在哪、
`.bnk` 怎么解、事件名怎么对上宠物）记在隔壁仓库：
[rocom-capture / docs/audio.md](https://github.com/whoisnian/rocom-capture/blob/master/docs/audio.md)。

简述四步：

1. 事件名 `Pet_Vo_<拼音>_Common_Happy` 经 FNV-1 哈希定位到 `Pet_Vo_<拼音>.bnk`
   里的 Event 对象；
2. 沿 `Event → Action → 容器 → Sound` 下行，取 `sourceID` 得到 `<id>.wem`；
   一个事件通常挂 3 个随机变体，本项目固定取**最小 id** 那条，保证可复现；
3. 拼音经 `PET_NAME_MAP_CONF` 换成 conf_id，再经 `PETBASE_CONF` 拿到中文名和图鉴号；
4. `.wem` 是 Wwise Vorbis，ffmpeg 解不了，用 vgmstream 解成 wav 再转 m4a。

没有图鉴号的（未上线 / 非图鉴宠）和没有 `Common_Happy` 事件的（如画精灵只有
`World_Evo`）一律跳过，621 个 bnk 最终收录 425 只。

## 音调是怎么回事

游戏里每只宠物有个 -100 ~ 100 的 `voice` 属性（协议里就叫 `voice`），
拉到两端会得到「粗嗓门」「婉转声」两枚奖牌 —— 判的是本种群内最低 / 最高 2%。

这个值在客户端被直接喂给 Wwise 的 Game Parameter `Pet_Vo_Pitch`，由 RTPC 曲线
实时变调。曲线**逐宠手调**，三点线性（x = -100 / 0 / +100），两端音分就是
`data.js` 里的 `l` 和 `h`。最常见的是 -300 / +300 和 -300 / +500，也有 -801 / +1215
这种特例。

Wwise 的 pitch 本身就是重采样（变调同时变速），所以前端用

```js
a.preservesPitch = false;
a.playbackRate = Math.pow(2, cents / 1200);
```

就是等价实现，不需要为每个音调预生成音频。

一处**已知差异**：游戏里除了 pitch，还有两个效果器插件（`0x00820003` /
`0x00880003`）的参数跟着 `Pet_Vo_Pitch` 联动。bnk 里不存插件名，无从复刻，
所以两端的听感会和游戏内有出入，主要体现在音色而非音高。

## 重新生成

游戏更新后重跑。需要 [uv](https://docs.astral.sh/uv/)、`vgmstream-cli`、`ffmpeg`。

先用 [rocom-capture](https://github.com/whoisnian/rocom-capture) 的 `unpack.sh`
解包，得到两份产物 —— 音频在默认排除清单里，必须显式关掉：

```bash
# 常规解包(Bin 配置 + 头像 PNG)
scripts/unpack.sh

# 音频(约 3.3G,用完可删)
scripts/unpack.sh --no-exclude --no-post \
  --filter NRC/Content/NewRoco/WwiseAudio/Windows --out ~/Downloads/rocom/audio
```

然后：

```bash
uv run scripts/gen_data.py                    # 只补新增,已有的 m4a/sprite 不动
uv run scripts/gen_data.py --force            # 全量重编
uv run scripts/gen_data.py --only=data        # 只重写 data.js
```

解包根用环境变量覆盖：`ROCOM_PARSED`（默认 `~/Downloads/rocom/parsed`）、
`ROCOM_AUDIO`（默认 `~/Downloads/rocom/audio`）。

`data.js` 每次都重写（纯文本，diff 可读）；`sprite.webp` 和 `audio/*.m4a`
**默认跳过已存在的**，避免平白产生二进制改动。

### 关于可复现性

同版本 ffmpeg 下，`audio/*.m4a` 可复现到**字节一致**（425 个已实测）。

`sprite.webp` 不行 —— webp 编码结果会随 libwebp 版本漂移。`--force` 重编后
建议先做像素比对再决定要不要提交：实测重编版与已提交版 alpha 完全一致、
RGB 平均差 3.99（作为对照，整体错开一格是 66），属于编码噪声而非内容变化。

`data.js` 的 `d` 字段（原声时长，仅用作播放兜底定时）有约 20 只与最初提交的版本
差 0.0001 秒，是最初手工流程与现脚本的取整差异，对行为无影响。

## 许可

代码随仓库开源。音频与图片提取自游戏客户端，版权归权利人所有，
仅供学习与研究，请勿商用。

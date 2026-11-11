# 阶段交付与字段

## 项目目录

```text
项目名/
  素材/                           原始输入
  参考视频/                       可选参考片
  封面参考/                       系列封面参考与明确提供的素材
  edit/
    brief.json                    需求
    analysis/media_manifest.json  输入文件指纹与技术信息
    analysis/hypit/manifest.json  Hypit 参考证据（有视频参考时）
    01_strategy/strategy.md        剪辑思路
    01_strategy/reference_analysis.md
    02_storyboard/storyboard.json
    02_storyboard/storyboard.html  用户可看图审核
    02_storyboard/frames/          原片提取帧
    edl.json                      可重复运行的剪辑工程
    cover/cover_manifest.json     当前待审/已审封面清单与PNG/JPG
    03_preview/                   完整预览与检查记录
    04_final/                     终稿与检查记录
    workflow/state.json           当前确认、渲染记录
```

## 素材和思路

`brief.json` 由 Codex 根据用户本次要求填写，不用示例内容冒充真实需求。必要字段：

- `objective`：用途、受众、希望观众记住或采取的行动。
- `target_duration_s`、`aspect_ratio`、`fps`：目标时长、画幅和帧率。
- `required_content`：必须进入成片的内容字符串数组。
- `avoid_content`：不能出现的画面、人物、说法或信息。
- `subtitles_required`：是否必须有字幕。
- `cover`：封面是否需要、准确标题、系列标识、尺寸与参考文件；本项目默认包含封面。

没有实际要求时，不替用户作最终选择。可在思路阶段提出推荐并明确尚待用户确认。

`inventory` 输出技术清单、截图和索引，不自动生成“看过/听过全部素材”的结论。
Codex 继续查看足以判断选镜的片段，并用真实转写处理口播。思路应说明叙事结构、每段要点、预计时长、选材依据、字幕、声音和可能缺项。
若拍摄素材覆盖不了目标，提出替代结构或缺项，保留用户选择。
有视频参考时先运行 `reference`，读取真实 Hypit 证据并完成参考分析。思路确认绑定参考片与证据版本。

## 分镜

`storyboard.json` 顶层至少有 `shots` 数组，可配置 `grade`、`subtitles`、`overlays`、`music`。
每镜字段：

```json
{
  "id": "S01",
  "source": "清单中的素材ID",
  "start": 1.2,
  "end": 4.6,
  "frame": 2.0,
  "key_content": "这一镜中确实可见、需要让观众记住的内容",
  "covers": ["brief.required_content 中该镜覆盖的要点"],
  "purpose": "开场或证据等叙事作用",
  "caption": "本镜字幕文案，如有",
  "audio": "保留原声",
  "transition": "cut"
}
```

时间均为原片秒数，`end` 不包含在区间内；`frame` 落在本镜范围。关键内容有多个重要瞬间时，使用 `keyframes:[{time,description}]` 或拆成多镜。
源文件必须来自真实清单；真实截图用 FFmpeg 提取。HTML 展示来源、关键图、源/成片时间码、时长、关键内容、字幕和音频计划。
`missing:true` 允许标出缺镜，但不允许进入已确认可渲染分镜。

支持自动编译的是顺序切剪。复杂转场、变速、额外配音、构图处理需先准备可核验的派生素材，或扩展后端并验证后再确认分镜。
有字幕计划而 SRT 未准备时，分镜可以先展示文案，但不能声称 EDL 已就绪或进入渲染。

音乐相对路径从 `edit/` 解析：

```json
{"music":{"file":"assets/music.wav","volume_db":-24,"loop":true,"fade_in_s":0.5,"fade_out_s":1.0}}
```

这是普通背景音乐混音配置；时长与增益是本片的编辑选择，不能把示例数值强加到所有视频。

## 预览和终稿

必须是完整视频。低分辨率预览不能截短为样片，也不能省略终稿计划采用的字幕、音乐或主要动效。
预览批准绑定实际视频、EDL、依赖资产、封面清单与图片及QA。精简入口在预览阶段保留最终质量1920长边内部母版，以同一母版生成1280长边审片版；母版指纹和检查报告写入预览记录并参与审批绑定。用户确认前，母版不能作为已批准终稿交付。
终稿优先复制经过哈希校验的同一母版，封面沿用已审图片；相同视频字节直接复用母版检查。老项目没有母版记录时才沿用原渲染路径。缓存/QA被改或缺失时不得复制交付。
最终交付 MP4 与封面 PNG/JPG，并保留 EDL、素材指纹、分镜、字幕、动效/封面源文件和确认记录，方便继续修改。
源文件未复制到交付包时应说明其仍依赖原素材路径；不声称已生成剪映、Premiere 或 Resolve 原生工程。

完整预览检查至少包括：文件存在、完整解码、视频/音轨、画幅、帧率、预期完整时长、响度/峰值测量；再查看片头片尾、关键内容和每个剪点。相同母版交付不重复整套视觉/critic检查；局部修改只复核改动处及相邻剪点，新编码仍检查完整文件。
不把机器检测通过称为所有审美、语义、版权或平台发布要求均已验收。

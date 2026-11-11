# 使用 Hypit 分析参考视频

用户已指定参考视频环节使用 Hypit。从当前会话的可用Skill目录定位官方Hypit Skill，不假设其他电脑的安装路径。
开始此环节时读取它及其 `references/creation/reference-video.md`。
参考片先作为结构、节奏和视觉证据，不自动成为可复用素材、人物、音乐或模型输入的授权。

## 实际工具入口

历史验证过的 CLI 版本为 `@hypit/hypit@0.3.1`；新电脑需自行安装并通过runtime.local.json的hypit_dir或本地hypit-local安装定位。其他版本先实测适配器。
从本工作区调用：

```text
node hypit-local/run.cjs version --json
工作流工具.cmd inventory --project <项目目录>
工作流工具.cmd reference --project <项目目录>
工作流工具.cmd reference-detail --project <项目目录> --reference-id <清单中的R开头ID> --start 6.8 --end 8.4
```

基础命令实际调用 Hypit 的 `media probe / boundaries / tile`，输出唯一版本的证据目录和
`edit/analysis/hypit/manifest.json`，记录输入与产物哈希、版本和调用命令。
`reference-detail` 调用 `media tiles --every-frame`，保留关键区间所有原始帧，按页输出图片。
Hypit 输出拒绝覆盖，所以重复分析会创建新版本。增加或更改证据会使关联的旧思路确认失效。

必要时可直接调用同一安装：

```text
node hypit-local/run.cjs media frames <参考片> --at 1.2,2.4,3.6 --label-time --to <新目录> --json
node hypit-local/run.cjs media cut <参考片> --start 1 --end 3 --label-time --to <新片段.mp4> --json
```

直接调用的额外证据要在分析中标出来源和用途；纳入确认快照的密集区间优先用 `reference-detail`。
Windows 沙盒若在 `media cut` 原子发布文件时报硬链接 `EPERM`，先核对输出状态，再通过受支持的执行权限重试同一已授权任务；不能把临时文件或失败命令当成已交付片段。
完整 FFprobe 清单仍是旋转、显示画幅等技术信息的依据，不被 Hypit quick probe 的简单尺寸覆盖。
变化候选只是机械邻帧差异，不是已理解的镜头语义。

## 从证据到剪辑方案

1. 先读全片结构：开场、展开、重点、转折、收束及行动提示；记录各段参考源时间码。
2. 口播读取真实转写与说话时间。Hypit 的 `transcribe` 需要已选定并准备好的 WhisperX Endpoint；本地模型、中文对齐模型或云账户未就绪时，明确哪些语音信息尚未核验，不从截图编造文案。
3. 查看变化处的连续画面，追踪构图、景别、字幕、图文层、动效出入、音乐和音效如何配合。密集特效使用逐帧区间，不只看抽样索引。
4. 将关键做法映射到用户自己的素材ID与源区间，标明采用、改编或不采用。缺少对应素材就提出缺项或替代。
5. 给出与本次目标相符的创作方案。思路确认后才进入有真实截图的分镜；保留思路、分镜、预览三个真人确认点。

沿用 Hypit 的文件分工，将全片解释放在项目 `edit/01_strategy/ANALYSIS.md`，可定位的时间关系放在
`TIMELINE.md`；`reference_analysis.md` 为汇总与素材映射入口，链接这两个文件和实际证据。
同一详细结论在一处维护，其余文件引用它。

| 参考时间码 | 内容与叙事作用 | 画面/字幕/声音做法 | 本片素材与源区间 | 采用或改编方式 | 证据与缺口 |
| --- | --- | --- | --- | --- | --- |

本工作流主要剪用户现有素材。Hypit 的生成模型和 SVML 制作能力在该片确有需要时再启用，
不因安装就自动重生画面或消费生成额度。
本地媒体命令成功不等于转写、网页下载、浏览器渲染或第三方模型全部就绪。

通过工作流工具入口会自动加载runtime环境；直接运行node包装器时须提供VIDEO_WORKFLOW_HYPIT_DIR和VIDEO_USE_FFMPEG_PATH，优先使用reference命令。

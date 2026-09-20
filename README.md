# STEP to ACIS Converter

Windows STEP batch conversion through a separately licensed local Ansys SpaceClaim 2022 R2 or 2026 R1 installation. It imports `.stp` / `.step` and exports ACIS `.sab` or `.sat`; geometry conversion is performed by the local CAD installation.

当前版本为 1.1.0，支持点选多个 STEP 文件，并保留无控制台启动和自检进度反馈；旧的已发布 ZIP 不会因源码更新自动获得新版本支持。

This is an independent third-party project. It is not affiliated with, endorsed by, or sponsored by Ansys or ZEISS. Ansys, SpaceClaim, ZEISS, and other product names are trademarks of their respective owners and are used only to describe compatibility. Users must obtain and comply with their own Ansys SpaceClaim license. This project does not distribute Ansys software, DLLs, documentation, or license material.

## 普通用户快速开始

1. 从[最新发布版](https://github.com/GUZHUYAXIAN/step-to-acis-converter/releases/latest)下载 Windows x64 ZIP 与同名 `.sha256`。
2. 用发布版专属 SHA-256 sidecar 校验 ZIP，完整解压后运行 `STEP转ACIS.exe`；不要只复制 EXE。
3. 完成环境自检，再选择不同的输入和输出目录。接收方无需安装 Python。

Windows SmartScreen 可能对未签名程序显示警告；请仅从项目 Release 下载并遵循组织安全政策。

## 兼容性与验证边界

- 支持目标是 Windows x64、Ansys SpaceClaim 2022 R2 和 SpaceClaim 2026 R1；每台机器均须完成本地能力探测。
- 2022 R2 使用 V22 脚本接口，保留默认 SAB / ACIS V22 / Millimeters 和原有版本选择。
- 2026 R1 使用 V261 脚本接口，只输出 ACIS 5.0（V5），可选 SAB/SAT，默认 Millimeters；ACIS 装配导出会扁平化。V261 是脚本接口版本，不是 ACIS 文件版本。
- 新版简单实体的脚本导入、导出及尺寸/体积回读已做可行性实测；复杂零件、装配及旧版真实环境回归须单独验证，不能由单元测试推断通过。
- 程序会自动扫描本机安装，找不到时可手动选择；检测到但未经验证的版本会被阻止。
- 无模型 Headless 探测不读取 STEP，也不创建 SAB/SAT。源 `.stp` / `.step` 只读；默认 Skip，Overwrite 只在独立输出目录中暂存后原子替换。
- 公开验证以 `sample-small.step`、`sample-medium.step`、`sample-large.step` 与 `sample-invalid.step` 表示覆盖范围；仓库不包含 CAD 文件或派生数据。

## GUI 与 CMD

便携版启动不再附带空白控制台，自检显示当前步骤、动态进度条和已用时间。转换页可使用“点选 STEP 文件…”通过 Ctrl/Shift 多选文件，核对清单后只转换所选文件，也可切回整文件夹扫描。输入与输出目录必须不同。

运行 `run_converter_gui.bat` 使用 GUI；`run_converter.bat` 和 CLI 参数继续适合脚本化。GUI 与 CMD 显示输入/输出、进度、成功/失败/跳过计数和日志路径；CAD 进程以 Headless 模式运行。高级设置包含 ACIS Version、chunk size、无响应超时和进程级重试。

GUI 默认 SAB、Skip 和 Millimeters；2022 R2 默认 ACIS V22，2026 R1 固定 V5，也可选择 SAT 或 Overwrite。切换版本时不适用的历史 ACIS 设置会在界面提示调整，开始前请确认。没有取消或强制停止按钮；转换中请等待批次完成后正常关闭。

自动选择优先沿用仍有效的上次选择；没有历史选择时优先 2026 R1，可在自检窗口手动切换。两个版本分别探测、缓存；旧版 V22 的缓存不能授权新版 V261。

```text
%LOCALAPPDATA%\SpaceClaimStepToAcis\gui_settings.json
```

该向后兼容的本地设置目录不会修改 `converter_config.json`。能力缓存、探测记录和 GUI 设置仅保存在本地，不上传；转换日志写入用户选择的输出目录。

## 开发

```powershell
$env:PYTHONPATH = 'src'
python -X utf8 -m unittest discover -s tests
```

复制 `converter_config.example.json` 为本机 `converter_config.json`。不要提交本地配置、`spaceclaim_cli_profile.json`、模型、日志、缓存或验证材料。

2026 R1 的 CLI 配置须设置实际 `spaceclaim_exe` 和 `"acis_version": "V5"`；指定 V22 会报错，不会自动降级。先运行 `python tools/probe_spaceclaim.py --exe "实际安装路径/SpaceClaim.exe"`，然后将输出的缓存路径传给转换命令的 `--capability-profile`。该探测同时支持 2022 R2/2026 R1，全部使用无模型 Headless 模式。

更新内容和验证范围见 [v1.1.0 发布说明](packaging/RELEASE_NOTES_v1.1.0.md)。

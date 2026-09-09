# STEP to ACIS Converter

Windows STEP batch conversion through a separately licensed local Ansys SpaceClaim 2022 R2 installation. It imports `.stp` / `.step` and exports ACIS `.sab` or `.sat`; geometry conversion is performed by the local CAD installation.

This is an independent third-party project. It is not affiliated with, endorsed by, or sponsored by Ansys or ZEISS. Ansys, SpaceClaim, ZEISS, and other product names are trademarks of their respective owners and are used only to describe compatibility. Users must obtain and comply with their own Ansys SpaceClaim license. This project does not distribute Ansys software, DLLs, documentation, or license material.

## 普通用户快速开始

1. 从[最新发布版](https://github.com/GUZHUYAXIAN/step-to-acis-converter/releases/latest)下载 Windows x64 ZIP 与同名 `.sha256`。
2. 用发布版专属 SHA-256 sidecar 校验 ZIP，完整解压后运行 `STEP转ACIS.exe`；不要只复制 EXE。
3. 完成环境自检，再选择不同的输入和输出目录。接收方无需安装 Python。

Windows SmartScreen 可能对未签名程序显示警告；请仅从项目 Release 下载并遵循组织安全政策。

## 兼容性与验证边界

- 已验证目标是 Windows x64 和 Ansys SpaceClaim 2022 R2。默认 SAB / ACIS V22 / Millimeters 组合在既定兼容场景中得到验证；其他产品、版本、ACIS 版本或单位不得据此推断兼容。
- 程序会自动扫描本机安装，找不到时可手动选择；检测到但未经验证的版本会被阻止。
- 无模型 Headless 探测不读取 STEP，也不创建 SAB/SAT。源 `.stp` / `.step` 只读；默认 Skip，Overwrite 只在独立输出目录中暂存后原子替换。
- 公开验证以 `sample-small.step`、`sample-medium.step`、`sample-large.step` 与 `sample-invalid.step` 表示覆盖范围；仓库不包含 CAD 文件或派生数据。

## GUI 与 CMD

运行 `run_converter_gui.bat` 使用 GUI；`run_converter.bat` 和 CLI 参数继续适合脚本化。GUI 与 CMD 显示输入/输出、进度、成功/失败/跳过计数和日志路径；CAD 进程以 Headless 模式运行。高级设置包含 ACIS Version、chunk size、无响应超时和进程级重试。

GUI 默认 SAB、Skip、ACIS V22 和 Millimeters，也可选择 SAT 或 Overwrite。没有取消或强制停止按钮；转换中请等待批次完成后正常关闭。

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

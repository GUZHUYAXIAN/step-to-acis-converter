# STEP to ACIS Converter — Windows x64 portable package

This is an independent third-party project. It is not affiliated with, endorsed by, or sponsored by Ansys or ZEISS. Product names are trademarks of their respective owners and are used only to describe compatibility. Obtain and comply with your own Ansys SpaceClaim license; this package does not distribute proprietary CAD software, DLLs, documentation, or license material.

## 快速开始

1. 从项目 Release 下载 Windows x64 ZIP 与 `.sha256`，核对 SHA-256 后完整解压；不要只复制 EXE。
2. 双击 `STEP转ACIS.exe`，以窗口模式启动，不再附带空白控制台。接收方无需安装 Python；Python、Tcl/Tk 和运行资源均在 `_internal` 中。
3. 环境自检期间显示动态进度条、当前步骤和已用时间；程序自动扫描安装位置，找不到时可手动选择 `SpaceClaim.exe`。进度条表示正在运行，不代表完成百分比。缓存有效时很快完成；首次或重新探测会显示 1/3、2/3、3/3，每步等待 SpaceClaim 最多 120 秒。检查期间下拉栏和操作按钮暂时禁用，结束后恢复。
4. 支持 SpaceClaim 2022 R2 和 SpaceClaim 2026 R1，均须完成本机能力探测。优先沿用上次有效选择，无历史选择时优先 2026 R1；可手动切换，其他版本不放行。
5. 无模型 Headless 探测不读取 STEP，也不生成 SAB/SAT。明确选择不同输入/输出目录后才能转换；默认 SAB、Skip、Millimeters。2022 R2 默认 ACIS V22，2026 R1 固定 ACIS 5.0（V5）。没有取消或强制停止按钮。
6. 切换软件版本后，请确认界面显示的输出版本。新版没有旧的 ACIS 版本选择功能，不能承诺 V22 输出；装配导出会扁平化。历史设置不适用时会显示调整提示。

## 点选几个模型转换

进入转换界面后，选择输入文件夹，再点“点选 STEP 文件…”。在文件对话框中用 Ctrl 或 Shift 多选 `.stp` / `.step` 文件，确认界面显示的已选数量及文件名；也可以直接点选文件，程序会填入其所在文件夹。点选清单仅针对当前一次选择，重新点选会替换清单，取消对话框则保留原选择。

选择与输入不同的输出目录后开始转换。点选模式不扫描未选中的文件或子目录，“包含子文件夹”暂时禁用；“切回文件夹扫描”恢复原批量功能。修改输入目录会清除旧清单；重启不会恢复具体文件清单。所选文件删除或移动后会报错，需要重新点选。输入与输出目录相同会被保护校验拦截，这与目录中是否混有其他格式文件无关。

## SmartScreen 与本地数据

未签名 EXE 可能触发 Windows SmartScreen。请从项目 Release 下载，先核对 `.sha256`，再按组织安全政策决定是否运行。自检缓存、选择记录和 GUI 设置仅保存在 `%LOCALAPPDATA%\SpaceClaimStepToAcis`，不上传；转换日志写入用户选择的输出目录。

窗口模式的诊断输出保存在 `%LOCALAPPDATA%\SpaceClaimStepToAcis\logs\application-*.log`，每次启动使用独立文件；本地目录无法写入时使用 `%TEMP%\SpaceClaimStepToAcis\logs`。日志只保存在本机，可能包含文件路径。转换界面日志和输出目录中的 CSV/TXT 继续保留。

## 支持边界

这是 v1.1.0 双版本便携包。旧的 Windows x64 / SpaceClaim 2022 R2 / SAB / ACIS V22 / Millimeters 转换路径保留，新版增加 V261 脚本路径。简单实体的新版接口可行性已有实测；复杂模型、旧版真实环境和下游软件仍需分别验证。先用独立输出目录和测试模型验证后再用于工作。

两个版本的本地能力缓存分别验证 EXE 路径、SHA-256、文件/产品版本和脚本 API，不复用不匹配的验证结果。没有服务、驱动、注册表写入、自动更新、遥测或自动上传。

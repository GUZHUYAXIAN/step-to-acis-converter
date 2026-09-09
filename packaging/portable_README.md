# STEP to ACIS Converter — Windows x64 portable package

This is an independent third-party project. It is not affiliated with, endorsed by, or sponsored by Ansys or ZEISS. Product names are trademarks of their respective owners and are used only to describe compatibility. Obtain and comply with your own Ansys SpaceClaim license; this package does not distribute proprietary CAD software, DLLs, documentation, or license material.

## 快速开始

1. 从项目 Release 下载 Windows x64 ZIP 与 `.sha256`，核对 SHA-256 后完整解压；不要只复制 EXE。
2. 双击 `STEP转ACIS.exe`。接收方无需安装 Python；Python、Tcl/Tk 和运行资源均在 `_internal` 中。
3. 完成环境自检；程序自动扫描安装位置，找不到时可手动选择 `SpaceClaim.exe`。
4. 只有 SpaceClaim 2022 R2 会被自动放行；其他版本显示“检测到但未经验证”。
5. 无模型 Headless 探测不读取 STEP，也不生成 SAB/SAT。明确选择不同输入/输出目录后才能转换；安全默认值是 SAB、Skip、ACIS V22、Millimeters。没有取消或强制停止按钮。

## SmartScreen 与本地数据

未签名 EXE 可能触发 Windows SmartScreen。请从项目 Release 下载，先核对 `.sha256`，再按组织安全政策决定是否运行。自检缓存、选择记录和 GUI 设置仅保存在 `%LOCALAPPDATA%\SpaceClaimStepToAcis`，不上传；转换日志写入用户选择的输出目录。

## 支持边界

本发行版仅验证 Windows x64、SpaceClaim 2022 R2 和默认 SAB / ACIS V22 / Millimeters 组合。没有服务、驱动、注册表写入、自动更新、遥测或自动上传。

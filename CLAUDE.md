# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言与工作方式

- 始终使用中文与用户交流；代码注释、变量命名、commit message 按现有风格（中英均可）。
- **执行脚本（写 .py 验证脚本、跑训练/导出/推理命令、做数值一致性验证）前必须先征求用户同意**：先给出直接分析与打算执行的内容及目的，用户明确同意后再执行。

## 项目简介

基于 PyQt5 的 Windows 桌面 2D 人体姿态标注工具。工作流为「图片文件夹 + COCO JSON」，支持同一张图多人标注、编辑、保存。当前配置为 COCO17（17 关键点 + 19 骨骼），通过修改 `pose_config.py` 可适配其他骨架。

## 常用命令

- 安装依赖：`pip install -r requirements.txt`
  - **必须用 `opencv-python-headless`**；若装的是 `opencv-python`，其自带 Qt 插件会与 PyQt 冲突导致无法启动。
- 运行：`python annotator.py`（GUI，需图形环境）
- 语法检查：`python -m py_compile annotator.py`
- 无测试框架、无构建/打包流程；数据均为本地文件。

## 架构

程序集中在 `annotator.py`（约 1500 行单文件），由 4 个类组成：

- `ImageFolderProcessor`（[annotator.py:40](annotator.py#L40)）：维护「帧号 → 图片文件路径」映射。纯数字文件名按数字解析帧号；带字符文件名自然排序（数字段按数值）后在数字帧之后连续分配帧号。`rebuild_from_annotations()` 按 COCO `images` 列表重建映射（只保留文件夹中真实存在的文件），并把缺失的 `frame_number` 写回 image dict 供下拉框与帧匹配使用。
- `KeypointScene`（[annotator.py:196](annotator.py#L196)）/ `ImageViewer`（[annotator.py:178](annotator.py#L178)）：图像渲染与鼠标交互。核心状态：
  - `people`：`[{kp_name: (x, y, v)}]`，当前帧的每一个人（多人标注）
  - `original_people`：加载时的坐标快照，`Reset` 时恢复用
  - `current_person_index` / `current_keypoint`：当前编辑的人 / 选中的点
  - 所有编辑（左键放置、吸附拖拽、删除、v 切换）都发生在这里，通过三个回调通知主窗口：`keypoint_updated`、`keypoint_selected`、`placement_changed`。
- `IntegratedPoseTool`（QMainWindow，[annotator.py:510](annotator.py#L510)）：控制器。持有 `self.annotations`（COCO dict）、`output_dir`、`image_folder_processor`，几乎全部业务逻辑在此。场景回调在 `initUI` / `displayFrame` 中接线。

`pose_config.py` 的 `PoseConfig` 是关键点/骨骼/颜色唯一配置源：`keypoint_names`（COCO 英文键）、`keypoint_display_names`（界面中文名）、`skeleton`（COCO 1-based 索引连接）、`keypoint_colors`。改骨架只需改此文件。

### 关键设计：两个数据源，只在保存时对齐

本程序最核心、需读多个文件才能理解的设计：

- **当前帧的编辑只存在于 `KeypointScene.people`（工作状态）**；
- **`self.annotations`（COCO dict）是持久层**；
- 两者只在 `saveAnnotations()`（[annotator.py:1339](annotator.py#L1339)）时对齐：按 `scene.people` 重建该 image 的 `annotations`——修改写回、新增的人追加、被删除的人丢弃。

由此派生出的行为：
- 「删除 person」只有保存才真正落地；若切帧时选「不保存」，本帧全部修改（含删除的人）都会被丢弃、切回后恢复。
- `current_frame_dirty` 标记当前帧是否有未保存修改；A/D 切帧据此决定是否弹窗询问，Tab 切人自动保存，S 静默保存。

### 保存管线

`writeAnnotationsFile()`（[annotator.py:906](annotator.py#L906)）写输出目录 `annotations.json`，写前先把旧文件复制为 `annotations.json.bak`。新帧首次保存时：分配 image id → 把当前帧以 `{image_id:012d}.jpg` 存入输出目录 `frames/` → 写回 COCO。

### 数据格式

COCO 人体关键点标准，`images` 额外扩展 `video_file`（图片文件夹名）与 `frame_number` 用于帧关联。`keypoints` 为扁平三元组 `(x, y, v)`：v=0 未标注 / 1 遮挡·估计 / 2 可见。同一 `image_id` 对应多条 `annotations` 即多人。

### 其他实现细节

- 吸附选点阈值 `KEYPOINT_SNAP_THRESHOLD = 15`（[annotator.py:20](annotator.py#L20)，像素）。
- 关键点列表显示中文名，但 `QListWidgetItem` 的 `Qt.UserRole` 存英文 key，内部与 COCO JSON 一致。
- `prefer_pyqt_qt_plugins()`（[annotator.py:23](annotator.py#L23)）启动时剔除 QT 插件路径中的 cv2，规避 OpenCV 自带 Qt 插件与 PyQt 冲突。
- 快捷键：A/D 切帧、W 放置模式开关、T/Delete 删除点、S 保存、Tab 切人（见 `initUI` 的 QShortcut 段）。

## 目录

- `annotator.py`：主程序
- `pose_config.py`：配置（唯一的骨架适配点）
- `demo/coco-pose-2017.json`：示例 COCO 标注文件（多人）
- `images/`：README 截图

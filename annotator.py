import sys
import json
import os
import re
import shutil
import cv2
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QLabel, QPushButton, QFileDialog,
                           QListWidget, QListWidgetItem, QGraphicsView,
                           QGraphicsScene, QSlider, QSpinBox, QMessageBox,
                           QComboBox, QTextEdit, QShortcut)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QTextCursor
from PyQt5.QtCore import Qt, QRectF

from pose_config import*

# 吸附选点阈值（像素）：默认未选中任何点时，点击关键点附近距离内会自动选中该点
# （代替手动在列表中选择）。数值越小需点得越准，越大越容易吸附。调试时可在此调整。
KEYPOINT_SNAP_THRESHOLD = 15


def prefer_pyqt_qt_plugins():
    """Avoid OpenCV's bundled Qt plugins shadowing PyQt's platform plugins."""
    for env_var in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH"):
        plugin_path = os.environ.get(env_var, "")
        if not plugin_path:
            continue

        paths = [
            path for path in plugin_path.split(os.pathsep)
            if "cv2" not in path
        ]
        if paths:
            os.environ[env_var] = os.pathsep.join(paths)
        else:
            os.environ.pop(env_var, None)


class ImageFolderProcessor:
    valid_extensions = {".jpg", ".jpeg", ".png"}

    def __init__(self):
        self.folder_path = None
        self.video_file = None
        self.frame_paths = {}
        self.frame_numbers = []
        self.frame_width = 0
        self.frame_height = 0
        self.fps = 0

    @staticmethod
    def _natural_sort_key(filename):
        """自然排序键：数字段按数值、文本段按字典序比较（如 img2 < img10）。"""
        return [int(part) if part.isdigit() else part.lower()
                for part in re.split(r'(\d+)', filename)]

    def load_folder(self, folder_path):
        self.folder_path = folder_path
        self.video_file = os.path.basename(os.path.normpath(folder_path))
        self.frame_paths = {}
        self.frame_numbers = []
        self.frame_width = 0
        self.frame_height = 0

        numeric_paths = {}
        named_files = []
        for filename in os.listdir(folder_path):
            stem, ext = os.path.splitext(filename)
            if ext.lower() not in self.valid_extensions:
                continue
            if stem.isdigit():
                numeric_paths[int(stem)] = os.path.join(folder_path, filename)
            else:
                named_files.append(filename)

        # 纯数字文件名按原行为解析帧号；带字符文件名自然排序后从数字帧号之后连续分配
        named_files.sort(key=self._natural_sort_key)
        next_frame = (max(numeric_paths) + 1) if numeric_paths else 0
        for filename in named_files:
            self.frame_paths[next_frame] = os.path.join(folder_path, filename)
            next_frame += 1
        self.frame_paths.update(numeric_paths)

        self.frame_numbers = sorted(self.frame_paths)
        if not self.frame_numbers:
            return False

        first_frame = self.get_frame(self.frame_numbers[0])
        if first_frame is None:
            return False

        self.frame_height, self.frame_width = first_frame.shape[:2]
        return True

    def rebuild_from_annotations(self, images, folder_path):
        """按 COCO images 列表重建帧映射：frame_number -> 文件夹内实际文件路径。

        只保留 file_name 在当前文件夹中真实存在的图片；已有 frame_number 的直接
        复用，缺失时纯数字文件名按数字解析，其余按保留顺序从已确定帧号之后分配。
        并把分配好的 frame_number 写回 image dict，供下拉框与帧匹配使用。
        """
        self.folder_path = folder_path
        self.video_file = os.path.basename(os.path.normpath(folder_path))
        self.frame_paths = {}
        self.frame_numbers = []
        self.frame_width = 0
        self.frame_height = 0

        existing_files = set(os.listdir(folder_path))
        resolved = []  # (frame_number, path)
        pending = []   # (image, path)：无 frame_number 且非纯数字命名的文件，按顺序分配
        max_frame = -1

        for image in images:
            file_name = os.path.basename(image.get('file_name', ''))
            if not file_name or file_name not in existing_files:
                continue
            path = os.path.join(folder_path, file_name)
            frame_number = image.get('frame_number')
            if isinstance(frame_number, (int, float)):
                frame_number = int(frame_number)
            elif isinstance(frame_number, str) and frame_number.isdigit():
                frame_number = int(frame_number)
            else:
                frame_number = None
            if frame_number is None:
                stem = os.path.splitext(file_name)[0]
                if stem.isdigit():
                    frame_number = int(stem)
            if frame_number is not None:
                image['frame_number'] = frame_number  # 写回，供下拉框与查找使用
                resolved.append((frame_number, path))
                if frame_number > max_frame:
                    max_frame = frame_number
            else:
                pending.append((image, path))

        next_frame = max_frame + 1
        for image, path in pending:
            image['frame_number'] = next_frame
            self.frame_paths[next_frame] = path
            next_frame += 1
        for frame_number, path in resolved:
            self.frame_paths[frame_number] = path

        self.frame_numbers = sorted(self.frame_paths)
        if not self.frame_numbers:
            return False

        first_frame = self.get_frame(self.frame_numbers[0])
        if first_frame is None:
            return False

        self.frame_height, self.frame_width = first_frame.shape[:2]
        return True

    def frame_range(self):
        if not self.frame_numbers:
            return None
        return self.frame_numbers[0], self.frame_numbers[-1]

    def get_frame(self, frame_number):
        image_path = self.frame_paths.get(frame_number)
        if image_path is None:
            return None
        return cv2.imread(image_path)

    def save_frame(self, frame_number, output_dir, image_id):
        frame = self.get_frame(frame_number)
        if frame is not None:
            filename = f"{image_id:012d}.jpg"
            output_path = os.path.join(output_dir, filename)
            cv2.imwrite(output_path, frame)
            return filename
        return None

class ImageViewer(QGraphicsView):
    def __init__(self, pose_config, parent=None):
        super().__init__(parent)
        self.setScene(KeypointScene(pose_config))
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(30, 30, 30))
        self.setFrameShape(QGraphicsView.NoFrame)
        
    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        zoom_factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(zoom_factor, zoom_factor)
            
class KeypointScene(QGraphicsScene):
    def __init__(self, pose_config, parent=None):
        super().__init__(parent)
        self.pose_config = pose_config
        self.people = []                # 每个人一份 {kp_name: (x,y,v)}（当前可编辑）
        self.original_people = []       # 加载时的原始坐标快照，供 Reset 恢复
        self.current_person_index = 0   # 当前正在编辑的人
        self.current_keypoint = None
        self.keypoint_items = {}        # {(person_index, kp_name): [items]}
        self.keypoint_updated = None
        self.keypoint_selected = None   # 吸附选中关键点时回调 (kp_name)
        self._drag_keypoint = None      # 正在拖拽移动的关键点名
        self._dragged = False           # 本次按下是否发生实际拖动
        self._drag_start_pos = None     # 按下时的 scene 坐标（用于区分单击/拖动）
        self.bbox_item = None
        self.skeleton_lines = []  # Add this line to track skeleton lines
        self.editing_enabled = True

        # Colors for different states
        self.highlighted_color = QColor(255, 255, 0)  # Yellow for highlighted
        self.visible_color = QColor(0, 255, 0)       # Green for visible
        self.invisible_color = QColor(255, 165, 0)    # Orange for invisible but labeled
        self.other_person_color = QColor(180, 180, 180)  # 非当前人的灰色
        self.visibility_mode = 2  # 放置关键点时的可见性：2=可见，1=遮挡/估计
        self.placement_enabled = False  # W 键开关：开启后才能用左键放置未标注关键点
        self.placement_changed = None   # 放置模式状态变化回调 (on: bool)

    @property
    def keypoints(self):
        """当前正在编辑的人的 keypoints（{kp_name: (x,y,v)}）。

        people 为空（已删除全部 person）时返回空 dict，不自动创建。
        """
        if not self.people:
            return {}
        if len(self.original_people) < len(self.people):
            self.original_people.append({})
        idx = min(self.current_person_index, len(self.people) - 1)
        return self.people[idx]

    def set_people(self, people_list):
        """批量设置所有人的 keypoints（允许空列表，空图自动兜底 1 个空人）。

        同时保存原始坐标快照 original_people，Reset 时恢复到该快照。
        """
        self.people = [dict(p) for p in people_list]
        if not self.people:
            self.people.append({})
        self.original_people = [dict(p) for p in self.people]
        self.current_person_index = max(0, min(self.current_person_index,
                                               len(self.people) - 1))

    def add_person(self):
        """追加一个空人并切换到它，返回新 index。"""
        self.people.append({})
        self.original_people.append({})
        self.current_person_index = len(self.people) - 1
        return self.current_person_index

    def remove_person(self, index):
        """删除指定人并修正 current_person_index。"""
        if index < 0 or index >= len(self.people):
            return
        del self.people[index]
        if index < len(self.original_people):
            del self.original_people[index]
        self.current_person_index = max(0, min(self.current_person_index,
                                               len(self.people) - 1))

    def reset_keypoint_to_original(self, keypoint_name):
        """把当前人指定点恢复为加载时的原始坐标（v 一并恢复）；原始无此点则删除。"""
        if not self.original_people:
            return
        idx = min(self.current_person_index, len(self.original_people) - 1)
        orig = self.original_people[idx]
        if keypoint_name in orig:
            self.keypoints[keypoint_name] = tuple(orig[keypoint_name])
        else:
            self.keypoints.pop(keypoint_name, None)
        self.update_keypoint_visuals()

    def _find_nearby_keypoint(self, pos):
        """返回点击位置附近（KEYPOINT_SNAP_THRESHOLD 内）最近的当前人关键点名，无则 None。"""
        threshold = KEYPOINT_SNAP_THRESHOLD
        best_name = None
        best_dist = threshold
        for kp_name, (x, y, _) in self.keypoints.items():
            dist = ((pos.x() - x) ** 2 + (pos.y() - y) ** 2) ** 0.5
            if dist <= best_dist:
                best_dist = dist
                best_name = kp_name
        return best_name

    def _try_snap_select(self, pos):
        """尝试吸附选中 pos 附近的关键点；命中则选中该点并允许按住拖动。"""
        kp_name = self._find_nearby_keypoint(pos)
        if kp_name is None or kp_name == self.current_keypoint:
            return
        self.current_keypoint = kp_name
        self.update_keypoint_visuals()
        if self.keypoint_selected:
            self.keypoint_selected(kp_name)
        self._drag_keypoint = kp_name
        self._dragged = False
        self._drag_start_pos = pos

    def mousePressEvent(self, event):
        if not self.editing_enabled:
            return

        pos = event.scenePos()

        # 右键：取消当前选择，回到空选默认状态
        if event.button() == Qt.RightButton:
            if self.current_keypoint is not None:
                self.current_keypoint = None
                self._drag_keypoint = None
                self.update_keypoint_visuals()
                if self.keypoint_selected:
                    self.keypoint_selected(None)
            return

        if event.button() == Qt.LeftButton:
            if self.current_keypoint:
                kp = self.current_keypoint
                if kp in self.keypoints:
                    # 点击位置距当前选中点超过 3 倍吸附阈值 → 视为选择新的点
                    x, y, _ = self.keypoints[kp]
                    dx = pos.x() - x
                    dy = pos.y() - y
                    far_threshold = KEYPOINT_SNAP_THRESHOLD * 1
                    if dx * dx + dy * dy > far_threshold * far_threshold:
                        self._try_snap_select(pos)
                        return
                    # 在范围内：长按左键拖动移动（单击不移动）
                    self._drag_keypoint = kp
                    self._dragged = False
                    self._drag_start_pos = pos
                else:
                    # 新标注的点：需先按 W 键开启放置模式后才能左键放置
                    if not self.placement_enabled:
                        return
                    self.keypoints[kp] = (pos.x(), pos.y(), self.visibility_mode)
                    self.update_keypoint_visuals()
                    if self.keypoint_updated:
                        self.keypoint_updated(kp, True)
                    self.update_bounding_box()
                    # 放置一个关键点后自动关闭放置模式（回到选中/编辑状态）
                    self.placement_enabled = False
                    if self.placement_changed:
                        self.placement_changed(False)
            else:
                # 未选点：点击关键点附近区域 → 吸附选中该点（代替手动列表选择）
                self._try_snap_select(pos)

    def mouseMoveEvent(self, event):
        # 拖动已选中/已吸附的关键点，跟随鼠标移动（v 保持不变）
        if (self._drag_keypoint and (event.buttons() & Qt.LeftButton)):
            kp = self._drag_keypoint
            if kp in self.keypoints:
                cur = event.scenePos()
                # 3px 内的移动视为单击抖动，不移动点
                if self._drag_start_pos is not None:
                    dx = cur.x() - self._drag_start_pos.x()
                    dy = cur.y() - self._drag_start_pos.y()
                    if dx * dx + dy * dy < 9:
                        super().mouseMoveEvent(event)
                        return
                _, _, v = self.keypoints[kp]
                self.keypoints[kp] = (cur.x(), cur.y(), v)
                self._dragged = True
                self.update_keypoint_visuals()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # 拖动结束：刷新列表状态与 bbox
        if self._drag_keypoint and self._dragged:
            kp = self._drag_keypoint
            if self.keypoint_updated:
                self.keypoint_updated(kp, True)
            self.update_bounding_box()
        self._drag_keypoint = None
        self._dragged = False
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def update_keypoint_visuals(self):
        # Clear existing visualizations
        for items in self.keypoint_items.values():
            for item in items:
                self.removeItem(item)
        self.keypoint_items.clear()

        # Draw skeleton first
        self.draw_skeleton()

        # Draw keypoints for all people
        for person_index, person in enumerate(self.people):
            is_current = person_index == self.current_person_index
            for kp_name, (x, y, v) in person.items():
                items = []

                if is_current:
                    # 当前人用 pose_config 颜色
                    base_color = self.pose_config.keypoint_colors.get(kp_name, QColor(0, 255, 0))
                    if kp_name == self.current_keypoint:
                        color = QColor(255, 255, 0)  # Highlight in yellow
                    else:
                        color = QColor(base_color)
                    # Adjust opacity based on visibility
                    if v == 1:  # Labeled but not visible
                        color.setAlpha(128)
                else:
                    # 非当前人用灰色区分
                    color = QColor(self.other_person_color)
                    if v == 1:
                        color.setAlpha(96)

                # Draw point (keypoint name label is hidden)
                ellipse = self.addEllipse(x-3, y-3, 6, 6, QPen(color), color)
                items.append(ellipse)
                self.keypoint_items[(person_index, kp_name)] = items

        self.update_bounding_box()
    
    def calculate_bbox(self):
        """Calculate bounding box from keypoints"""
        if not self.keypoints:
            return None
            
        valid_x = [x for x, y, v in self.keypoints.values()]
        valid_y = [y for x, y, v in self.keypoints.values()]
        
        if valid_x and valid_y:
            x_min, x_max = min(valid_x), max(valid_x)
            y_min, y_max = min(valid_y), max(valid_y)
            
            # Add padding to make box slightly larger than the keypoints
            padding = 30
            x_min -= padding
            y_min -= padding
            x_max += padding
            y_max += padding
            
            return [x_min, y_min, x_max - x_min, y_max - y_min]
        return None

    def set_current_keypoint(self, keypoint_name):
        """Set the currently selected keypoint and update visuals"""
        self.current_keypoint = keypoint_name
        # Highlight the currently selected keypoint
        self.update_keypoint_visuals()

    def reset_keypoint(self, keypoint_name):
        """Reset (remove) a specific keypoint"""
        if keypoint_name in self.keypoints:
            del self.keypoints[keypoint_name]
            self.update_keypoint_visuals()
            if hasattr(self, 'keypoint_updated'):
                self.keypoint_updated(keypoint_name, False)    
    
    
    # Add skeleton drawing functionality
    def draw_skeleton(self):
        # Clear existing skeleton lines
        for line in self.skeleton_lines:
            self.removeItem(line)
        self.skeleton_lines.clear()

        for person_index, person in enumerate(self.people):
            is_current = person_index == self.current_person_index
            keypoints_list = []
            for kp_name in self.pose_config.keypoint_names:
                if kp_name in person:
                    x, y, v = person[kp_name]
                    keypoints_list.append((x, y, v))
                else:
                    keypoints_list.append((0, 0, 0))

            for connection in self.pose_config.skeleton:
                start_idx = connection[0] - 1
                end_idx = connection[1] - 1

                if (start_idx < len(keypoints_list) and end_idx < len(keypoints_list)):
                    start_x, start_y, start_v = keypoints_list[start_idx]
                    end_x, end_y, end_v = keypoints_list[end_idx]

                    if start_v > 0 and end_v > 0:
                        if is_current:
                            pen = QPen(self.pose_config.skeleton_color)
                            pen.setWidth(2)
                        else:
                            line_color = QColor(self.other_person_color)
                            line_color.setAlpha(160)
                            pen = QPen(line_color)
                            pen.setWidth(1)
                            pen.setStyle(Qt.DashLine)
                        line = self.addLine(start_x, start_y, end_x, end_y, pen)
                        self.skeleton_lines.append(line)  # Store the line

    
    def update_bounding_box(self):
        if self.bbox_item:
            self.removeItem(self.bbox_item)
            self.bbox_item = None
        
        bbox = self.calculate_bbox()
        if bbox:
            pen = QPen(QColor(255, 165, 0))  # Orange color
            pen.setStyle(Qt.DashLine)
            pen.setWidth(2)
            self.bbox_item = self.addRect(bbox[0], bbox[1], bbox[2], bbox[3], pen)


class IntegratedPoseTool(QMainWindow):
    def __init__(self, pose_config):
        super().__init__()
        self.pose_config = pose_config  # Store the pose config
        self.image_folder_processor = ImageFolderProcessor()
        self.active_source = None
        self.current_frame_number = 0
        self.output_dir = None
        self.current_image_data = None
        self.current_annotations_list = []
        self.current_frame_bgr = None
        self.is_syncing_frame_controls = False
        self.last_deleted_keypoint = None  # 最近被删除的关键点（删除后取消选中，Reset 时优先恢复）
        self.current_frame_dirty = False  # 当前帧是否有未保存的修改（A/D 切帧时据此决定是否弹窗）
        self.annotations = self.create_empty_annotations()
        self.initUI()

    def create_empty_annotations(self):
        return {
            "info": {
                "description": "Pose Keypoint Dataset",
                "url": "",
                "version": "1.0",
                "year": datetime.now().year,
                "contributor": "",
                "date_created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "licenses": [{"url": "", "id": 1, "name": ""}],
            "images": [],
            "annotations": [],
            "categories": [self.pose_config.get_category_config()]
        }
        
    def setOutputDirectory(self):
        self.output_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Directory")
        if self.output_dir:
            # Create necessary subdirectories
            os.makedirs(os.path.join(self.output_dir, "frames"), exist_ok=True)
            
            # Check for existing annotations
            annotation_file = os.path.join(self.output_dir, 'annotations.json')
            if os.path.exists(annotation_file):
                try:
                    with open(annotation_file, 'r') as f:
                        self.annotations = json.load(f)
                    self.normalizeAnnotations()
                    # Update frame dropdown with existing annotations
                    self.updateFrameDropdown()
                    QMessageBox.information(self, "Loaded Annotations", 
                                        f"Loaded existing annotations from:\n{annotation_file}\n"
                                        f"Contains {len(self.annotations.get('images', []))} images and "
                                        f"{len(self.annotations.get('annotations', []))} annotations.")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to load existing annotations: {str(e)}")
            else:
                QMessageBox.information(self, "New Annotations", 
                                    f"Will create new annotations file at:\n{annotation_file}")
    
        
    def exitProgram(self):
        reply = QMessageBox.question(self, 'Exit Program',
                                   'Are you sure you want to exit?',
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.close()

    def initUI(self):
        self.setWindowTitle('Integrated Pose Annotation & Visualization Tool')
        self.setGeometry(100, 100, 1400, 800)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        
        # Create image viewer with pose config
        self.viewer = ImageViewer(self.pose_config)
        layout.addWidget(self.viewer, stretch=2)
        
        # Create right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        layout.addWidget(right_panel, stretch=1)
        
        # File controls section
        file_group = QVBoxLayout()
        load_image_folder_btn = QPushButton('Load Image Folder')
        load_image_folder_btn.clicked.connect(self.loadImageFolder)
        file_group.addWidget(load_image_folder_btn)
        
        load_annotations_btn = QPushButton('Load Annotations')
        load_annotations_btn.clicked.connect(self.loadAnnotations)
        file_group.addWidget(load_annotations_btn)
        
        set_output_btn = QPushButton('Set Output Directory')
        set_output_btn.clicked.connect(self.setOutputDirectory)
        file_group.addWidget(set_output_btn)
        right_layout.addLayout(file_group)
        
        # Frame selection section
        frame_group = QVBoxLayout()
        right_layout.addWidget(QLabel('Frame Selection:'))
        
        # Dropdown for labeled frames
        self.frame_dropdown = QComboBox()
        self.frame_dropdown.currentIndexChanged.connect(self.loadSelectedFrame)
        frame_group.addWidget(self.frame_dropdown)
        
        # Frame slider for video navigation
        frame_control = QHBoxLayout()
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.valueChanged.connect(self.updateFrame)
        frame_control.addWidget(self.frame_slider)
        
        self.frame_spinbox = QSpinBox()
        self.frame_spinbox.valueChanged.connect(self.updateFrame)
        frame_control.addWidget(self.frame_spinbox)
        frame_group.addLayout(frame_control)
        right_layout.addLayout(frame_group)

        # Person selection and management (multi-person support)
        person_group = QVBoxLayout()
        person_row = QHBoxLayout()
        person_row.addWidget(QLabel('Person:'))
        self.person_dropdown = QComboBox()
        self.person_dropdown.currentIndexChanged.connect(self.setCurrentPerson)
        person_row.addWidget(self.person_dropdown, stretch=1)
        add_person_btn = QPushButton('Add Person')
        add_person_btn.clicked.connect(self.addPerson)
        person_row.addWidget(add_person_btn)
        delete_person_btn = QPushButton('Delete Person')
        delete_person_btn.clicked.connect(self.deletePerson)
        person_row.addWidget(delete_person_btn)
        person_group.addLayout(person_row)

        # 当前选择的点的 v 状态选择栏（放置关键点时使用该可见性）
        v_row = QHBoxLayout()
        v_row.addWidget(QLabel('Point v:'))
        self.visibility_combo = QComboBox()
        self.visibility_combo.addItem("Visible (v=2)", 2)
        self.visibility_combo.addItem("Occluded (v=1)", 1)
        self.visibility_combo.currentIndexChanged.connect(self.onVisibilityChanged)
        v_row.addWidget(self.visibility_combo, stretch=1)
        person_group.addLayout(v_row)

        right_layout.addLayout(person_group)

        # Keypoint list and controls (显示中文名，UserRole 存英文 key 供内部使用)
        right_layout.addWidget(QLabel('Keypoints:'))
        self.placement_label = QLabel('Add Mode (W): OFF')
        self.placement_label.setToolTip(
            '按 W 键开启/关闭关键点放置模式；开启后选中未标注的点，'
            '左键点击图片即可放置。')
        right_layout.addWidget(self.placement_label)
        self.keypoint_list = QListWidget()
        for kp_name in self.pose_config.keypoint_names:
            item = QListWidgetItem(self.pose_config.display_name(kp_name))
            item.setData(Qt.UserRole, kp_name)
            self.keypoint_list.addItem(item)
        self.keypoint_list.setFixedHeight(
            self.keypoint_list.sizeHintForRow(0) * len(self.pose_config.keypoint_names) + 10)
        self.keypoint_list.currentRowChanged.connect(self.onKeypointSelected)
        # 不默认选中任何点：必须先手动在列表里选点，点击图片才会修改该点
        right_layout.addWidget(self.keypoint_list)
        
        # Control buttons
        buttons_layout = QVBoxLayout()
        reset_keypoint_btn = QPushButton('Reset Selected Keypoint')
        reset_keypoint_btn.clicked.connect(self.resetSelectedKeypoint)
        buttons_layout.addWidget(reset_keypoint_btn)

        save_btn = QPushButton('Save Current Frame')
        save_btn.clicked.connect(self.saveBtnClicked)  
        buttons_layout.addWidget(save_btn)
        
        reset_btn = QPushButton('Reset All Keypoints')
        reset_btn.clicked.connect(self.resetCurrent)
        buttons_layout.addWidget(reset_btn)
        
        # Add exit button
        exit_btn = QPushButton('Exit Program')
        exit_btn.clicked.connect(self.exitProgram)
        buttons_layout.addWidget(exit_btn)
        
        right_layout.addLayout(buttons_layout)
        
        # Metadata display
        self.info_label = QLabel()
        right_layout.addWidget(self.info_label)
        
        # Set up keypoint update callback
        self.viewer.scene().keypoint_updated = self.updateKeypointStatus
        self.viewer.scene().keypoint_selected = self.onKeypointSelectedByClick
        self.viewer.scene().placement_changed = self.onPlacementChanged

        # Message prompt region
        right_layout.addWidget(QLabel('Status Messages:'))
        self.message_prompt = QTextEdit()
        self.message_prompt.setReadOnly(True)  # Make it read-only
        self.message_prompt.setMaximumHeight(100)  # Limit height
        right_layout.addWidget(self.message_prompt)

        # Keyboard shortcuts: A/D to step frames (previous / next)
        QShortcut(Qt.Key_A, self, activated=lambda: self.stepFrameWithSave(-1),
                  context=Qt.WidgetWithChildrenShortcut)
        QShortcut(Qt.Key_D, self, activated=lambda: self.stepFrameWithSave(1),
                  context=Qt.WidgetWithChildrenShortcut)
        # Keyboard shortcuts: T/t/Delete 删除当前选中的关键点
        QShortcut(Qt.Key_T, self, activated=self.deleteSelectedKeypoint,
                  context=Qt.WidgetWithChildrenShortcut)
        QShortcut(Qt.Key_Delete, self, activated=self.deleteSelectedKeypoint,
                  context=Qt.WidgetWithChildrenShortcut)
        # Keyboard shortcut: W/w 开关关键点放置模式（开启后才能左键放置未标注点）
        QShortcut(Qt.Key_W, self, activated=self.togglePlacement,
                  context=Qt.WidgetWithChildrenShortcut)
        # Keyboard shortcut: S/s 保存当前帧；Tab 切换下一个 person（循环）
        QShortcut(Qt.Key_S, self, activated=self.saveBtnClicked,
                  context=Qt.WidgetWithChildrenShortcut)
        QShortcut(Qt.Key_Tab, self, activated=self.nextPerson,
                  context=Qt.WidgetWithChildrenShortcut)

    def saveBtnClicked(self):
        image_data = self.saveAnnotations(silent=True)
        if not image_data:
            return

        current_video = image_data.get("video_file", "Unknown")
        current_frame = image_data.get("frame_number", "Unknown")
        current_id = image_data.get("id", "Unknown")
        
        # Add status message
        message = f"Saved: Frame {current_frame} (ID: {current_id}) from {current_video}"
        self.addStatusMessage(message, "red")
    
    
    def mark_dirty(self):
        """标记当前帧有未保存的修改（A/D 切帧时会弹窗询问保存）。"""
        self.current_frame_dirty = True

    def addStatusMessage(self, message, color="black"):
        # Get current time
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Format message with timestamp
        formatted_message = f"[{current_time}] {message}"
        
        # Create HTML with specified color
        html = f"<span style='color:{color};'>{formatted_message}</span><br>"
        
        # Add message to the prompt
        self.message_prompt.moveCursor(QTextCursor.End)
        self.message_prompt.insertHtml(html)
        self.message_prompt.ensureCursorVisible()       
        
    def onKeypointSelected(self, row):
        """当前行切换时，把英文 keypoint 名传给场景；取消选中（row<0）时清空。"""
        if row < 0:
            self.viewer.scene().set_current_keypoint(None)
            self._sync_visibility_combo()
            return
        item = self.keypoint_list.item(row)
        if item is not None:
            self.viewer.scene().set_current_keypoint(item.data(Qt.UserRole))
            self._sync_visibility_combo()

    def onKeypointSelectedByClick(self, kp_name):
        """吸附选中/取消选中后，同步右侧列表高亮与 v 状态栏（None 表示取消选中）。"""
        if kp_name is None:
            self.keypoint_list.clearSelection()
            self._sync_visibility_combo()
            return
        for i in range(self.keypoint_list.count()):
            item = self.keypoint_list.item(i)
            if item.data(Qt.UserRole) == kp_name:
                self.keypoint_list.setCurrentRow(i)
                break
        self._sync_visibility_combo()

    def updateKeypointStatus(self, keypoint_name, is_labeled):
        self.mark_dirty()  # 关键点坐标/可见性/增删变化 → 记录为未保存修改
        for i in range(self.keypoint_list.count()):
            item = self.keypoint_list.item(i)
            if item.data(Qt.UserRole) != keypoint_name:
                continue
            # Get the keypoint's visibility value (v) from the scene
            visibility = 0  # default - not labeled
            if keypoint_name in self.viewer.scene().keypoints:
                _, _, v = self.viewer.scene().keypoints[keypoint_name]
                visibility = v

            if is_labeled:
                if visibility == 1:  # not visible but labeled
                    item.setBackground(QColor(255, 255, 0))  # Yellow for not visible
                else:  # visibility == 2, visible
                    item.setBackground(QColor(200, 255, 200))  # Light green for visible
            else:
                item.setBackground(QColor(255, 255, 255))  # White for unlabeled
            break

    def find_image(self, image_id):
        return next((img for img in self.annotations.get('images', [])
                     if img.get('id') == image_id), None)

    def find_annotations(self, image_id):
        """返回该 image_id 的所有 annotations（同一张图的多个人）。"""
        return [ann for ann in self.annotations.get('annotations', [])
                if ann.get('image_id') == image_id]

    def find_existing_frame(self, video_file, frame_number):
        for image in self.annotations.get("images", []):
            if (image.get("video_file") == video_file and
                    image.get("frame_number") == frame_number):
                return image, self.find_annotations(image.get("id"))
        return None, None

    def build_keypoints(self):
        keypoints = []
        for kp_name in self.pose_config.keypoint_names:
            if kp_name in self.viewer.scene().keypoints:
                x, y, v = self.viewer.scene().keypoints[kp_name]
                keypoints.extend([x, y, v])
            else:
                keypoints.extend([0, 0, 0])
        return keypoints

    def build_keypoints_for_person(self, person):
        """按 keypoint_names 顺序将一个人的 keypoints dict 转为 (x,y,v) 扁平列表。"""
        keypoints = []
        for kp_name in self.pose_config.keypoint_names:
            if kp_name in person:
                x, y, v = person[kp_name]
                keypoints.extend([x, y, v])
            else:
                keypoints.extend([0, 0, 0])
        return keypoints

    def calculate_bbox_for_person(self, person):
        """从一个人的 keypoints dict 计算 bbox（与 scene.calculate_bbox 同款 padding）。"""
        valid_x = [x for x, y, v in person.values() if v > 0]
        valid_y = [y for x, y, v in person.values() if v > 0]
        if not valid_x or not valid_y:
            return None
        padding = 30
        x_min = min(valid_x) - padding
        y_min = min(valid_y) - padding
        x_max = max(valid_x) + padding
        y_max = max(valid_y) + padding
        return [x_min, y_min, x_max - x_min, y_max - y_min]

    def next_annotation_id(self):
        return max([ann.get("id", 0) for ann in self.annotations.get("annotations", [])],
                   default=0) + 1

    def setFrameControls(self, frame_number):
        self.is_syncing_frame_controls = True
        self.frame_slider.blockSignals(True)
        self.frame_spinbox.blockSignals(True)
        self.frame_slider.setValue(frame_number)
        self.frame_spinbox.setValue(frame_number)
        self.frame_slider.blockSignals(False)
        self.frame_spinbox.blockSignals(False)
        self.is_syncing_frame_controls = False

    def setFrameRange(self, minimum, maximum):
        self.is_syncing_frame_controls = True
        self.frame_slider.blockSignals(True)
        self.frame_spinbox.blockSignals(True)
        self.frame_slider.setMinimum(minimum)
        self.frame_spinbox.setMinimum(minimum)
        self.frame_slider.setMaximum(maximum)
        self.frame_spinbox.setMaximum(maximum)
        self.frame_slider.blockSignals(False)
        self.frame_spinbox.blockSignals(False)
        self.is_syncing_frame_controls = False

    def setCurrentFrameState(self, image_data, annotations_list, frame_bgr):
        self.current_image_data = image_data
        self.current_annotations_list = annotations_list
        self.current_frame_bgr = frame_bgr
        self.current_frame_number = image_data.get("frame_number", 0)

    def active_source_matches(self, image_data):
        return self.active_source is not None and self.active_source.video_file == image_data.get("video_file")

    def activateSource(self, source):
        self.active_source = source
        min_frame, max_frame = source.frame_range()
        self.setFrameRange(min_frame, max_frame)
        self.updateFrame(min_frame)

    def normalizeAnnotations(self):
        self.annotations.setdefault('images', [])
        self.annotations.setdefault('annotations', [])
        self.annotations.setdefault('categories', [self.pose_config.get_category_config()])

    def writeAnnotationsFile(self):
        """将标注写入 annotations.json；若原文件已存在，先备份为 annotations.json.bak。

        每次保存时把上一版本备份到 .bak（覆盖旧备份），随后在原文件上写新内容，
        方便误改时从备份恢复。
        """
        annotations_path = os.path.join(self.output_dir, 'annotations.json')
        if os.path.exists(annotations_path):
            try:
                shutil.copy2(annotations_path,
                             os.path.join(self.output_dir, 'annotations.json.bak'))
            except OSError:
                pass  # 备份失败不阻断保存
        with open(annotations_path, 'w') as f:
            json.dump(self.annotations, f, indent=2)

    def selectFrameDropdownByImageId(self, image_id):
        for i in range(self.frame_dropdown.count()):
            if self.frame_dropdown.itemData(i) == image_id:
                self.frame_dropdown.blockSignals(True)
                self.frame_dropdown.setCurrentIndex(i)
                self.frame_dropdown.blockSignals(False)
                return i
        return -1

    def showFrameState(self, image_data, annotations_list, frame_bgr):
        self.setCurrentFrameState(image_data, annotations_list, frame_bgr)
        self.displayFrame(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB), annotations_list)
        self.updateMetadataDisplay(image_data, annotations_list)

    # NEW: Enhanced load annotations method
    def loadAnnotations(self):
        annotations_file, _ = QFileDialog.getOpenFileName(
            self, "Select Annotations File", "", "JSON Files (*.json)")
        
        if not annotations_file:
            return
            
        try:
            with open(annotations_file, 'r') as f:
                self.annotations = json.load(f)
            self.normalizeAnnotations()
            
            # Set output directory to annotations location
            self.output_dir = os.path.dirname(annotations_file)

            # 将 COCO JSON 与图片文件夹关联后激活
            self.associateImageFolderFromAnnotations()

            QMessageBox.information(self, "Loaded Annotations",
                                  f"Successfully loaded {len(self.annotations.get('images', []))} "
                                  f"images and {len(self.annotations.get('annotations', []))} annotations.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load annotations: {str(e)}")

    def associateImageFolderFromAnnotations(self):
        """将当前 annotations 的 images 与图片文件夹关联（非视频流程）。

        若尚未加载图片文件夹则弹出选择框；随后为缺失 video_file 的 image 补齐
        文件夹名，并按 images 列表重建帧映射后激活图片源。
        """
        folder_path = self.image_folder_processor.folder_path
        if not folder_path:
            folder_path = QFileDialog.getExistingDirectory(
                self, "Select the Image Folder for this Annotation File")
            if not folder_path:
                self.updateFrameDropdown()
                return
            if not self.image_folder_processor.load_folder(folder_path):
                QMessageBox.warning(self, "Error",
                    "No readable image files found in the selected folder.")
                self.updateFrameDropdown()
                return

        folder_name = os.path.basename(os.path.normpath(folder_path))
        for image in self.annotations.get('images', []):
            if not image.get('video_file'):
                image['video_file'] = folder_name

        if not self.image_folder_processor.rebuild_from_annotations(
                self.annotations.get('images', []), folder_path):
            QMessageBox.warning(self, "Warning",
                "None of the annotation image files were found in the selected folder.")
            self.updateFrameDropdown()
            return

        self.activateSource(self.image_folder_processor)
        self.updateFrameDropdown()

    def updateFrameDropdown(self):
        self.frame_dropdown.blockSignals(True)
        self.frame_dropdown.clear()
        for image in self.annotations.get('images', []):
            if 'id' not in image or 'frame_number' not in image:
                continue
            self.frame_dropdown.addItem(
                f"Frame {image['frame_number']} (ID: {image['id']})",
                userData=image['id'])
        self.frame_dropdown.blockSignals(False)

    def rebuild_person_dropdown(self, select_index=None):
        """重建 Person 下拉框（blockSignals 防止触发 setCurrentPerson）。"""
        scene = self.viewer.scene()
        num_people = len(scene.people)
        self.person_dropdown.blockSignals(True)
        self.person_dropdown.clear()
        for i in range(num_people):
            self.person_dropdown.addItem(f"Person {i + 1}")
        index = scene.current_person_index if select_index is None else select_index
        if num_people > 0:
            index = max(0, min(index, self.person_dropdown.count() - 1))
            self.person_dropdown.setCurrentIndex(index)
        self.person_dropdown.blockSignals(False)

    def onVisibilityChanged(self, index):
        """v 状态栏切换时：更新放置可见性，并立即应用到当前选中的点。"""
        scene = self.viewer.scene()
        v = self.visibility_combo.itemData(index) or 2
        scene.visibility_mode = v
        kp = scene.current_keypoint
        if kp is not None and kp in scene.keypoints:
            x, y, _ = scene.keypoints[kp]
            scene.keypoints[kp] = (x, y, v)
            scene.update_keypoint_visuals()
            self.updateKeypointListState()
            self.mark_dirty()  # v 状态变化属于修改

    def _sync_visibility_combo(self):
        """把 v 状态栏同步为当前选中点的 v；未选点显示空（index -1）。

        选中已标注点 → 显示该点 v；选中未标注点 → 显示当前放置 v。
        """
        scene = self.viewer.scene()
        kp = scene.current_keypoint
        v = None
        if kp is not None:
            if kp in scene.keypoints:
                _, _, v = scene.keypoints[kp]
            else:
                v = scene.visibility_mode
        idx = -1 if v is None else self.visibility_combo.findData(v)
        self.visibility_combo.blockSignals(True)
        self.visibility_combo.setCurrentIndex(idx)
        self.visibility_combo.blockSignals(False)
        if v is not None:
            scene.visibility_mode = v

    def setCurrentPerson(self, index):
        """切换当前编辑的人。"""
        scene = self.viewer.scene()
        if index < 0 or index >= len(scene.people):
            return
        scene.current_person_index = index
        scene.set_current_keypoint(None)
        self.last_deleted_keypoint = None  # 切人后重置最近删除记录
        scene.update_keypoint_visuals()
        self.updateKeypointListState()
        self._sync_visibility_combo()
        self.updateMetadataDisplay(self.current_image_data or {},
                                   self.current_annotations_list or [])

    def nextPerson(self):
        """Tab 键：切换到下一个 person（循环）；切换前自动保存当前人的修改。"""
        scene = self.viewer.scene()
        n = len(scene.people)
        if n <= 1:
            return
        current_index = scene.current_person_index
        self.saveAnnotations(silent=True)  # 自动保存当前人（不弹框）
        # 新增标注保存时会重建场景，重新获取最新的 people 数量
        scene = self.viewer.scene()
        n = len(scene.people)
        if n <= 1:
            return
        next_index = (current_index + 1) % n
        self.person_dropdown.blockSignals(True)
        self.person_dropdown.setCurrentIndex(next_index)
        self.person_dropdown.blockSignals(False)
        self.setCurrentPerson(next_index)

    def addPerson(self):
        """新增一个人并切换到它。"""
        scene = self.viewer.scene()
        scene.add_person()
        self.mark_dirty()  # 新增 person 属于修改
        scene.set_current_keypoint(None)
        self.rebuild_person_dropdown()
        self.updateKeypointListState()
        self._sync_visibility_combo()
        self.updateMetadataDisplay(self.current_image_data or {},
                                   self.current_annotations_list or [])

    def deletePerson(self):
        """删除当前编辑的人（关键点与框一并删除），弹窗确认后执行。

        删除只作用于场景（工作状态）并标记 dirty；真正的数据删除在
        “保存”时同步到 annotations 并写回文件。因此若随后切换帧时
        选择“不保存”，本帧所有修改（含删除的人）都会被丢弃、切回后恢复。
        """
        scene = self.viewer.scene()
        if not scene.people:
            return  # 已无 person 可删
        index = scene.current_person_index
        reply = QMessageBox.question(self, 'Delete Person',
                                     f'确定删除当前 Person {index + 1}（关键点与框）？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        # 从场景移除该人（关键点、骨架、框全部消失）；数据同步延迟到保存时
        scene.remove_person(index)
        self.mark_dirty()  # 删除 person 属于修改

        scene.set_current_keypoint(None)
        self.last_deleted_keypoint = None
        self.rebuild_person_dropdown()
        self.updateKeypointListState()
        self._sync_visibility_combo()
        self.updateMetadataDisplay(self.current_image_data or {},
                                   self.current_annotations_list or [])


    def displayFrame(self, frame, annotations_list=None):
        self.last_deleted_keypoint = None  # 切帧后不再恢复上一帧被删除的点
        self.current_frame_dirty = False  # 加载新帧，重置修改记录
        height, width, channel = frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)

        # Create new scene
        new_scene = KeypointScene(self.pose_config)
        self.viewer.setScene(new_scene)

        # Add image to scene
        pixmap = QPixmap.fromImage(q_image)
        new_scene.addPixmap(pixmap)
        self.viewer.setSceneRect(QRectF(pixmap.rect()))
        self.viewer.fitInView(self.viewer.sceneRect(), Qt.KeepAspectRatio)

        # Set up keypoint update callback
        new_scene.keypoint_updated = self.updateKeypointStatus
        new_scene.keypoint_selected = self.onKeypointSelectedByClick
        new_scene.placement_changed = self.onPlacementChanged

        # Load keypoints for all people (one person per annotation)
        people = []
        for ann in (annotations_list or []):
            person = {}
            keypoints = ann.get('keypoints', [])
            for i, kp_name in enumerate(self.pose_config.keypoint_names):
                if i * 3 + 2 >= len(keypoints):
                    break
                x = keypoints[i * 3]
                y = keypoints[i * 3 + 1]
                v = keypoints[i * 3 + 2]
                if v > 0:  # If keypoint exists
                    person[kp_name] = (x, y, v)
            people.append(person)
        new_scene.set_people(people)
        new_scene.visibility_mode = self.visibility_combo.itemData(
            self.visibility_combo.currentIndex()) or 2
        new_scene.update_keypoint_visuals()
        self.updateKeypointListState()

        # 切换图片后自动空选关键点，回到空选默认状态（不保留上一帧的选中）
        new_scene.set_current_keypoint(None)
        self.keypoint_list.setCurrentItem(None)
        self._sync_visibility_combo()
        self.onPlacementChanged(new_scene.placement_enabled)  # 新场景放置模式默认关闭，同步标签

        self.rebuild_person_dropdown()

    def updateMetadataDisplay(self, image_data, annotations_list):
        # 统计改为从 scene 实时读取，annotations_list 保留以匹配调用方签名
        _ = annotations_list
        scene = self.viewer.scene()
        num_people = len(scene.people)
        person_idx = (min(scene.current_person_index, num_people - 1)
                      if num_people > 0 else -1)

        # Determine the source
        if image_data.get('id') is None:
            source = "Current source only (not annotated)"
        else:
            if self.active_source_matches(image_data):
                source = "Annotation and Current Source"
            else:
                source = "Annotation only"

        # 当前人的实时统计（基于 scene，反映编辑状态）
        kp_values = list(scene.keypoints.values()) if scene.keypoints else []
        visible_points = len([v for _, _, v in kp_values if v == 2])
        estimated_points = len([v for _, _, v in kp_values if v == 1])

        bbox = scene.calculate_bbox() or [0, 0, 0, 0]

        info_text = (
            f"Source: {source}\n"
            f"Video: {image_data.get('video_file', 'N/A')}\n"
            f"Frame: {image_data.get('frame_number', 'N/A')}\n"
            f"Image ID: {image_data.get('id', 'N/A')}\n"
            f"Person: {person_idx + 1}/{num_people}\n"
            f"BBox: x={bbox[0]:.1f}, y={bbox[1]:.1f}, "
            f"w={bbox[2]:.1f}, h={bbox[3]:.1f}\n"
            f"Visible Keypoints (Left-click): {visible_points}\n"
            f"Estimated Keypoints (Right-click): {estimated_points}\n"
            f"Unlabeled Keypoints: {len(self.pose_config.keypoint_names) - visible_points - estimated_points}"
        )
        self.info_label.setText(info_text)

    def updateKeypointListState(self):
        """按当前人的标注情况刷新 keypoint 列表背景色。"""
        scene = self.viewer.scene()
        for i in range(self.keypoint_list.count()):
            item = self.keypoint_list.item(i)
            kp_name = item.data(Qt.UserRole)
            if kp_name in scene.keypoints:
                _, _, v = scene.keypoints[kp_name]
                if v == 1:
                    item.setBackground(QColor(255, 255, 0))  # Yellow: labeled but occluded
                else:
                    item.setBackground(QColor(200, 255, 200))  # Light green: visible
            else:
                item.setBackground(QColor(255, 255, 255))  # White: unlabeled
        
    def loadImageFolder(self):
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Image Folder"
        )
        if not folder_path:
            return

        if not self.image_folder_processor.load_folder(folder_path):
            QMessageBox.warning(
                self,
                "Error",
                "No readable image files found in the selected folder.\n"
                "Supported formats: *.jpg *.jpeg *.png (numeric or named files)."
            )
            return

        self.activateSource(self.image_folder_processor)

    def loadSelectedFrame(self, index):
        if index < 0:
            return
            
        image_id = self.frame_dropdown.currentData()
        image_data = self.find_image(image_id)
        if image_data is None:
            QMessageBox.warning(self, "Error", f"Annotation image ID not found: {image_id}")
            return
        
        # Load all annotations for this image (may be empty for unlabeled images
        # in standard COCO data; the image is still shown without keypoints)
        annotations_list = self.find_annotations(image_id)

        # Sync active source frame if it matches the annotation source.
        if self.active_source_matches(image_data):
            self.current_frame_number = image_data.get('frame_number', 0)
            self.setFrameControls(self.current_frame_number)
            frame = self.active_source.get_frame(self.current_frame_number)
        else:
            # Load from saved frame
            file_name = image_data.get('file_name')
            if not file_name:
                QMessageBox.warning(self, "Error", f"Image file name missing for image ID: {image_id}")
                return
            image_path = os.path.join(self.output_dir, "frames", file_name)
            if not os.path.exists(image_path):
                QMessageBox.warning(self, "Error", f"Image file not found: {image_path}")
                return
            frame = cv2.imread(image_path)
        
        if frame is None:
            QMessageBox.warning(self, "Error", "Failed to load frame image.")
            return

        self.showFrameState(image_data, annotations_list, frame)

    def updateFrame(self, frame_number):
        if self.is_syncing_frame_controls:
            return
        if self.active_source is None:
            return

        frame = self.active_source.get_frame(frame_number)
        if frame is None:
            if self.active_source is self.image_folder_processor:
                self.addStatusMessage(f"Frame {frame_number} is missing from the selected image folder.", "red")
            return

        self.current_frame_number = frame_number
        self.setFrameControls(frame_number)

        source_name = self.active_source.video_file
        existing_image, existing_annotations = self.find_existing_frame(source_name, frame_number)
        if existing_image:
            self.showFrameState(existing_image, existing_annotations, frame)
        else:
            temp_image_data = {
                "video_file": source_name or 'N/A',
                "frame_number": frame_number,
                "id": None
            }
            self.showFrameState(temp_image_data, [], frame)

    def stepFrame(self, delta):
        """切换前一张 / 后一张（按相邻帧号跳转，帧号可能不连续）。"""
        if self.active_source is None:
            return
        frames = self.image_folder_processor.frame_numbers
        if not frames:
            return
        try:
            idx = frames.index(self.current_frame_number)
        except ValueError:
            idx = 0
        idx = max(0, min(len(frames) - 1, idx + delta))
        self.updateFrame(frames[idx])

    def stepFrameWithSave(self, delta):
        """A/D 快捷键入口：当前帧有未保存修改时弹窗询问是否保存，否则直接切换。"""
        if self.current_frame_dirty:
            reply = QMessageBox.question(
                self, "Save Changes",
                "切换帧前是否保存当前帧的修改？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.saveAnnotations(silent=True)
        self.stepFrame(delta)

    def saveAnnotations(self, silent=False):
        """保存当前帧所有标注；silent=True 时静默（不弹任何对话框，失败返回 False）。

        保存以场景 scene.people 为准，将本帧 annotations 与之一一对齐：
        修改的点写回对应 annotation，新增的人追加 annotation，被删除的人
        丢弃其 annotation。因此“删除 person”只有在保存时才会真正落地；
        若切换帧时选择不保存，本帧修改（含删除的人）都会被丢弃、切回后恢复。
        """
        if not self.output_dir:
            if not silent:
                QMessageBox.warning(self, "Warning", "Please set output directory first!")
            return False

        if self.current_image_data is None or self.current_frame_bgr is None:
            if not silent:
                QMessageBox.warning(self, "Warning", "Please load an annotation frame first!")
            return False

        current_video = self.current_image_data.get("video_file")
        current_frame = self.current_image_data.get("frame_number")
        if current_video in (None, "N/A") or current_frame is None:
            if not silent:
                QMessageBox.warning(self, "Warning", "Current frame does not have video metadata to save.")
            return False

        scene = self.viewer.scene()
        existing_image, existing_annotations = self.find_existing_frame(current_video, current_frame)

        # 已删除全部 person：清除该帧全部 annotation（保留 image 记录），使删除真正落地
        if not scene.people:
            if existing_image and existing_annotations:
                image_id = existing_image["id"]
                self.annotations['annotations'] = [a for a in self.annotations.get('annotations', [])
                                                   if a.get('image_id') != image_id]
                existing_image["date_captured"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.writeAnnotationsFile()
                self.setCurrentFrameState(existing_image, [], self.current_frame_bgr)
                self.current_frame_dirty = False  # 保存成功，清空修改记录
                if not silent:
                    QMessageBox.information(self, "Success",
                                          f"Frame {current_frame} 已清空全部标注！")
                return existing_image
            return None  # 空帧无可保存内容

        current_person_index = scene.current_person_index

        # 确认 / 创建 image 记录
        if existing_image:
            image_id = existing_image["id"]
            image_info = existing_image
        else:
            # For new annotation, get next available ID
            if self.active_source is None:
                if not silent:
                    QMessageBox.warning(self, "Warning", "Please load an image folder before saving a new annotation.")
                return False

            frames_dir = os.path.join(self.output_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)

            image_id = max([img.get("id", 0) for img in self.annotations.get("images", [])],
                           default=0) + 1

            # Save current frame
            filename = self.active_source.save_frame(current_frame, frames_dir, image_id)
            if not filename:
                if not silent:
                    QMessageBox.warning(self, "Error", "Failed to save current frame image.")
                return False

            image_info = {
                "id": image_id,
                "file_name": filename,
                "video_file": current_video,
                "frame_number": current_frame,
                "width": self.active_source.frame_width,
                "height": self.active_source.frame_height,
                "fps": self.active_source.fps,
                "date_captured": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.annotations["images"].append(image_info)

        # 整体对齐：用 scene.people 重建该 image 的 annotations。
        # 先移除该 image 的旧 annotations，再按顺序复用旧 ann 对象（保留 id 等额外
        # 字段）逐一覆盖；people 比旧 ann 多则新建，少（删除 person）则自然丢弃。
        self.annotations['annotations'] = [a for a in self.annotations.get('annotations', [])
                                           if a.get('image_id') != image_id]
        new_anns = []
        next_ann_id = self.next_annotation_id()  # 新增多人时起始 id，循环内递增避免重复
        for i, person in enumerate(scene.people):
            if i < len(existing_annotations):
                ann = existing_annotations[i]
            else:
                ann = {
                    "id": next_ann_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "iscrowd": 0,
                    "segmentation": [],
                    "score": 1.0
                }
                next_ann_id += 1
            keypoints = self.build_keypoints_for_person(person)
            bbox = self.calculate_bbox_for_person(person) or [0, 0, 0, 0]
            ann.update({
                "keypoints": keypoints,
                "num_keypoints": len(person),
                "bbox": bbox,
                "area": bbox[2] * bbox[3],
            })
            new_anns.append(ann)
        self.annotations['annotations'].extend(new_anns)

        image_info["date_captured"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.writeAnnotationsFile()

        self.setCurrentFrameState(image_info, new_anns, self.current_frame_bgr)
        self.updateFrameDropdown()
        self.selectFrameDropdownByImageId(image_id)
        self.updateMetadataDisplay(image_info, new_anns)

        if not silent:
            QMessageBox.information(self, "Success",
                                  f"Frame {current_frame} Person {current_person_index + 1} saved successfully!")

        self.current_frame_dirty = False  # 保存成功，清空修改记录
        return image_info
            

    def togglePlacement(self):
        """W 键：开关关键点放置模式（开启后才能用左键放置未标注关键点）。"""
        scene = self.viewer.scene()
        on = not scene.placement_enabled
        scene.placement_enabled = on
        self.onPlacementChanged(on)

    def onPlacementChanged(self, on):
        """放置模式开关变化：刷新右侧状态标签（放置一个关键点后自动关闭也会调用）。"""
        self.placement_label.setText('Add Mode (W): ' + ('ON' if on else 'OFF'))
        self.placement_label.setStyleSheet(
            'color: green; font-weight: bold;' if on else '')

    def resetSelectedKeypoint(self):
        """恢复当前选中的点；无选中时恢复最近被删除的点（删除后已取消选中）。"""
        scene = self.viewer.scene()
        kp_name = None
        current_item = self.keypoint_list.currentItem()
        if current_item:
            kp_name = current_item.data(Qt.UserRole)
        if kp_name is None:
            kp_name = self.last_deleted_keypoint
        if not kp_name:
            return
        scene.reset_keypoint_to_original(kp_name)
        self.last_deleted_keypoint = None
        self.updateKeypointListState()

    def deleteSelectedKeypoint(self):
        """删除当前选中的关键点（T/t/Delete 键）。

        删除后自动取消选中，点击图片不会再生成该点；
        按 Reset Selected Keypoint 可恢复——优先恢复当前选中点，
        无选中时恢复最近被删除的点。
        """
        scene = self.viewer.scene()
        kp_name = scene.current_keypoint
        if not kp_name:
            return
        if kp_name not in scene.keypoints:
            return  # 点不存在（未标注或已被删除）
        self.last_deleted_keypoint = kp_name
        scene.reset_keypoint(kp_name)
        scene.set_current_keypoint(None)
        self.onKeypointSelectedByClick(None)

    def resetCurrent(self):
        """将当前人的所有点恢复为加载时的原始坐标（原始没有的点会被删除）。"""
        scene = self.viewer.scene()
        if scene.original_people:
            idx = min(scene.current_person_index, len(scene.original_people) - 1)
            scene.keypoints.clear()
            scene.keypoints.update(
                {k: tuple(v) for k, v in scene.original_people[idx].items()})
        else:
            scene.keypoints.clear()
        scene.update_keypoint_visuals()
        self.updateKeypointListState()
            
    def closeEvent(self, event):
        super().closeEvent(event)

if __name__ == '__main__':
    prefer_pyqt_qt_plugins()
    app = QApplication(sys.argv)
    pose_config=PoseConfig()
    tool = IntegratedPoseTool(pose_config)
    tool.show()
    sys.exit(app.exec_())

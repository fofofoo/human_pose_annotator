from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor

class PoseConfig:
    def __init__(self):
        # Keypoint definitions
        self.keypoint_names = [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle"
        ]
        
        # Skeleton connections (COCO format)
        self.skeleton = [
            [16,14], [14,12], [17,15], [15,13], [12,13], [6,12], [7,13],
            [6,7], [6,8], [7,9], [8,10], [9,11], [2,3], [1,2], [1,3],
            [2,4], [3,5], [4,6], [5,7]
        ]

        # 界面显示用的中文关键点名称（内部 key 仍用英文，COCO JSON 兼容）
        self.keypoint_display_names = {
            "nose": "鼻子",
            "left_eye": "左眼",
            "right_eye": "右眼",
            "left_ear": "左耳",
            "right_ear": "右耳",
            "left_shoulder": "左肩",
            "right_shoulder": "右肩",
            "left_elbow": "左肘",
            "right_elbow": "右肘",
            "left_wrist": "左腕",
            "right_wrist": "右腕",
            "left_hip": "左髋",
            "right_hip": "右髋",
            "left_knee": "左膝",
            "right_knee": "右膝",
            "left_ankle": "左踝",
            "right_ankle": "右踝",
        }
        
        # Color definitions for keypoints
        self.keypoint_colors = {
            "nose": QColor(255, 0, 0),      # Red
            "left_eye": QColor(255, 85, 0),  
            "right_eye": QColor(255, 170, 0),
            "left_ear": QColor(255, 255, 0),  
            "right_ear": QColor(170, 255, 0),
            "left_shoulder": QColor(85, 255, 0),
            "right_shoulder": QColor(0, 255, 0),
            "left_elbow": QColor(0, 255, 85),   
            "right_elbow": QColor(0, 255, 170),
            "left_wrist": QColor(0, 255, 255),  
            "right_wrist": QColor(0, 170, 255),
            "left_hip": QColor(0, 85, 255),    
            "right_hip": QColor(0, 0, 255),    
            "left_knee": QColor(85, 0, 255),   
            "right_knee": QColor(170, 0, 255),
            "left_ankle": QColor(255, 0, 255),
            "right_ankle": QColor(255, 0, 170)
        }
        
        self.skeleton_color = QColor(0, 128, 255)  # Light blue

    def display_name(self, kp_name):
        """返回界面显示名（中文），无映射时回退英文 key。"""
        return self.keypoint_display_names.get(kp_name, kp_name)

    def get_category_config(self):
        """Return the category configuration for COCO format"""
        return {
            "id": 1,
            "name": "person",
            "supercategory": "person",
            "keypoints": self.keypoint_names,
            "skeleton": self.skeleton
        }
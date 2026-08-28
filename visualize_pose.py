import json
import cv2
import os
import numpy as np

# ================= 配置区域 =================
# 数据集根目录 (请根据您的实际路径修改)
DATASET_ROOT = r"D:\AI\Dataset\ir_human_pose\zlzk0804\modified_data"
ANN_FILE =  os.path.join(DATASET_ROOT, "out_annotations_modified.json")
IMG_DIR  = os.path.join(DATASET_ROOT, "images")

# ============================================

def load_coco_json(ann_file):
    """加载 COCO JSON 文件"""
    with open(ann_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def get_colors(num_colors):
    """生成均匀分布的颜色池，用于区分不同的人"""
    colors = []
    for i in range(num_colors):
        # 使用 HSV 转 BGR 生成鲜艳的颜色
        hue = int((i * 180) / num_colors)
        hsv = np.uint8([[[hue, 255, 255]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0]
        colors.append(tuple(int(c) for c in bgr))
    return colors

def visualize_coco_pose(data, img_dir):
    
    # 1. 解析 categories (假设只有 person 类别，取第一个)
    categories = data.get('categories', [])
    if not categories:
        print("Error: No categories found in JSON.")
        return
    
    cat = categories[0]
    keypoints_names = cat.get('keypoints', [])
    skeleton = cat.get('skeleton', []) 
    
    # ⚠️ 核心细节：COCO 的 skeleton 索引是 1-based (从1开始)，需要转为 0-based (从0开始) 供 Python 使用
    skeleton_0based = [[idx - 1 for idx in pair] for pair in skeleton]
    
    # 2. 构建 images 字典，方便通过 image_id 快速查找
    images_dict = {img['id']: img for img in data.get('images', [])}
    
    # 3. 将 annotations 按 image_id 分组
    anns_by_image = {}
    for ann in data.get('annotations', []):
        img_id = ann['image_id']
        if img_id not in anns_by_image:
            anns_by_image[img_id] = []
        anns_by_image[img_id].append(ann)
        
    # 生成颜色池
    colors = get_colors(20) 
    processed_count = 0
    
    print(f"开始可视化，图片源: {img_dir}")
    
    # 4. 遍历图片进行绘制
    for img_id, img_info in images_dict.items():
        
        file_name = img_info['file_name']
        img_path = os.path.join(img_dir, file_name)
        
        if not os.path.exists(img_path):
            print(f"Warning: Image not found: {img_path}")
            continue

        img = cv2.imread(img_path)
        if img is None:
            print(f"Warning: Failed to read image: {img_path}")
            continue
            
        # 获取该图片的所有人体标注
        anns = anns_by_image.get(img_id, [])
        
        # 遍历每个人 (annotation)
        for i, ann in enumerate(anns):
            kpts = ann['keypoints'] # 格式: [x1, y1, v1, x2, y2, v2, ...]
            color = colors[i % len(colors)]
            
            # 解析关键点坐标和可见性 (v)
            valid_points = {}
            for j in range(len(keypoints_names)):
                x = kpts[3*j]
                y = kpts[3*j + 1]
                v = kpts[3*j + 2]
                # v=0 表示未标注/不存在，v>0 才进行绘制
                if v > 0:
                    valid_points[j] = (int(x), int(y), v)
                    
            # A. 绘制骨架连线 (Skeleton)
            for pair in skeleton_0based:
                idx1, idx2 = pair[0], pair[1]
                # 只有当两个端点都可见/被标注时，才画线
                if idx1 in valid_points and idx2 in valid_points:
                    pt1 = valid_points[idx1][:2]
                    pt2 = valid_points[idx2][:2]
                    cv2.line(img, pt1, pt2, color, 2) # 线宽为 2
                    
            # B. 绘制关键点圆点 (Keypoints)
            for j, (x, y, v) in valid_points.items():
                # 颜色区分：v=2 (可见) 用绿色，v=1 (被遮挡) 用橙色
                pt_color = (0, 255, 0) if v == 2 else (0, 165, 255) 
                cv2.circle(img, (x, y), 5, pt_color, -1)       # 画实心圆
                cv2.circle(img, (x, y), 5, (0, 0, 0), 1)       # 加个黑边，在热成像图上更清晰
                
        processed_count += 1
        cv2.imshow("img",img)
        cv2.waitKey(1)
        
    print("可视化全部完成！")

if __name__ == "__main__":
    # 1. 加载 JSON
    print(f"Loading annotations from {ANN_FILE}...")
    coco_data = load_coco_json(ANN_FILE)
    
    # 2. 执行可视化
    visualize_coco_pose(coco_data, IMG_DIR)
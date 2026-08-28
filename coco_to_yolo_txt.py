import json
import os
from pathlib import Path


# ============================================

def coco_to_yolo_txt(dataset_root, json_path, img_dir):

    # 3. 创建 labels 输出目录
    labels_dir = Path(dataset_root)  / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📂 正在读取: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # 4. 构建 image_id 到图像信息(宽高)的映射
    img_info_dict = {img['id']: img for img in data.get('images', [])}
    
    # 5. 按 image_id 分组 annotations
    anns_by_image = {}
    for ann in data.get('annotations', []):
        img_id = ann['image_id']
        if img_id not in anns_by_image:
            anns_by_image[img_id] = []
        anns_by_image[img_id].append(ann)
        
    converted_count = 0
    
    # 6. 遍历并生成 YOLO TXT 文件
    print(f"🔄 开始生成 labels 下的 TXT 文件...")
    for img_id, anns in anns_by_image.items():
        img_info = img_info_dict.get(img_id)
        if not img_info:
            continue
            
        file_name = img_info['file_name']
        img_width = img_info['width']
        img_height = img_info['height']
        
        if img_width == 0 or img_height == 0:
            continue
            
        # 生成对应的 txt 文件名 (例如: 000001.jpg -> 000001.txt)
        txt_file = labels_dir / (Path(file_name).stem + ".txt")
        
        with open(txt_file, 'w', encoding='utf-8') as f:
            for ann in anns:
                # --- A. 解析并归一化 Bounding Box ---
                # COCO bbox 格式: [x_min, y_min, width, height]
                x_min, y_min, w, h = ann['bbox']
                
                x_center = (x_min + w / 2.0) / img_width
                y_center = (y_min + h / 2.0) / img_height
                norm_w = w / img_width
                norm_h = h / img_height
                
                # 防止因标注越界导致归一化值超出 [0, 1]
                x_center = max(0.0, min(1.0, x_center))
                y_center = max(0.0, min(1.0, y_center))
                norm_w = max(0.0, min(1.0, norm_w))
                norm_h = max(0.0, min(1.0, norm_h))
                
                # --- B. 解析并归一化 Keypoints ---
                kpts = ann.get('keypoints', [])
                kpt_str = []
                
                for i in range(0, len(kpts), 3):
                    kx = kpts[i] / img_width
                    ky = kpts[i+1] / img_height
                    v = int(kpts[i+2])
                    
                    if v == 0:
                        # v=0 表示未标注/不存在，坐标设为 0.0
                        kpt_str.extend([0.0, 0.0, 0])
                    else:
                        # v>0 表示存在，归一化并限制在 [0, 1] 内
                        kx = max(0.0, min(1.0, kx))
                        ky = max(0.0, min(1.0, ky))
                        kpt_str.extend([round(kx, 6), round(ky, 6), v])
                        
                # --- C. 组装 YOLO-Pose 标准行 ---
                # 格式: <class_id> <x_center> <y_center> <width> <height> <px1> <py1> <pv1> ... <px17> <py17> <pv17>
                # class_id 对于 person 固定为 0
                line = [0, round(x_center, 6), round(y_center, 6), round(norm_w, 6), round(norm_h, 6)] + kpt_str
                
                # 写入文件，用空格分隔
                f.write(" ".join(map(str, line)) + "\n")
                
        converted_count += 1
        
    print(f"✅ 成功！共为 {converted_count} 张图片生成了 YOLO TXT 标签。")
    print(f"📁 保存路径: {labels_dir}")

if __name__ == "__main__":
    
    # 数据集根目录 (请根据您的实际路径修改)
    DATASET_ROOT = r"D:\AI\Dataset\ir_human_pose\zlzk0804\modified_data"
    json_path = os.path.join(DATASET_ROOT, "out_annotations_modified.json")
    img_dir = os.path.join(DATASET_ROOT, "images")

    coco_to_yolo_txt(DATASET_ROOT,json_path,img_dir)
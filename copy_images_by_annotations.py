# -*- coding: utf-8 -*-
"""根据标注文件中的图片清单，把图片从源文件夹复制到目标文件夹。

用法：python copy_images_by_annotations.py

- 读取 ANNOT_JSON 中所有 image 的 file_name；
- 从 SRC_IMG_DIR 查找并复制到 DST_IMG_DIR（自动创建目录）；
- 源目录找不到原文件名时，按同名做 .jpg/.jpeg/.png 扩展名兜底；
- 目标文件始终以 json 中的 file_name 命名（与标注引用保持一致）；
- 只读源、写目标，不修改任何源数据。
"""
import json
import os
import shutil

ANNOT_JSON = r"D:\AI\Dataset\ir_human_pose\zlzk0804\modified_data\out_annotations_modified.json"
SRC_IMG_DIR = r"D:\AI\Dataset\ir_human_pose\zlzk0804\flited_data\images"
DST_IMG_DIR = r"D:\AI\Dataset\ir_human_pose\zlzk0804\modified_data\images"

VALID_EXTS = (".jpg", ".jpeg", ".png")


def resolve_source(file_name, src_dir):
    """返回源文件实际路径；找不到返回 (None, None)。"""
    direct = os.path.join(src_dir, file_name)
    if os.path.isfile(direct):
        return direct, None
    # 扩展名兜底：按 stem 匹配源目录中任意支持扩展名的同名文件
    stem = os.path.splitext(file_name)[0]
    for ext in VALID_EXTS:
        candidate = os.path.join(src_dir, stem + ext)
        if os.path.isfile(candidate):
            return candidate, ext
    return None, None


def main():
    with open(ANNOT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(DST_IMG_DIR, exist_ok=True)

    file_names = [img.get("file_name")
                  for img in data.get("images", []) if img.get("file_name")]
    copied = 0
    fallback = 0
    missing = []
    for name in file_names:
        src, used_ext = resolve_source(name, SRC_IMG_DIR)
        if src is None:
            missing.append(name)
            continue
        shutil.copy2(src, os.path.join(DST_IMG_DIR, name))
        copied += 1
        if used_ext is not None:
            fallback += 1

    print(f"标注文件中的图片：{len(file_names)} 张")
    print(f"已复制：{copied} 张（其中 {fallback} 张为扩展名兜底匹配）→ {DST_IMG_DIR}")
    if missing:
        print(f"源目录中缺失 {len(missing)} 张：")
        for m in missing:
            print("  ", m)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""从标注文件中筛选出已修改（modified=1）的图片及其对应标注，生成精简版标注文件。

用法：python filter_modified_annotations.py

输出文件结构与原文件完全一致（顶层键顺序、字段均不变），
仅 images 数组与 annotations 数组减少了（未修改的图片与其标注被剔除）。
"""
import json

SRC_JSON = r"D:\AI\Dataset\ir_human_pose\zlzk0804\flited_data\label\out_annotations.json"
DST_JSON = r"D:\AI\Dataset\ir_human_pose\zlzk0804\flited_data\label\out_annotations_modified.json"


def main():
    with open(SRC_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_images = data.get("images", [])
    all_anns = data.get("annotations", [])

    # 只保留 modified=1 的图片
    modified_images = [img for img in all_images if img.get("modified") == 1]
    modified_ids = {img["id"] for img in modified_images}

    # 仅保留这些图片对应的标注（孤儿标注一并剔除）
    kept_anns = [ann for ann in all_anns if ann.get("image_id") in modified_ids]

    # dict(data) 保持原顶层键及其顺序，仅替换 images / annotations 内容
    out = dict(data)
    out["images"] = modified_images
    out["annotations"] = kept_anns

    with open(DST_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"原文件：{len(all_images)} 张图片 / {len(all_anns)} 条标注")
    print(f"已修改：{len(modified_images)} 张图片 / {len(kept_anns)} 条标注")
    print(f"剔除未修改：{len(all_images) - len(modified_images)} 张图片 / "
          f"{len(all_anns) - len(kept_anns)} 条标注")
    print(f"已写入：{DST_JSON}")


if __name__ == "__main__":
    main()

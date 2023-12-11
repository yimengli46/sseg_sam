'''
run SAM on AVD with Detic detected bbox as prompt.
'''
import _pickle as cPickle
import bz2
import glob
import os
import sys
import json
import numpy as np
import torch
import matplotlib.pyplot as plt
import multiprocessing
import argparse
import cv2
sys.path.append("..")
from segment_anything import sam_model_registry, SamPredictor, SamAutomaticMaskGenerator  # NOQA


def show_mask(mask, ax, random_color=False):
    if random_color:
        color = np.concatenate([np.random.random(3), np.array([0.6])], axis=0)
    else:
        color = np.array([30/255, 144/255, 255/255, 0.6])
    h, w = mask.shape[-2:]
    mask_image = mask.reshape(h, w, 1) * color.reshape(1, 1, -1)
    ax.imshow(mask_image)


def show_points(coords, labels, ax, marker_size=375):
    pos_points = coords[labels == 1]
    neg_points = coords[labels == 0]
    ax.scatter(pos_points[:, 0], pos_points[:, 1], color='green',
               marker='*', s=marker_size, edgecolor='white', linewidth=1.25)
    ax.scatter(neg_points[:, 0], neg_points[:, 1], color='red', marker='*',
               s=marker_size, edgecolor='white', linewidth=1.25)


def show_box(box, ax):
    x0, y0 = box[0], box[1]
    w, h = box[2] - box[0], box[3] - box[1]
    ax.add_patch(plt.Rectangle((x0, y0), w, h, edgecolor='green', facecolor=(0, 0, 0, 0), lw=2))


def batch_segment_input_boxes(sam_predictor, image, boxes):
    H, W = image.shape[:2]
    sam_predictor.set_image(image)
    boxes = torch.tensor(boxes, device=sam_predictor.device)
    transformed_boxes = sam_predictor.transform.apply_boxes_torch(boxes, (H, W))

    masks, _, _ = sam_predictor.predict_torch(
        point_coords=None,
        point_labels=None,
        boxes=transformed_boxes,
        multimask_output=False
    )

    masks = masks.cpu().numpy()

    return masks


def run_sam_with_AVD_boxes(scene):
    print(f'scene = {scene}')
    # =========================== initialize sam model =================================
    sam_checkpoint = "../segment-anything/model_weights/sam_vit_h_4b8939.pth"
    model_type = "vit_h"

    device_id = gpu_Q.get()
    device = f"cuda:{device_id}"
    sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
    sam.to(device=device)

    sam_predictor = SamPredictor(sam)

    # ============================= run on AVD =======================================
    data_folder = 'data/ActiveVisionDataset'
    saved_folder = 'output/stage_c_sam_results_with_avd_instances/'
    scene_folder = f'{saved_folder}/{scene}'
    if not os.path.exists(scene_folder):
        os.mkdir(scene_folder)

    avd_annotation_folder = 'data/ActiveVisionDataset'

    img_name_list = [os.path.splitext(os.path.basename(x))[0]
                     for x in sorted(glob.glob(f'{data_folder}/{scene}/jpg_rgb/*.jpg'))]
    # img_name_list = img_name_list[:3]

    # load avd annotations
    with open(f'{avd_annotation_folder}/{scene}/annotations.json', 'r') as file:
        data = json.load(file)

    for img_name in img_name_list:
        print(f'img_name = {img_name}')

        image = cv2.imread(f'{data_folder}/{scene}/jpg_rgb/{img_name}.jpg')
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        H, W = image.shape[:2]

        # load image avd object annotation
        annotated_boxes = data[f'{img_name}.jpg']['bounding_boxes']

        num_instances = len(annotated_boxes)
        pred_boxes = []
        pred_classes = []

        # some images does not have avd instances
        if num_instances == 0:
            continue

        for i in range(num_instances):
            x1, y1, x2, y2, instance_id, _ = annotated_boxes[i]
            pred_boxes.append([x1, y1, x2, y2])
            pred_classes.append(instance_id)

        pred_boxes = np.array(pred_boxes).astype(np.int16)
        pred_classes = np.array(pred_classes).astype(np.int16)

        # run SAM
        masks = batch_segment_input_boxes(sam_predictor, image, pred_boxes)
        masks = masks[:, 0]  # num_masks x h x w

        # sort the masks decendingly. So the large masks in the front
        sorted_masks = sorted(enumerate(masks), key=(lambda x: x[1].sum()), reverse=True)
        sorted_bbox_idx, _ = zip(*sorted_masks)

        # convert all the masks into one simgle mask
        img_mask = np.zeros((H, W), dtype=np.uint16)
        for idx_bbox in list(sorted_bbox_idx):
            mask = masks[idx_bbox]
            mask_class = pred_classes[idx_bbox]
            img_mask[mask] = mask_class

        # for visualize the built mask
        unique_labels = np.unique(img_mask)
        vis_mask = np.zeros((H, W, 3))
        # skip label 0
        for idx in unique_labels[1:]:
            vis_mask[img_mask == idx] = np.random.random(3)

        # visualization bbox and mask
        fig, ax = plt.subplots(nrows=2, ncols=1, figsize=(20, 30))
        ax[0].imshow(image)
        for idx in range(masks.shape[0]):
            # print(f'mask.shape = {mask.shape}')
            show_mask(masks[idx], ax[0], random_color=True)
        for box in pred_boxes:
            show_box(box, ax[0])
        ax[0].get_xaxis().set_visible(False)
        ax[0].get_yaxis().set_visible(False)
        ax[1].imshow(vis_mask)
        ax[1].get_xaxis().set_visible(False)
        ax[1].get_yaxis().set_visible(False)
        fig.tight_layout()
        fig.savefig(f'{scene_folder}/{img_name}_vis.jpg')
        plt.close()

        cv2.imwrite(f'{scene_folder}/{img_name}_avd_instances_labels.png', img_mask)

        results = {}
        results['pred_boxes'] = pred_boxes
        results['pred_classes'] = pred_classes
        results['masks'] = masks
        with bz2.BZ2File(f'{scene_folder}/{img_name}_avd_instances_masks.pbz2', 'w') as fp:
            cPickle.dump(
                results,
                fp
            )

    gpu_Q.put(device_id)
    return


def mp_run_wrapper(args):
    run_sam_with_AVD_boxes(args[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--j', type=int, required=False, default=1)
    args = parser.parse_args()

    scene_list = ['Home_001_1', 'Home_001_2', 'Home_002_1', 'Home_003_1', 'Home_003_2', 'Home_004_1',
                  'Home_004_2', 'Home_005_1', 'Home_005_2', 'Home_006_1', 'Home_007_1', 'Home_008_1',
                  'Home_010_1', 'Home_011_1', 'Home_013_1', 'Home_014_1', 'Home_014_2', 'Home_015_1',
                  'Home_016_1', 'Office_001_1']

    # ====================== get the available GPU devices ============================
    visible_devices = os.environ["CUDA_VISIBLE_DEVICES"].split(",")
    devices = [int(dev) for dev in visible_devices]

    for device_id in devices:
        for _ in range(args.j):
            gpu_Q.put(device_id)

    with multiprocessing.Pool(processes=8) as pool:
        args0 = scene_list
        pool.map(mp_run_wrapper, list(zip(args0)))
        pool.close()


if __name__ == "__main__":
    gpu_Q = multiprocessing.Queue()
    main()

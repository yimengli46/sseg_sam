import glob
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import cv2

saved_folder = 'output/vote_sam_with_maskFormer_results'
sam_results_folder = 'output/ade20k_sam_results'
maskFormer_results_folder = '../MaskFormer/output/ade20k_maskformer_results'
data_folder = '/projects/kosecka/Datasets/ADE20K/Semantic_Segmentation'


img_list = np.load(f'{data_folder}/val_img_list.npy', allow_pickle=True)

for idx in range(img_list.shape[0]):
    img_dir = img_list[idx]['img']
    name = img_dir[18:-4]
    print(f'name = {name}')

    # load sam results
    sseg_sam = np.load(f'{sam_results_folder}/{name}.npy', allow_pickle=True)

    # load maskFormer results
    sseg_maskFormer = np.load(f'{maskFormer_results_folder}/{name}.npy', allow_pickle=True)

    H, W = sseg_sam.shape
    sseg_vote = np.zeros((H, W), dtype=np.int32)
    # go through each segment in sseg_sam
    segment_ids = np.unique(sseg_sam)
    for segment_id in segment_ids:
        mask = (sseg_sam == segment_id)
        # get the segment from maskFormer result
        segment = sseg_maskFormer[mask]
        counts = np.bincount(segment)
        most_common_idx = np.argmax(counts)
        sseg_vote[mask] = most_common_idx

    vis_sseg_vote = np.ones((H, W, 3))
    unique_labels = np.unique(sseg_vote)
    for idx in unique_labels:
        vis_sseg_vote[sseg_vote == idx] = np.random.random(3)

    fig, ax = plt.subplots(nrows=1, ncols=1, figsize=(20, 15))
    ax.imshow(vis_sseg_vote)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    fig.tight_layout()
    fig.savefig(f'{saved_folder}/{name}_vote_sseg.jpg')
    plt.close()

    np.save(f'{saved_folder}/{name}.npy', sseg_vote)

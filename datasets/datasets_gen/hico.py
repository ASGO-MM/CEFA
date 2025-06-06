"""
HICO detection dataset.
"""
from pathlib import Path

from PIL import Image
import json
from collections import defaultdict
import numpy as np

import torch
import torch.utils.data
import clip

import datasets.transforms as T
from datasets.hico_text_label import hico_text_label, hico_unseen_index



class HICODetection(torch.utils.data.Dataset):
    def __init__(self, img_set, img_folder, anno_file, clip_feats_folder, transforms, num_queries, args):
        self.img_set = img_set
        self.img_folder = img_folder
        self.clip_feates_folder = clip_feats_folder
        with open(anno_file, 'r') as f:
            self.annotations = json.load(f)
        self._transforms = transforms

        self.num_queries = num_queries

        self.unseen_index = hico_unseen_index.get(args.zero_shot_type, [])
        self._valid_obj_ids = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13,
                               14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
                               24, 25, 27, 28, 31, 32, 33, 34, 35, 36,
                               37, 38, 39, 40, 41, 42, 43, 44, 46, 47,
                               48, 49, 50, 51, 52, 53, 54, 55, 56, 57,
                               58, 59, 60, 61, 62, 63, 64, 65, 67, 70,
                               72, 73, 74, 75, 76, 77, 78, 79, 80, 81,
                               82, 84, 85, 86, 87, 88, 89, 90)
        self._valid_verb_ids = list(range(1, 118))

        self.text_label_dict = hico_text_label
        self.text_label_ids = list(self.text_label_dict.keys())
        if img_set == 'train' and len(self.unseen_index) != 0 and args.del_unseen:
            tmp = []
            for idx, k in enumerate(self.text_label_ids):
                if idx in self.unseen_index:
                    continue
                else:
                    tmp.append(k)
            self.text_label_ids = tmp

        total_anno = 0
        skip_anno = 0
        hoi_count = [0 for i in range(600)]
        select_hoi = [0 for i in range(600)]

        if img_set == 'train':
            self.ids = []
            for idx, img_anno in enumerate(self.annotations):
                new_img_anno = []
                skip_pair = []
                for hoi in img_anno['hoi_annotation']:
                    hoi_count[hoi['hoi_category_id'] - 1] += 1
                    if hoi['hoi_category_id'] - 1 in self.unseen_index:
                        skip_pair.append((hoi['subject_id'], hoi['object_id']))

                for hoi in img_anno['hoi_annotation']:
                    if hoi['subject_id'] >= len(img_anno['annotations']) or hoi['object_id'] >= len(
                            img_anno['annotations']):
                        new_img_anno = []
                        break
                    if (hoi['subject_id'], hoi['object_id']) not in skip_pair:
                        new_img_anno.append(hoi)
                    else:
                        skip_anno += 1
                if len(new_img_anno) > 0:
                    for pair_info in new_img_anno:
                        select_hoi[pair_info['hoi_category_id'] - 1] += 1
                    self.ids.append(idx)
                    img_anno['hoi_annotation'] = new_img_anno
                total_anno += len(new_img_anno)

                # import cv2
                # import os
                # data_root = os.path.join(os.getcwd(), 'data/hico_20160224_det/images/train2015')
                # image = cv2.imread(os.path.join(data_root, img_anno['file_name']))
        else:
            self.ids = list(range(len(self.annotations)))
        print("{} contains {} images and {} annotations".format(img_set, len(self.ids), total_anno))

        # UC RF top20 seen instance number
        # [4051, 3208, 2385, 2338, 2250, 2206, 2019, 1994, 1904, 1686, 1681, 1625,
        #         1590, 1525, 1519, 1488, 1469, 1366, 1269, 1265]

        # Default bottom200 class instance number
        # [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,
        #          1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,
        #          1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  2,  2,  2,  2,  2,  2,  2,
        #          2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,  2,
        #          3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,  3,
        #          3,  3,  4,  4,  4,  4,  4,  4,  4,  4,  5,  5,  5,  5,  5,  5,  5,  5,
        #          5,  5,  5,  5,  5,  5,  6,  6,  6,  6,  6,  6,  6,  6,  6,  7,  7,  7,
        #          7,  7,  7,  8,  8,  8,  9,  9,  9,  9,  9,  9, 10, 10, 10, 10, 10, 10,
        #         11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 12, 12, 12, 12, 12, 13, 13, 13,
        #         13, 13, 14, 14, 14, 14, 15, 15, 15, 15, 15, 15, 16, 16, 16, 16, 17, 17,
        #         17, 17, 17, 18, 18, 18, 18, 19, 19, 19, 20, 20, 20, 20, 21, 21, 21, 21,
        #         21, 22]

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _, self.clip_preprocess = clip.load(args.clip_model, device)
        # self.mask_patch=np.load("/public/home/zlj/Try/hico_mask.npz")

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, idx):
        img_anno = self.annotations[self.ids[idx]]

        img = Image.open(self.img_folder / img_anno['file_name']).convert('RGB')
        # img = img.resize((512, 512), Image.ANTIALIAS)
        if self.img_set == 'genfea':
            img = img.resize((512, 512), Image.ANTIALIAS)
        w, h = img.size

        if self.img_set == 'train' and len(img_anno['annotations']) > self.num_queries:
            img_anno['annotations'] = img_anno['annotations'][:self.num_queries]

        boxes = [obj['bbox'] for obj in img_anno['annotations']]
        # guard against no boxes via resizing
        boxes = torch.as_tensor(boxes, dtype=torch.float32).reshape(-1, 4)

        if self.img_set == 'train':
            # Add index for confirming which boxes are kept after image transformation
            classes = [(i, self._valid_obj_ids.index(obj['category_id'])) for i, obj in
                       enumerate(img_anno['annotations'])]
        else:
            classes = [self._valid_obj_ids.index(obj['category_id']) for obj in img_anno['annotations']]
        classes = torch.tensor(classes, dtype=torch.int64)

        target = {}
        target['orig_size'] = torch.as_tensor([int(h), int(w)])
        target['size'] = torch.as_tensor([int(h), int(w)])
        if self.img_set == 'train':
            boxes[:, 0::2].clamp_(min=0, max=w)
            boxes[:, 1::2].clamp_(min=0, max=h)
            keep = (boxes[:, 3] > boxes[:, 1]) & (boxes[:, 2] > boxes[:, 0])
            boxes = boxes[keep]
            classes = classes[keep]

            target['boxes'] = boxes
            target['labels'] = classes
            target['iscrowd'] = torch.tensor([0 for _ in range(boxes.shape[0])])
            target['area'] = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
            if isinstance(self._transforms, tuple):
                img_0, img_1 = self._transforms[0][0](img, target)[0], self._transforms[1][0](img, target)[0]
                img0, img1 = self._transforms[0][1](img_0, target)[0], self._transforms[1][1](img_1, target)[0]
                img, target = self._transforms[0][1](img_0, target)
                # target['mask_patch'] = torch.tensor(self.mask_patch[img_anno['file_name'].split('.')[0]], dtype=torch.float32)

            else:
                # if self._transforms is not None:
                #     img, target = self._transforms(img, target)
                if self._transforms is not None:
                    if isinstance(self._transforms, list):
                        img_0, target_0 = self._transforms[0](img, target)
                        img, target = self._transforms[1](img_0, target_0)
                    else:
                        img_0, target_0 = self._transforms[0](img, target)
                        img, target = self._transforms[1](img_0, target_0)
            # if self._transforms is not None:
            #     img_0, target_0 = self._transforms[0](img, target)
            #     img, target = self._transforms[1](img_0, target_0)
            clip_inputs = self.clip_preprocess(img_0)
            target['clip_inputs'] = clip_inputs
            kept_box_indices = [label[0] for label in target['labels']]

            target['labels'] = target['labels'][:, 1]

            obj_labels, verb_labels, sub_boxes, obj_boxes = [], [], [], []
            sub_obj_pairs = []
            hoi_labels = []
            for hoi in img_anno['hoi_annotation']:
                # print('hoi: ', hoi)
                if hoi['subject_id'] not in kept_box_indices or hoi['object_id'] not in kept_box_indices:
                    continue
                verb_obj_pair = (self._valid_verb_ids.index(hoi['category_id']),
                                 target['labels'][kept_box_indices.index(hoi['object_id'])])
                if verb_obj_pair not in self.text_label_ids:
                    continue

                sub_obj_pair = (hoi['subject_id'], hoi['object_id'])
                if sub_obj_pair in sub_obj_pairs:
                    verb_labels[sub_obj_pairs.index(sub_obj_pair)][self._valid_verb_ids.index(hoi['category_id'])] = 1
                    hoi_labels[sub_obj_pairs.index(sub_obj_pair)][self.text_label_ids.index(verb_obj_pair)] = 1
                else:
                    sub_obj_pairs.append(sub_obj_pair)
                    obj_labels.append(target['labels'][kept_box_indices.index(hoi['object_id'])])
                    verb_label = [0 for _ in range(len(self._valid_verb_ids))]
                    hoi_label = [0] * len(self.text_label_ids)
                    hoi_label[self.text_label_ids.index(verb_obj_pair)] = 1
                    verb_label[self._valid_verb_ids.index(hoi['category_id'])] = 1
                    sub_box = target['boxes'][kept_box_indices.index(hoi['subject_id'])]
                    obj_box = target['boxes'][kept_box_indices.index(hoi['object_id'])]
                    verb_labels.append(verb_label)
                    hoi_labels.append(hoi_label)
                    sub_boxes.append(sub_box)
                    obj_boxes.append(obj_box)

            target['filename'] = img_anno['file_name']
            
            # print('sub_obj_pairs: ', sub_obj_pairs)
            if len(sub_obj_pairs) == 0:
                target['obj_labels'] = torch.zeros((0,), dtype=torch.int64)
                target['verb_labels'] = torch.zeros((0, len(self._valid_verb_ids)), dtype=torch.float32)
                target['hoi_labels'] = torch.zeros((0, len(self.text_label_ids)), dtype=torch.float32)
                target['sub_boxes'] = torch.zeros((0, 4), dtype=torch.float32)
                target['obj_boxes'] = torch.zeros((0, 4), dtype=torch.float32)
            else:
                target['obj_labels'] = torch.stack(obj_labels)
                target['verb_labels'] = torch.as_tensor(verb_labels, dtype=torch.float32)
                target['hoi_labels'] = torch.as_tensor(hoi_labels, dtype=torch.float32)
                target['sub_boxes'] = torch.stack(sub_boxes)
                target['obj_boxes'] = torch.stack(obj_boxes)
        elif self.img_set == 'val':
            target['filename'] = img_anno['file_name']
            # target['hoilabel'] = img_anno['hoilabel']
            target['boxes'] = boxes
            target['labels'] = classes
            target['id'] = idx

            if self._transforms is not None:
                img_0, _ = self._transforms[0](img, None)
                img, _ = self._transforms[1](img_0, None)
            clip_inputs = self.clip_preprocess(img_0)
            target['clip_inputs'] = clip_inputs

            hois = []
            for hoi in img_anno['hoi_annotation']:
                hois.append((hoi['subject_id'], hoi['object_id'], self._valid_verb_ids.index(hoi['category_id'])))
            target['hois'] = torch.as_tensor(hois, dtype=torch.int64)
        else:
            target['filename'] = img_anno['file_name']
            target['hoilabel'] = img_anno['hoilabel']
            target['boxes'] = boxes
            target['labels'] = classes
            target['id'] = idx

            if self._transforms is not None:
                img_0, _ = self._transforms[0](img, None)
                img, _ = self._transforms[1](img_0, None)
            clip_inputs = self.clip_preprocess(img_0)
            target['clip_inputs'] = clip_inputs

            hois = []
            for hoi in img_anno['hoi_annotation']:
                hois.append((hoi['subject_id'], hoi['object_id'], self._valid_verb_ids.index(hoi['category_id'])))
            target['hois'] = torch.as_tensor(hois, dtype=torch.int64)
        if isinstance(self._transforms, tuple):
            return img0, img1, target
        else:
            return img, target
        # return img, target

    def set_rare_hois(self, anno_file):
        with open(anno_file, 'r') as f:
            annotations = json.load(f)

        if len(self.unseen_index) == 0:
            # no unseen categoruy, use rare to evaluate
            counts = defaultdict(lambda: 0)
            for img_anno in annotations:
                hois = img_anno['hoi_annotation']
                bboxes = img_anno['annotations']
                for hoi in hois:
                    triplet = (self._valid_obj_ids.index(bboxes[hoi['subject_id']]['category_id']),
                            self._valid_obj_ids.index(bboxes[hoi['object_id']]['category_id']),
                            self._valid_verb_ids.index(hoi['category_id']))
                    counts[triplet] += 1
            self.rare_triplets = []
            self.non_rare_triplets = []
            for triplet, count in counts.items():
                if count < 10:
                    self.rare_triplets.append(triplet)
                else:
                    self.non_rare_triplets.append(triplet)
            print("rare:{}, non-rare:{}".format(len(self.rare_triplets), len(self.non_rare_triplets)))
        else:
            self.rare_triplets = []
            self.non_rare_triplets = []
            for img_anno in annotations:
                hois = img_anno['hoi_annotation']
                bboxes = img_anno['annotations']
                for hoi in hois:
                    triplet = (self._valid_obj_ids.index(bboxes[hoi['subject_id']]['category_id']),
                            self._valid_obj_ids.index(bboxes[hoi['object_id']]['category_id']),
                            self._valid_verb_ids.index(hoi['category_id']))
                    if hoi['hoi_category_id'] - 1 in self.unseen_index:
                        self.rare_triplets.append(triplet)
                    else:
                        self.non_rare_triplets.append(triplet)
            print("unseen:{}, seen:{}".format(len(self.rare_triplets), len(self.non_rare_triplets)))

    def load_correct_mat(self, path):
        self.correct_mat = np.load(path)

def strong_transforms():

    normalize = T.Compose([
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    return [T.Compose([
        T.RandomHorizontalFlip(),
        T.ColorJitter(.4, .4, .4),
    ]),normalize]
def weak_transforms():

    normalize = T.Compose([
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    return [T.Compose([
        T.RandomHorizontalFlip(),
    ]),normalize]

# Add color jitter to coco transforms
def make_hico_transforms(image_set):
    normalize = T.Compose([
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    scales = [480, 512, 544, 576, 608, 640, 672, 704, 736, 768, 800]

    if image_set == 'train':
        return [T.Compose([
            T.RandomHorizontalFlip(),
            T.ColorJitter(.4, .4, .4),
            T.RandomSelect(
                T.RandomResize(scales, max_size=1333),
                T.Compose([
                    T.RandomResize([400, 500, 600]),
                    T.RandomSizeCrop(384, 600),
                    T.RandomResize(scales, max_size=1333),
                ]))]
            ),
            normalize
            ]

    if image_set == 'val':
        return [T.Compose([
            T.RandomResize([800], max_size=1333),
        ]),
            normalize
        ]

    raise ValueError(f'unknown {image_set}')
def genfea_transforms(image_set):
    normalize = T.Compose([
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    scales = [480, 512, 544, 576, 608, 640, 672, 704, 736, 768, 800]

    if image_set == 'train':
        return [T.Compose([
            T.RandomHorizontalFlip(),
            T.ColorJitter(.4, .4, .4),
            T.RandomSelect(
                T.RandomResize(scales, max_size=1333),
                T.Compose([
                    T.RandomResize([400, 500, 600]),
                    T.RandomSizeCrop(384, 600),
                    T.RandomResize(scales, max_size=1333),
                ]))]
            ),
            normalize
            ]

    if image_set == 'val':
        return [T.Compose([
            # T.RandomResize([800], max_size=1333),
        ]),
            normalize
        ]

    raise ValueError(f'unknown {image_set}')

def build(image_set, args):
    root = Path(args.hoi_path)
    assert root.exists(), f'provided HOI path {root} does not exist'
    if args.frac > 0:
        PATHS = {
            'train': (root / 'images' / 'train2015', root / 'annotations' / f'trainval_hico_{args.frac}.json',
                      root / 'clip_feats_pool' / 'train2015'),
            'val': (
                root / 'images' / 'test2015', root / 'annotations' / 'test_hico.json',
                root / 'clip_feats_pool' / 'test2015')
        }
    else:
        PATHS = {
            'train': (root / 'images' / 'train2015', root / 'annotations' / 'trainval_hico_oral.json',
                      root / 'clip_feats_pool' / 'train2015'),
            'val': (
                root / 'images' / 'test2015', root / 'annotations' / 'test_hico.json',
                root / 'clip_feats_pool' / 'test2015')
            # 'val': (root / 'images' / 'train2015', root / 'annotations' / 'trainval_hico_oral.json',
            #           root / 'clip_feats_pool' / 'train2015')
        }
        # PATHS = {
        #     'train': (root / 'images' / 'train2015', root / 'annotations' / 'trainval_hico_oral.json',
        #               root / 'clip_feats_pool' / 'train2015'),
        #     # 'val': (
        #     #     root / 'images' / 'train2015', root / 'annotations' / 'rare_tsne.json',
        #     #     root / 'clip_feats_pool' / 'train2015')
        #     'val': (
        #         Path('/public/home/zlj/HOICLIP/data/hico_20160224_det/images/train2015'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/rarefull.json', Path('/public/home/zlj/HOICLIP/data/hico_20160224_det/images/train2015'))
        # }
    CORRECT_MAT_PATH = root / 'annotations' / 'corre_hico.npy'
    if image_set == 'genfea':
        dataset = HICODetection('genfea', Path('/public/home/zlj/HOICLIP/data/hico_20160224_det/images/train2015'),
                                Path('/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/rare.json'), Path('/public/home/zlj/HOICLIP/data/hico_20160224_det/images/train2015'),
                                transforms=genfea_transforms('val'),
                                num_queries=args.num_queries, args=args)
        dataset.set_rare_hois(Path('/public/home/zlj/GENVLKT_MRT/data/hico_20160224_det/annotations/trainval_hico_oral.json'))
        dataset.load_correct_mat(CORRECT_MAT_PATH)
        return dataset
    if image_set == 'gen_train':
        # dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata+norare'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen_imgfull1.json', Path('/public/home/zlj/HOICLIP/data/gendata'),
        #                         transforms=strong_transforms(),
        #                         num_queries=args.num_queries, args=args)
        dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata'),
                                '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen_img.json', Path('/public/home/zlj/HOICLIP/data/gendata'),
                                transforms=strong_transforms(),
                                num_queries=args.num_queries, args=args)
        # dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata100'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen100_img.json', Path('/public/home/zlj/HOICLIP/data/gendata100'),
        #                         transforms=strong_transforms(),
        #                         num_queries=args.num_queries, args=args)
        # dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata150'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen150_img.json', Path('/public/home/zlj/HOICLIP/data/gendata150'),
        #                         transforms=strong_transforms(),
        #                         num_queries=args.num_queries, args=args)
        return dataset
    if image_set == 'gen_train_teacher':
        # dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata+norare'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen_imgfull1.json', Path('/public/home/zlj/HOICLIP/data/gendata'),
        #                         transforms=(strong_transforms(),weak_transforms()),
        #                         num_queries=args.num_queries, args=args)
        dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata'),
                                '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen_img.json', Path('/public/home/zlj/HOICLIP/data/gendata'),
                                transforms=(strong_transforms(),weak_transforms()),
                                num_queries=args.num_queries, args=args)
        # dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata100'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen100_img.json', Path('/public/home/zlj/HOICLIP/data/gendata100'),
        #                         transforms=(strong_transforms(),weak_transforms()),
        #                         num_queries=args.num_queries, args=args)
        # dataset = HICODetection('train', Path('/public/home/zlj/HOICLIP/data/gendata150'),
        #                         '/public/home/zlj/HOICLIP/data/hico_20160224_det/annotations/gen150_img.json', Path('/public/home/zlj/HOICLIP/data/gendata150'),
        #                         transforms=(strong_transforms(),weak_transforms()),
        #                         num_queries=args.num_queries, args=args)
        return dataset

    img_folder, anno_file, clip_feats_folder = PATHS[image_set]
    dataset = HICODetection(image_set, img_folder, anno_file, clip_feats_folder,
                            transforms=make_hico_transforms(image_set),
                            num_queries=args.num_queries, args=args)
    if image_set == 'val':
        dataset.set_rare_hois(PATHS['train'][1])
        dataset.load_correct_mat(CORRECT_MAT_PATH)
    return dataset

try:
    import torch
except ModuleNotFoundError:  # pragma: no cover - optional CPU runtime
    torch = None
import numpy as np
import cv2


def xyxy2xywh(x):
    """
    Converts a 1-d tensor/ndarray containing [x1, y1, x2, y2] coordinates of a
    bounding box to [x, y, w, h] where (x1, y1)=top-left, (x2, y2)=bottom-right
    Taken from YOLOv5: https://github.com/ultralytics/yolov5/blob/b564c1f3653a9b11038a80e348a34afbf59943be/utils/general.py
    """
    y = x.clone() if torch is not None and isinstance(x, torch.Tensor) else np.copy(x)
    y[:, 0] = (x[:, 0] + x[:, 2]) / 2  # x center
    y[:, 1] = (x[:, 1] + x[:, 3]) / 2  # y center
    y[:, 2] = x[:, 2] - x[:, 0]  # width
    y[:, 3] = x[:, 3] - x[:, 1]  # height
    return y


def crop_image(bbox, frame):
    """
    Takes in a single bbox (TLBR) format
    Returns the image crop in a numpy array
    """
    h, w = frame.shape[:2]
    left = min(max(0, int(bbox[0])), w - 1)
    top = min(max(0, int(bbox[1])), h - 1)
    right = min(max(0, int(bbox[2])), w - 1)
    bot = min(max(0, int(bbox[3])), h - 1)
    crop = frame[top:bot, left:right]
    return crop


def crop_images(bboxes, frame):
    """
    Takes in a list of bounding boxes (TLBR) format
    Returns a list of corresponding image crops
    """
    crops = []
    for bbox in bboxes:
        crop = crop_image(bbox, frame)
        crops.append(crop)
    return crops


def clean_bboxes(bboxes):
    """
    Removes the bboxes with height or width <=0
    args:
        bboxes: list or array of bboxes
    returns
        cleaned list of bboxes
    """
    bboxes = np.array(bboxes)
    bboxes = bboxes[bboxes[:, 3] - bboxes[:, 1] > 0]
    bboxes = bboxes[bboxes[:, 2] - bboxes[:, 0] > 0]
    return bboxes.tolist()


def bottom_mid_point(bbox_point, offset=0):
    """
    args:
        bbox_point: [array/tuple] in xyxy format
        offset: [int] default 0, increases y value of mid point
    returns:
        bottom mid point of the bbox (x,y) tuple
    """
    ret = bbox_point.copy()
    xtl = ret[0]
    ytl = ret[1]
    xbr = ret[2]
    ybr = ret[3]
    x = xtl + ((xbr - xtl) / 2.0)
    y = ybr + offset  # offset so point is around ankles not feet

    return (x, y)


def scale_coords(curr_img_shape, coords, target_img_shape, ratio_pad=None):
    """
    args:
        curr_img_shape: List of current image height and width
        coords: Tensor of [x1, y1, x2, y2] bounding box coordinates
        target_img_shape: List of target image height and width
        ratio_pad: List of ratio for both height and width to pad the image
    returns:
        coords: List of coordinates after scaling image
    """
    # Rescale coords (xyxy) from curr_img_shape to target_img_shape
    if ratio_pad is None:  # calculate from target_img_shape
        gain = min(
            curr_img_shape[0] / target_img_shape[0],
            curr_img_shape[1] / target_img_shape[1],
        )  # gain  = old / new
        pad = (
            (curr_img_shape[1] - target_img_shape[1] * gain) / 2,
            (curr_img_shape[0] - target_img_shape[0] * gain) / 2,
        )  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    coords[:, [0, 2]] -= pad[0]  # x padding
    coords[:, [1, 3]] -= pad[1]  # y padding
    coords[:, :4] /= gain
    clip_coords(coords, target_img_shape)
    return coords


def clip_coords(boxes, shape):
    """
    args:
        boxes: Tensor of [x1, y1, x2, y2] bounding box coordinates
        shape: Image shape (height, width)
    """
    if torch is not None and isinstance(boxes, torch.Tensor):  # faster individually
        boxes[:, 0].clamp_(0, shape[1])  # x1
        boxes[:, 1].clamp_(0, shape[0])  # y1
        boxes[:, 2].clamp_(0, shape[1])  # x2
        boxes[:, 3].clamp_(0, shape[0])  # y2
    else:  # np.array (faster grouped)
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, shape[1])  # x1, x2
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, shape[0])  # y1, y2


def intersection(box_a, box_b):
    # box: x1, y1, x2, y2
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    if x1 >= x2 or y1 >= y2:
        return 0.0
    return float((x2 - x1 + 1) * (y2 - y1 + 1))


def IoU(box_a, box_b):
    inter = intersection(box_a, box_b)
    box_a_area = (box_a[2] - box_a[0] + 1) * (box_a[3] - box_a[1] + 1)
    box_b_area = (box_b[2] - box_b[0] + 1) * (box_b[3] - box_b[1] + 1)
    union = box_a_area + box_b_area - inter
    return inter / float(max(union, 1))


def IoA(box_a, box_b):
    inter = intersection(box_a, box_b)
    box_a_area = (box_a[2] - box_a[0] + 1) * (box_a[3] - box_a[1] + 1)
    return inter / float(max(box_a_area, 1))


def bbox_centroid(bbox, offset=0):
    """
    bbox: [array/tuple] in xyxy format
    offset: [int] default 0, decreases or increases y value of mid point

    returns: centroid of the bbox (x,y) tuple
    """
    ret = bbox.copy()
    ret = (
        ret[0] + abs((ret[2] - ret[0]) / 2),
        ret[1] + abs((ret[1] - ret[3]) / 2) + offset,
    )
    return ret


def bbox_top_mid_point(bbox, offset=0):
    """
    bbox_point: [array/tuple] in xyxy format
    offset: [int] default 0, decreases y value of mid point

    returns: top mid point of the bbox (x,y) tuple
    """
    ret = bbox.copy()
    xtl = ret[0]
    ytl = ret[1]
    xbr = ret[2]
    ybr = ret[3]
    x = xtl + abs((xbr - xtl) / 2.0)
    y = ytl - offset  # offset from top, so not at head

    return (x, y)


def bbox_right_mid_point(bbox, offset=0):
    """
    bbox_point: [array/tuple] in xyxy format
    offset: [int] default 0, decreases x value of mid point

    returns: right mid point of the bbox (x,y) tuple
    """
    ret = bbox.copy()
    xtl = ret[0]
    ytl = ret[1]
    xbr = ret[2]
    ybr = ret[3]
    x = xbr - offset  # offset from right
    y = ytl + abs((ybr - ytl) / 2.0)

    return (x, y)


def bbox_left_mid_point(bbox, offset=0):
    """
    bbox_point: [array/tuple] in xyxy format
    offset: [int] default 0, increases x value of mid point

    returns: left mid point of the bbox (x,y) tuple
    """
    ret = bbox.copy()
    xtl = ret[0]
    ytl = ret[1]
    xbr = ret[2]
    ybr = ret[3]
    x = xtl + offset  # offset from left
    y = ytl + abs((ybr - ytl) / 2.0)

    return (x, y)


COLOR_PALETTE = [
    [0, 113, 188],
    [216, 82, 24],
    [236, 176, 31],
    [125, 46, 141],
    [118, 171, 47],
    [76, 189, 237],
    [161, 19, 46],
    [76, 76, 76],
    [153, 153, 153],
    [255, 0, 0],
    [255, 127, 0],
    [190, 190, 0],
    [0, 255, 0],
    [0, 0, 255],
    [170, 0, 255],
    [84, 84, 0],
    [84, 170, 0],
    [84, 255, 0],
    [170, 84, 0],
    [170, 170, 0],
    [170, 255, 0],
    [255, 84, 0],
    [255, 170, 0],
    [255, 255, 0],
    [0, 84, 127],
    [0, 170, 127],
    [0, 255, 127],
    [84, 0, 127],
    [84, 84, 127],
    [84, 170, 127],
    [84, 255, 127],
    [170, 0, 127],
    [170, 84, 127],
    [170, 170, 127],
    [170, 255, 127],
    [255, 0, 127],
    [255, 84, 127],
    [255, 170, 127],
    [255, 255, 127],
    [0, 84, 255],
    [0, 170, 255],
    [0, 255, 255],
    [84, 0, 255],
    [84, 84, 255],
    [84, 170, 255],
    [84, 255, 255],
    [170, 0, 255],
    [170, 84, 255],
    [170, 170, 255],
    [170, 255, 255],
    [255, 0, 255],
    [255, 84, 255],
    [255, 170, 255],
    [42, 0, 0],
    [84, 0, 0],
    [127, 0, 0],
    [170, 0, 0],
    [212, 0, 0],
    [255, 0, 0],
    [0, 42, 0],
    [0, 84, 0],
    [0, 127, 0],
    [0, 170, 0],
    [0, 212, 0],
    [0, 255, 0],
    [0, 0, 42],
    [0, 0, 84],
    [0, 0, 127],
    [0, 0, 170],
    [0, 0, 212],
    [0, 0, 255],
    [0, 0, 0],
    [36, 36, 36],
    [72, 72, 72],
    [109, 109, 109],
    [145, 145, 145],
    [182, 182, 182],
    [218, 218, 218],
    [255, 255, 255],
]


def draw_labels(text, x, y, frame, text_thickness=2, font_scale=0.6, text_padding=3):
    """
    Params:
        text: String - text to be printed
        x: Int - top left x coordinate of label
        y: Int - top left y coordinate of label
        frame: ndarray - target image/frame for label to be drawn on
        text_thickness: Int - thickness of text
        font_scale: float - size of text 1 being normal scale
        text_padding: Int - pixel offset from border of label to text
    Returns:
        No return object, annotates on frame passed in
    """
    label_size, base_line = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness
    )
    bg_x = x + label_size[0]
    bg_y = y + base_line
    cv2.rectangle(frame, (x, y - label_size[1]), (bg_x, bg_y), (0, 0, 0), -1)  # black bg
    cv2.putText(
        frame,
        text,
        (x + text_padding, y + text_padding),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (0, 0, 205),
        text_thickness,
    )  # red words


def draw_bbox(frame, boxes, scale, ids=None, classes=None):
    label = ""
    scalex = scale[0]
    scaley = scale[1]
    if ids is None:
        ids = [int(i) for i in range(len(boxes))]

    if classes is None:
        classes = [None] * len(boxes)

    for id, box, class_name in zip(ids, boxes, classes):
        left = int(box[0] / scalex)
        top = int(box[1] / scaley)
        right = int(box[2] / scalex)
        bottom = int(box[3] / scaley)

        try:
            color = COLOR_PALETTE[id % len(COLOR_PALETTE)]
        except Exception:
            color = (255, 0, 0)

        cv2.rectangle(frame, (left, top), (right, bottom), color, thickness=2)

        if ids[0] is not None:
            label = str(id)
        if classes[0] is not None:
            label += f" {class_name}"

        draw_labels(label, left, top, frame)

"""
Mask R-CNN

Written by Aaron Borger

"""

# Set matplotlib backend
# This has to be done before other importa that might
# set it, but only if we're running in script mode
# rather than being imported.
if __name__ == '__main__':
    import matplotlib
    # Agg backend to see figures
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

import os
import sys
import json
import datetime
import numpy as np
import skimage.draw
import skimage.color, skimage.io, skimage.transform

# Root directory of project
ROOT_DIR = os.path.abspath("Mask_RCNN/")

# Import Mask RCNN
sys.path.append(ROOT_DIR)
from mrcnn.config import Config
from mrcnn import model as modellib, utils
from mrcnn import visualize

# Path to trained wights file
COCO_WEIGHTS_PATH = os.path.join(ROOT_DIR, "mask_rcnn_coco.h5")

# Directory to save logs and model checkpoints, if not provided
# through the command line argument --logs
DEFAULT_LOGS_DIR = os.path.join(ROOT_DIR, "logs")


# Results directory
RESULTS_DIR = os.path.join(ROOT_DIR, "../results/")
############################################################
#  Configurations
############################################################

class blossomConfig(Config):
    """Configuration for training blossoms
    Derived from base Config class
    Overides Config values to blossom values
    """
    
    NAME = "blossom"
    
    # Lenova's one gpu only has 4GB memory, 12GB fits 2 images, hopefully 4GB can fit 1.
    # Barry Allen has two NVIDIA GTX 1080 ti's each with 11gb of physical vram, so should be able to do 2 images per gpu
    IMAGES_PER_GPU = 1
    
    # Number of GPUs 
    # Default = 1
    GPU_COUNT = 1
    
    # Number of classes (including background)
    NUM_CLASSES = 1 + 1 # Currently only using 1 blossom class
    
    # Number of training steps per epoch
    # Default = 1000
    STEPS_PER_EPOCH = 250
    
    # Minimum probability to be accepted as a detected object
    # Default = 0.7
    # DETECTION_MIN_CONFIDENCE = 0.9
    
    # Number of validation steps run at the end of every training epoch.
    # Bigger number = greater accuracy, but slower training
    # Default = 50
    VALIDATION_STEPS = 50
    
    # Number of required detections per image
    TRAIN_ROIS_PER_IMAGE = 50
    
    # Image Sizing
    # Modes include: None, Square, Pad64, crop
    IMAGE_RESIZE_MODE = "square" # Pads width and height with zeros
    IMAGE_MIN_DIM = 2048
    IMAGE_MAX_DIM = 2624
    
    
############################################################
#  Dataset
############################################################

class blossomDataset(utils.Dataset):
    
    def load_classes(self):
        self.add_class("blossom", 1, "blossom")
        
    def prep(self, class_map=None):
        def clean_name(name):
            """Returns a shorter version of object names for cleaner display."""
            return ",".join(name.split(",")[:1])
        
        self.num_classes = len(self.class_info)
        self.class_ids = np.arange(self.num_classes)
        self.class_names = [clean_name(c["name"]) for c in self.class_info]
        
    def load_blossom(self, dataset_dir, subset):
        """Loads a subset of blossom dataset.
        dataset_dir: Root of dataset directory.
        subset: load either train or val subset
        """
        # Add classes
        self.load_classes()
        
        # Check if dataset is train or validation
        assert subset in ["train", "val"]
        dataset_dir = os.path.join(dataset_dir, subset)
        
        # Load annotations
        annotations = json.load(open(os.path.join(dataset_dir, "via_region_data.json")))
        annotations = annotations['_via_img_metadata']
        annotations = list(annotations.values())
        
        # Add images
        for a in annotations:
            # Get x, y coordinates of points on outline.
            if type(a['regions']) is dict:
                polygons = [r['shape_attributes'] for r in a  ['regions'].values()]
            else:
                polygons = [r['shape_attributes'] for r in a['regions']]
                
            # Load_mask() needs image size to convert polygons to masks.
            # Do this by reading image, only possible with small dataset
            image_path = os.path.join(dataset_dir, a['filename'])
            image = skimage.io.imread(image_path)
            height, width = image.shape[:2]
        
            self.add_image(
                "blossom",
                image_id = a['filename'],
                path = image_path,
                width = width, height = height,
                polygons = polygons)
        
    def load_mask(self, image_id):
        """Generates a mask for an image.
        Returns:
         masks: A bool array of shape [height, widht, instance count] with
             one mask per instance.
         class_ids: a 1D array of class IDs of the instance masks.
         """
        
        # If doesn't come from blossom dataset, let parent class take care of it.
        image_info = self.image_info[image_id]
        if image_info["source"] != "blossom":
            return super(self.__class__, slef).load_mask(image_id)
        
        # Convert polygons to a bitmap mask of shape
        # [height, width, instance_count]
        info = self.image_info[image_id]
        mask = np.zeros([info["height"], info["width"], len(info["polygons"])],
                        dtype=np.uint8)
        for i, p in enumerate(info["polygons"]):
            # Get indexes of pixels inside the polygon and set them to 1
            rr, cc = skimage.draw.polygon(p['all_points_y'], p['all_points_x'])
            mask[rr, cc, i] = 1
        
        # Return mask, and array of class IDs of each instance. Since we have
        # one class ID only, we return an array of 1s
        return mask.astype(np.bool), np.ones([mask.shape[-1]], dtype=np.int32)
    
    def image_reference(self, image_id):
        """Return the path of the image."""
        info = self.image_info[image_id]
        if info["source"] == "balloon":
            return info["path"]
        else:
            super(self.__class__, self).image_reference(image_id)
            
############################################################
#  Training
############################################################

def train(model):
    """Train the model."""
    # Training dataset
    dataset_train = blossomDataset()
    dataset_train.load_blossom(args.dataset, "train")
    dataset_train.prepare()
    
    # Validation dataset
    dataset_val = blossomDataset()
    dataset_val.load_blossom(args.dataset, "val")
    dataset_val.prepare()
    
    print("Training network heads...")
    model.train(dataset_train, dataset_val,
                learning_rate = config.LEARNING_RATE,
                epochs = 1,
                layers = 'heads')

############################################################
#  RLE Encoding
############################################################

def rle_encode(mask):
    """Encodes a mask in Run Length Encoding (RLE).
    Returns a string of space-separated values.
    """
    assert mask.ndim == 2, "Mask must be of shape [Height, Width]"
    # Flatten it column wise
    m = mask.T.flatten()
    # Compute gradient. Equals 1 or -1 at transition points
    g = np.diff(np.concatenate([[0], m, [0]]), n=1)
    # 1-based indicies of transition points (where gradient != 0)
    rle = np.where(g != 0)[0].reshape([-1, 2]) + 1
    # Convert second index in each pair to lenth
    rle[:, 1] = rle[:, 1] - rle[:, 0]
    return " ".join(map(str, rle.flatten()))


def rle_decode(rle, shape):
    """Decodes an RLE encoded list of space separated
    numbers and returns a binary mask."""
    rle = list(map(int, rle.split()))
    rle = np.array(rle, dtype=np.int32).reshape([-1, 2])
    rle[:, 1] += rle[:, 0]
    rle -= 1
    mask = np.zeros([shape[0] * shape[1]], np.bool)
    for s, e in rle:
        assert 0 <= s < mask.shape[0]
        assert 1 <= e <= mask.shape[0], "shape: {}  s {}  e {}".format(shape, s, e)
        mask[s:e] = 1
    # Reshape and transpose
    mask = mask.reshape([shape[1], shape[0]]).T
    return mask


def mask_to_rle(image_id, mask, scores):
    "Encodes instance masks to submission format."
    assert mask.ndim == 3, "Mask must be [H, W, count]"
    # If mask is empty, return line with image ID only
    if mask.shape[-1] == 0:
        return "{},".format(image_id)
    # Remove mask overlaps
    # Multiply each instance mask by its score order
    # then take the maximum across the last dimension
    order = np.argsort(scores)[::-1] + 1  # 1-based descending
    mask = np.max(mask * np.reshape(order, [1, 1, -1]), -1)
    # Loop over instance masks
    lines = []
    for o in order:
        m = np.where(mask == o, 1, 0)
        # Skip if empty
        if m.sum() == 0.0:
            continue
        rle = rle_encode(m)
        lines.append("{}, {}".format(image_id, rle))
    return "\n".join(lines)

############################################################
#  Detection
############################################################

def load_image(image_id):
    # load image
    image = skimage.io.imread(image_id)
    # if grayscale. convert to RGB
    if image.ndim != 3:
        image = skimage.color.gray2rgb(image)
    # if has an alpha channel, remove it for consistency
    if image.shape[-1] == 4:
        image = image[..., :3]
    return image

def detect(model, dataset_dir, subset):
    """Run detection on images in the given directory."""
    print("Running on {}".format(dataset_dir))

    # Create directory
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
    submit_dir = "submit_{:%Y%m%dT%H%M%S}".format(datetime.datetime.now())
    submit_dir = os.path.join(RESULTS_DIR, submit_dir)
    os.makedirs(submit_dir)

    # Read dataset
    dataset = blossomDataset()
    dataset.load_classes()
    #dataset.load_blossom(dataset_dir, subset)
    dataset.prepare()
    sub_dir = os.path.join(dataset_dir, subset)
    image_list = os.listdir(sub_dir)
    # Load over images
    submission = []
    print('Number of pics: ', len(image_list))
    for image_id in image_list:
        image_path = os.path.join(sub_dir, image_id)
        # Load image and run detection
        image = load_image(image_path)
        # Detect objects
        try:
            r = model.detect([image], verbose=0)[0]
        except:
            print('Error occured')
        numBlossoms = r['rois'].shape[0]
        # Encode image to RLE. Returns a string of multiple lines
        source_id = image_id
        rle = mask_to_rle(source_id, r["masks"], r["scores"])
        submission.append(rle)
        # Save image with masks
        visualize.display_instances(
            image, r['rois'], r['masks'], r['class_ids'],
            dataset.class_names, r['scores'],
            show_bbox=False, show_mask=False,
            title="Number of Blossoms: " + str(numBlossoms))
        plt.savefig("{}/{}.png".format(submit_dir, image_id))

    # Save to csv file
    submission = "ImageId,EncodedPixels\n" + "\n".join(submission)
    file_path = os.path.join(submit_dir, "submit.csv")
    with open(file_path, "w") as f:
        f.write(submission)
    print("Saved to ", submit_dir)
############################################################
#  Counting
############################################################    
def countBlossoms(model, dataset_dir, subset):
    """Run detection on images in the given directory."""
    print("Running on {}".format(dataset_dir))

    # Create directory
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
    submit_dir = "submit_{:%Y%m%dT%H%M%S}".format(datetime.datetime.now())
    submit_dir = os.path.join(RESULTS_DIR, submit_dir)
    os.makedirs(submit_dir)

    # Read dataset
    dataset = blossomDataset()
    print(dataset.image_ids[0])
    dataset.load_blossom(dataset_dir, subset)
    dataset.prep()
    print('Number of pics: ', len(dataset.image_ids))
    submission = []
    print(dataset.image_ids[0])
    raise stop
    for image_id in dataset.image_ids:
        print("Working on image: ", image_id)
        # Load image and run detection
        image = dataset.load_image(image_id)
        # Detect objects
        try:
            r = model.detect([image], verbose=0)[0]
        except:
            print('Error occured')
        numBlossoms = r['rois'].shape[0]
        submission.append(str(numBlossoms))
    submission = "Blossom Count\n" + "\n".join(submission)
    file_path = os.path.join(submit_dir, "submit.csv")
    with open(file_path, 'w') as f:
        f.write(submission)
    print("Saved to ", submit_dir)
############################################################
#  Command Line
############################################################


if __name__=='__main__':
    import argparse
    
    # Parse command lin arguments
    parser=argparse.ArgumentParser(
        description='Train Mask R-CNN to count blossoms.')
    parser.add_argument("command",
                        metavar="<command>",
                        help="'train', 'eval', or 'count'")
    parser.add_argument('--dataset', required=False,
                        default='datasets',
                        metavar="/path/to/blossom/dataset/",
                        help='Directory of the Blossom dataset')
    parser.add_argument('--weights', required=True,
                        metavar="/path/to/weights.h5",
                        help="Path to weights .h5 file or 'coco'")
    parser.add_argument('--logs', required=False,
                        default=DEFAULT_LOGS_DIR,
                        metavar="/path/to/logs/",
                        help='Logs and checkpoints directory (default=logs/)')
    parser.add_argument('--subset', required=False,
                        default='test',
                        metavar="Dataset sub-directory",
                        help="Subset of dataset to run prediction on")
    args = parser.parse_args()
    
    # Validate arguments
    if args.command == "train":
        assert args.dataset, "Argument --dataset is required for training"
    elif args.command == "eval":
        assert args.subset, "Provide --subset to run prediction on"
    elif args.command == "count":
        assert args.subset, "Provide --subset to count on"
        
    print("Weights: ", args.weights)
    print("Dataset: ", args.dataset)
    if args.subset:
        print("Subset: ", args.subset)
    print("Logs: ", args.logs)
    
    # Configurations
    if args.command == "train":
        config = blossomConfig()
    else:
        class InferenceConfig(blossomConfig):
            # Set batch size to 1 since we'll be running inference on
            # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
            GPU_COUNT = 1
            IMAGES_PER_GPU = 1
            DETECTION_MIN_CONFIDENCE = 0
        config = InferenceConfig()
    config.display()
        
    # Create model
    if args.command == "train":
        model = modellib.MaskRCNN(mode="training", config=config,
                                  model_dir=args.logs)
    else:
        model = modellib.MaskRCNN(mode="inference", config=config,
                                  model_dir=args.logs)
        
    # Select weights file to load
    if args.weights.lower() == "coco":
        weights_path = COCO_WEIGHTS_PATH
        # Download weights file
        if not os.path.exists(weights_path):
            utils.download_trained_weights(weights_path)
    elif args.weights.lower() == "last":
            # Get last trained weights
            weights_path = model.find_last()
    else:
            weights_path = args.weights
            
    # Load weights
    print("Loading weights ", weights_path)
    if args.weights.lower() == "coco":
        # Exclude last layers because they require a matching number of classes
        model.load_weights(weights_path, by_name=True, exclude=[
            "mrcnn_class_logits", "mrcnn_bbox_fc",
            "mrcnn_bbox", "mrcnn_mask"])
    else:
        model.load_weights(weights_path, by_name=True)
        
    # Train or evaluate
    if args.command == "train":
        train(model)
    elif args.command == "eval":
        detect(model, args.dataset, args.subset)
    elif args.command == "count":
        countBlossoms(model, args.dataset, args.subset)
    else:
        print("'{}' is not recognized. "
              "Use 'train', 'eval', or 'count'".format(args.command))

    
    
